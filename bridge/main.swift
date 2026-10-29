// unplugged-bridge: lets the iPhone app reach this Mac with no Wi-Fi network at all, just by being nearby.
// It announces itself over Bonjour with Apple's peer-to-peer Wi-Fi (the AirDrop link: Bluetooth finds the devices,
// a direct Wi-Fi link carries the data) and passes every connection to the unplugged.ai server on 127.0.0.1:<BRIDGE_PORT>,
// a port where the server treats every client as remote (sign-in required, no guest mode, no account creation).
// Built and started by server.py. Usage: unplugged-bridge <server-port> <service-name>
import Foundation
import Network

let args = CommandLine.arguments
let target = NWEndpoint.Port(rawValue: UInt16(args.count > 1 ? args[1] : "8001") ?? 8001)!
let name = args.count > 2 ? args[2] : "unplugged.ai"

let params = NWParameters.tcp
params.includePeerToPeer = true
let listener: NWListener
do {
    listener = try NWListener(using: params)
} catch {
    FileHandle.standardError.write("bridge: cannot listen: \(error)\n".data(using: .utf8)!)
    exit(1)
}
listener.service = NWListener.Service(name: name, type: "_unplugged-p2p._tcp")

func pump(_ from: NWConnection, _ to: NWConnection) {
    from.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { data, _, done, error in
        if let data, !data.isEmpty {
            to.send(content: data, completion: .contentProcessed { e in
                if e != nil { from.cancel(); to.cancel() } else if !done && error == nil { pump(from, to) }
            })
        } else if !done && error == nil {
            pump(from, to)
        }
        if done || error != nil {
            to.send(content: nil, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { _ in })
            from.cancel()
        }
    }
}

listener.newConnectionHandler = { inbound in
    let outbound = NWConnection(host: "127.0.0.1", port: target, using: .tcp)
    outbound.stateUpdateHandler = { st in
        switch st {
        case .ready: pump(inbound, outbound); pump(outbound, inbound)
        case .failed, .cancelled: inbound.cancel()
        default: break
        }
    }
    inbound.stateUpdateHandler = { st in
        if case .failed = st { outbound.cancel() }
        if case .cancelled = st { outbound.cancel() }
    }
    inbound.start(queue: .main)
    outbound.start(queue: .main)
}
listener.stateUpdateHandler = { st in
    switch st {
    case .ready: print("bridge: ready on port \(listener.port?.rawValue ?? 0) as \(name)"); fflush(stdout)
    case .failed(let e): FileHandle.standardError.write("bridge: failed: \(e)\n".data(using: .utf8)!); exit(1)
    default: break
    }
}
listener.start(queue: .main)
signal(SIGTERM) { _ in exit(0) }
dispatchMain()
