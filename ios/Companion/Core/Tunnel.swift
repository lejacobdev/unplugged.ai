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
    /// A running peer-to-peer browse keeps the iPhone's direct link to the Mac awake. Without one, iOS powers the link down
    /// after a short while and new requests cannot reach the Mac (opening Settings, Servers fixed it only because that
    /// screen browses too).
    private var keepAwake: NWBrowser?
    private var service: String?
    private var localPort: UInt16 = 0
    private var lastName: String?
    private var lastRoute: (NWEndpoint, NWInterface?)?

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
        let b = NWBrowser(for: .bonjour(type: Tunnel.serviceType, domain: "local."), using: {
            let p = NWParameters()
            p.includePeerToPeer = true
            return p
        }())
        b.browseResultsChangedHandler = { _, _ in }
        b.start(queue: queue)
        lock.withLock {
            listener = l
            keepAwake?.cancel()
            keepAwake = b
        }
    }

    /// After the app was in the background the local listener can be stale: start it fresh.
    func restart() async {
        let name = lock.withLock { service }
        stop()
        if let name { try? await start(name) }
    }

    func stop() {
        lock.withLock {
            keepAwake?.cancel()
            keepAwake = nil
            listener?.cancel()
            listener = nil
            service = nil
            localPort = 0
        }
    }

    /// Connects one local request to the Mac. Two attempts race: one over any path (same Wi-Fi works too) and one over the
    /// direct peer-to-peer link only, because a Wi-Fi that blocks devices from talking to each other (office, school,
    /// hotel) would otherwise stall the first. Whichever is ready first carries the request; the other is closed.
    private func bridge(_ local: NWConnection, to name: String) {
        let endpoint = NWEndpoint.service(name: name, type: Tunnel.serviceType, domain: "local.", interface: nil)
        let any = NWParameters.tcp
        any.includePeerToPeer = true
        let direct = NWParameters.tcp
        direct.includePeerToPeer = true
        direct.prohibitedInterfaceTypes = [.wifi, .wiredEthernet, .cellular, .loopback]
        var attempts = [NWConnection(to: endpoint, using: any), NWConnection(to: endpoint, using: direct)]
        // The address and link of the last connection that worked: reusing it skips the slow name lookup over the air.
        if let (cachedEndpoint, cachedInterface) = lock.withLock({ () -> (NWEndpoint, NWInterface?)? in lastName == name ? lastRoute : nil }) {
            let known = NWParameters.tcp
            known.includePeerToPeer = true
            if let cachedInterface { known.requiredInterface = cachedInterface }
            attempts.insert(NWConnection(to: cachedEndpoint, using: known), at: 0)
        }
        let winner = Once()
        var failed = 0
        for remote in attempts {
            remote.stateUpdateHandler = { [weak self] st in
                switch st {
                case .ready:
                    winner.run {
                        for other in attempts where other !== remote { other.cancel() }
                        if let ep = remote.currentPath?.remoteEndpoint {
                            let iface = remote.currentPath?.availableInterfaces.first
                            self?.lock.withLock { self?.lastName = name; self?.lastRoute = (ep, iface) }
                        }
                        remote.stateUpdateHandler = { st in
                            switch st {
                            case .failed, .cancelled: local.cancel()
                            default: break
                            }
                        }
                        local.stateUpdateHandler = { st in
                            switch st {
                            case .failed, .cancelled: remote.cancel()
                            default: break
                            }
                        }
                        self?.pump(local, remote)
                        self?.pump(remote, local)
                    }
                case .failed:
                    failed += 1   // runs on the tunnel queue only
                    if failed == attempts.count { local.cancel(); self?.lock.withLock { self?.lastRoute = nil } }
                default: break
                }
            }
        }
        local.stateUpdateHandler = { st in
            switch st {
            case .failed, .cancelled: attempts.forEach { $0.cancel() }
            default: break
            }
        }
        local.start(queue: queue)
        attempts.forEach { $0.start(queue: queue) }
        // Not connected to the Mac within 20 s (out of reach, or a stale link after the app was in the background):
        // close everything so the request fails with an error instead of loading forever. The first link over the air
        // can take several seconds to come up.
        queue.asyncAfter(deadline: .now() + 20) { [weak self] in
            if !attempts.contains(where: { $0.state == .ready }) {
                attempts.forEach { $0.cancel() }
                local.cancel()
                self?.lock.withLock { self?.lastRoute = nil }
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
