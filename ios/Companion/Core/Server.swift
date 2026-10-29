import Foundation
import Observation
import Security

/// One unplugged.ai server the user has saved.
struct Server: Codable, Identifiable, Hashable {
    var id = UUID()
    var name: String
    var host: String
    var port: Int
    var secure: Bool
    /// Accept a self-signed certificate for this server (the one setup_https.sh makes). Only for your own Mac.
    var trustCertificate = false
    var userName: String?
    var lastUsed = Date()
    /// Set for a Mac reached over the nearby (peer-to-peer) link: its Bonjour service name. host/port are then unused.
    var nearbyName: String?

    var isNearby: Bool { nearbyName != nil }

    var baseURL: URL {
        if let n = nearbyName {
            return URL(string: "http://127.0.0.1:\(Tunnel.shared.port(for: n) ?? 9)")!
        }
        var c = URLComponents()
        c.scheme = secure ? "https" : "http"
        c.host = host
        let standard = secure ? 443 : 80
        if port != standard { c.port = port }
        return c.url ?? URL(string: "http://127.0.0.1:8000")!
    }

    var displayAddress: String {
        if isNearby { return "Nearby, no network needed" }
        let standard = secure ? 443 : 80
        return (secure ? "https://" : "http://") + (host.contains(":") ? "[\(host)]" : host) + (port == standard ? "" : ":\(port)")
    }

    func url(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)?.absoluteURL ?? baseURL
    }
}

/// What the user typed as an address, turned into scheme, host and port.
/// Rules: nothing typed but a host means http on port 8000 (how unplugged.ai starts). A scheme without a port means the
/// standard port of that scheme (for a domain behind a proxy). Port 8443 without a scheme means https.
struct ParsedAddress: Equatable {
    var host: String
    var port: Int
    var secure: Bool

    static func parse(_ raw: String) -> ParsedAddress? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains(" ") else { return nil }
        let hadScheme = text.lowercased().hasPrefix("http://") || text.lowercased().hasPrefix("https://")
        if !hadScheme { text = "http://" + text }
        guard let c = URLComponents(string: text), var host = c.host, !host.isEmpty else { return nil }
        if host.hasPrefix("[") && host.hasSuffix("]") { host = String(host.dropFirst().dropLast()) }
        var secure = c.scheme?.lowercased() == "https"
        let port: Int
        if let p = c.port {
            port = p
            if !hadScheme && p == 8443 { secure = true }
        } else if hadScheme {
            port = secure ? 443 : 80
        } else {
            port = 8000
        }
        guard (1...65535).contains(port) else { return nil }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: ".-:_%"))
        guard host.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { return nil }
        return ParsedAddress(host: host, port: port, secure: secure)
    }
}

/// Saved servers and which one is active. Stored in UserDefaults; session tokens live in the Keychain.
@MainActor @Observable
final class ServerStore {
    static let shared = ServerStore()
    private let key = "servers.v1"
    private let activeKey = "servers.active"

    var servers: [Server] = [] { didSet { save() } }
    var activeID: UUID? { didSet { UserDefaults.standard.set(activeID?.uuidString, forKey: activeKey) } }

    var active: Server? { servers.first { $0.id == activeID } }

    private init() {
        if let data = UserDefaults.standard.data(forKey: key), let list = try? JSONDecoder().decode([Server].self, from: data) {
            servers = list
        }
        if let s = UserDefaults.standard.string(forKey: activeKey), let id = UUID(uuidString: s), servers.contains(where: { $0.id == id }) {
            activeID = id
        }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(servers) { UserDefaults.standard.set(data, forKey: key) }
    }

    /// Adds the server, or returns the saved one with the same address.
    @discardableResult
    func add(_ s: Server) -> Server {
        if let i = servers.firstIndex(where: { s.nearbyName != nil ? $0.nearbyName == s.nearbyName : ($0.nearbyName == nil && $0.host.lowercased() == s.host.lowercased() && $0.port == s.port && $0.secure == s.secure) }) {
            return servers[i]
        }
        servers.append(s)
        return s
    }

    func update(_ s: Server) {
        if let i = servers.firstIndex(where: { $0.id == s.id }) { servers[i] = s }
    }

    func remove(_ s: Server) {
        Keychain.delete(account: s.id.uuidString)
        servers.removeAll { $0.id == s.id }
        if activeID == s.id { activeID = nil }
    }

    func activate(_ s: Server) {
        var s = s
        s.lastUsed = Date()
        update(s)
        activeID = s.id
    }

    func disconnect() { activeID = nil }

    /// Read without the main actor (WatchConnectivity callbacks run on a background queue).
    nonisolated static func activeServerSnapshot() -> Server? {
        guard let s = UserDefaults.standard.string(forKey: "servers.active"), let id = UUID(uuidString: s),
              let data = UserDefaults.standard.data(forKey: "servers.v1"),
              let list = try? JSONDecoder().decode([Server].self, from: data) else { return nil }
        return list.first { $0.id == id }
    }
}

/// The session token of each server, kept in the Keychain (this device only).
enum Keychain {
    private static let service = "dev.lejacob.unplugged.session"

    static func set(_ value: String, account: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var add = query
            add[kSecValueData as String] = data
            add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            SecItemAdd(add as CFDictionary, nil)
        }
    }

    static func get(account: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(account: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
    }
}
