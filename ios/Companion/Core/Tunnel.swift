import Foundation
import Network

/// Reaches a Mac nearby without any shared network: Apple's peer-to-peer Wi-Fi (the AirDrop link, found over Bluetooth).
/// URLSession cannot use that link directly, so the app runs a tiny proxy on 127.0.0.1 and pipes each connection to the
/// Mac's unplugged-bridge (service _unplugged-p2p._tcp). Everything else in the app just talks to http://127.0.0.1:<port>.
final class Tunnel: @unchecked Sendable {
    static let shared = Tunnel()
    static let serviceType = "_unplugged-p2p._tcp"

    private let queue = DispatchQueue(label: "dev.lejacob.unplugged.tunnel")
    private let lock = NSLock()
    private var listener: NWListener?
    private var service: String?
    private var localPort: UInt16 = 0

    /// The local port for this Mac's service, when the proxy is running.
    func port(for name: String) -> Int? {
        lock.withLock { service == name && localPort != 0 ? Int(localPort) : nil }
    }

    /// Starts (or keeps) the proxy for one nearby Mac. Returns when it accepts connections.
    func start(_ name: String) async throws {
        let running = lock.withLock { () -> Bool in
            if service == name, localPort != 0, let l = listener, l.state == .ready { return true }
            listener?.cancel()
            listener = nil
            localPort = 0
            service = name
            return false
        }
        if running { return }

        let params = NWParameters.tcp
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        params.allowLocalEndpointReuse = true
        let l = try NWListener(using: params)
        l.newConnectionHandler = { [weak self] local in self?.bridge(local, to: name) }
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            let once = Once()
            l.stateUpdateHandler = { [weak self] st in
                switch st {
                case .ready:
                    self?.lock.withLock { self?.localPort = l.port?.rawValue ?? 0 }
                    once.run { cont.resume() }
                case .failed(let e):
                    self?.lock.withLock { self?.localPort = 0 }
                    once.run { cont.resume(throwing: e) }
                case .cancelled:
                    once.run { cont.resume(throwing: CancellationError()) }
                default: break
                }
            }
            l.start(queue: queue)
        }
        lock.withLock { listener = l }
    }

    /// After the app was in the background the local listener can be stale: start it fresh.
    func restart() async {
        let name = lock.withLock { service }
        stop()
        if let name { try? await start(name) }
    }

    func stop() {
        lock.withLock {
            listener?.cancel()
            listener = nil
            service = nil
            localPort = 0
        }
    }

    private func bridge(_ local: NWConnection, to name: String) {
        let p = NWParameters.tcp
        p.includePeerToPeer = true
        let remote = NWConnection(to: .service(name: name, type: Tunnel.serviceType, domain: "local.", interface: nil), using: p)
        remote.stateUpdateHandler = { [weak self] st in
            switch st {
            case .ready:
                self?.pump(local, remote)
                self?.pump(remote, local)
            case .failed, .cancelled:
                local.cancel()
            default: break
            }
        }
        local.stateUpdateHandler = { st in
            switch st {
            case .failed, .cancelled: remote.cancel()
            default: break
            }
        }
        local.start(queue: queue)
        remote.start(queue: queue)
        // Not connected to the Mac within 10 s (out of reach, or a stale link after the app was in the background):
        // close both sides so the request fails with an error instead of loading forever.
        queue.asyncAfter(deadline: .now() + 10) {
            if remote.state != .ready {
                remote.cancel()
                local.cancel()
            }
        }
    }

    private func pump(_ from: NWConnection, _ to: NWConnection) {
        from.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { [weak self] data, _, done, error in
            if let data, !data.isEmpty {
                to.send(content: data, completion: .contentProcessed { e in
                    if e != nil { from.cancel(); to.cancel() } else if !done && error == nil { self?.pump(from, to) }
                })
            } else if !done && error == nil {
                self?.pump(from, to)
            }
            if done || error != nil {
                to.send(content: nil, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { _ in })
                from.cancel()
            }
        }
    }
}

/// Runs a block at most once, from any thread.
final class Once: @unchecked Sendable {
    private let lock = NSLock()
    private var done = false
    func run(_ f: () -> Void) {
        let first = lock.withLock { () -> Bool in if done { return false }; done = true; return true }
        if first { f() }
    }
}
