import Foundation
import Network
import Observation

/// A server announced on the local network (Bonjour, _unplugged._tcp).
struct FoundServer: Identifiable, Hashable {
    var id: String { name }
    var name: String          // "unplugged.ai on MacBook-Pro"
    var host: String          // IPv4 address, or the .local name when no address was found
    var port: Int
    var tlsPort: Int?
    var nearby = false

    var macName: String {
        name.hasPrefix("unplugged.ai on ") ? String(name.dropFirst("unplugged.ai on ".count)) : name
    }
}

/// Browses the local network for unplugged.ai servers. Starting it the first time makes iOS ask for Local Network access.
@MainActor @Observable
final class Discovery {
    enum State: Equatable { case idle, searching, denied, failed(String) }

    var found: [FoundServer] = []
    /// Macs reachable over the peer-to-peer link (no shared network needed).
    var nearby: [FoundServer] = []
    var state: State = .idle
    private var browser: NWBrowser?
    private var p2pBrowser: NWBrowser?
    private var resolving: [String: NWConnection] = [:]

    func start() {
        stop()
        state = .searching
        let params = NWParameters()
        params.includePeerToPeer = false
        let b = NWBrowser(for: .bonjourWithTXTRecord(type: "_unplugged._tcp", domain: "local."), using: params)
        b.stateUpdateHandler = { [weak self] st in
            Task { @MainActor in self?.handle(st) }
        }
        b.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in self?.update(results) }
        }
        b.start(queue: .main)
        browser = b

        let p2p = NWParameters()
        p2p.includePeerToPeer = true
        let pb = NWBrowser(for: .bonjour(type: Tunnel.serviceType, domain: "local."), using: p2p)
        pb.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in
                self?.nearby = results.compactMap { r in
                    guard case .service(let name, _, _, _) = r.endpoint else { return nil }
                    return FoundServer(name: name, host: "", port: 0, tlsPort: nil, nearby: true)
                }.sorted { $0.name < $1.name }
            }
        }
        pb.start(queue: .main)
        p2pBrowser = pb
    }

    func stop() {
        browser?.cancel()
        browser = nil
        p2pBrowser?.cancel()
        p2pBrowser = nil
        resolving.values.forEach { $0.cancel() }
        resolving = [:]
        if state == .searching { state = .idle }
    }

    private func handle(_ st: NWBrowser.State) {
        switch st {
        case .ready: state = .searching
        case .failed(let e), .waiting(let e):
            if case .dns(let code) = e, code == -65570 { state = .denied }   // kDNSServiceErr_PolicyDenied: Local Network is off for this app
            else { state = .failed(e.localizedDescription) }
        case .cancelled: break
        default: break
        }
    }

    private func update(_ results: Set<NWBrowser.Result>) {
        var names = Set<String>()
        for r in results {
            guard case .service(let name, _, _, _) = r.endpoint else { continue }
            names.insert(name)
            var tls: Int?
            if case .bonjour(let txt) = r.metadata, let t = txt["tls"], let p = Int(t) { tls = p }
            if found.contains(where: { $0.name == name }) || resolving[name] != nil { continue }
            resolve(r.endpoint, name: name, tls: tls)
        }
        found.removeAll { !names.contains($0.name) }
    }

    /// Bonjour gives a service name; a short TCP connection tells us the address and port behind it (IPv4 preferred).
    private func resolve(_ endpoint: NWEndpoint, name: String, tls: Int?) {
        let params = NWParameters.tcp
        if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options { ip.version = .v4 }
        let c = NWConnection(to: endpoint, using: params)
        resolving[name] = c
        c.stateUpdateHandler = { [weak self] st in
            Task { @MainActor in
                guard let self else { return }
                switch st {
                case .ready:
                    if case .hostPort(let host, let port) = c.currentPath?.remoteEndpoint ?? c.endpoint {
                        var h: String
                        switch host {
                        case .ipv4(let a): h = "\(a)"
                        case .ipv6(let a): h = "\(a)"
                        case .name(let n, _): h = n
                        @unknown default: h = "\(host)"
                        }
                        if let pct = h.firstIndex(of: "%") { h = String(h[..<pct]) }   // drop the interface suffix
                        let s = FoundServer(name: name, host: h, port: Int(port.rawValue), tlsPort: tls)
                        if !self.found.contains(where: { $0.name == name }) { self.found.append(s); self.found.sort { $0.name < $1.name } }
                    }
                    c.cancel()
                    self.resolving[name] = nil
                case .failed, .cancelled:
                    self.resolving[name] = nil
                default: break
                }
            }
        }
        c.start(queue: .main)
    }
}
