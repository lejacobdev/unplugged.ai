import Foundation

enum APIError: LocalizedError {
    case notUnplugged
    case signedOut
    case server(String)
    case network(String)

    var errorDescription: String? {
        switch self {
        case .notUnplugged: return "Something answered at this address, but it is not unplugged.ai."
        case .signedOut: return "You are signed out. Sign in again."
        case .server(let m): return m
        case .network(let m): return m
        }
    }
}

struct PingInfo {
    var name: String
    var accounts: Bool
    var tlsPort: Int?
    var legacy: Bool   // an older unplugged.ai without /api/ping
}

struct ModelInfo: Identifiable, Hashable {
    var name: String
    var label: String
    var desc: String
    var id: String { name }
}

struct ChatSummary: Identifiable, Hashable {
    var id: String
    var title: String
    var updated: Date
    var count: Int
    var project: String?
}

struct ChatAttachment: Hashable {
    var kind: String        // image_job, run, music, music_draft, music_job
    var job: String?
    var runID: String?
    var files: [String]     // run files that are pictures
    var allFiles: [String] = []   // every file a run or document tool made (downloads)
    var musicID: String?
    var caption = ""
    var lyrics = ""
    var length = "medium"
}

struct ChatMessage: Identifiable, Hashable {
    var id = UUID()
    var role: String        // user, assistant, tool
    var content: String
    var thinking: String = ""
    var toolName: String?
    var attachment: ChatAttachment?
    var images: [String] = []   // pictures the user attached (served at /img/<name>)
    var files: [String] = []    // names of files the user attached
    var localImage: Data?       // a picture just sent, shown until the server's copy is loaded
    var fileNames: [String] = []
}

enum StreamEvent {
    case thinking(String)
    case token(String)
    case toolStart(String)
    case toolResult(String, String, ChatAttachment?)
    case error(String)
    case done
}

/// Talks to one unplugged.ai server. The session cookie is sent by hand (never through the shared cookie store),
/// so several servers and the web view stay separate and predictable.
final class API: NSObject, URLSessionDelegate, @unchecked Sendable {
    static let cookieName = "jacobai_session"
    let server: Server
    lazy var session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.httpShouldSetCookies = false
        cfg.httpCookieAcceptPolicy = .never
        cfg.timeoutIntervalForRequest = 30
        cfg.timeoutIntervalForResource = 3600
        cfg.waitsForConnectivity = false
        return URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }()

    init(_ server: Server) { self.server = server }

    /// URLSession keeps its delegate alive: call this when a client is no longer needed.
    func invalidate() { session.finishTasksAndInvalidate() }

    /// Checks an address once with a short-lived client.
    static func probe(_ s: Server) async throws -> PingInfo {
        let a = API(s)
        defer { a.invalidate() }
        return try await a.ping()
    }

    var token: String? { Keychain.get(account: server.id.uuidString) }

    // MARK: requests

    func request(_ path: String, method: String = "GET", json: Any? = nil, body: Data? = nil, contentType: String? = nil, timeout: TimeInterval = 30) -> URLRequest {
        var r = URLRequest(url: server.url(path), timeoutInterval: timeout)
        r.httpMethod = method
        r.httpShouldHandleCookies = false
        if let t = token { r.setValue("\(API.cookieName)=\(t)", forHTTPHeaderField: "Cookie") }
        if let json {
            r.httpBody = try? JSONSerialization.data(withJSONObject: json)
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        } else if let body {
            r.httpBody = body
            r.setValue(contentType ?? "application/octet-stream", forHTTPHeaderField: "Content-Type")
        }
        return r
    }

    func send(_ r: URLRequest) async throws -> (Data, HTTPURLResponse) {
        do {
            let (data, resp): (Data, URLResponse)
            do {
                (data, resp) = try await session.data(for: r)
            } catch let e as URLError where server.isNearby && [.networkConnectionLost, .cannotConnectToHost, .timedOut].contains(e.code) {
                // the direct link to a nearby Mac drops now and then: try once more on a fresh connection
                if let n = server.nearbyName { try? await Tunnel.shared.start(n) }
                try await Task.sleep(for: .milliseconds(600))
                (data, resp) = try await session.data(for: r)
            }
            guard let http = resp as? HTTPURLResponse else { throw APIError.network("No answer from the server.") }
            return (data, http)
        } catch let e as APIError {
            throw e
        } catch let e as URLError {
            throw APIError.network(API.describe(e, server: server))
        }
    }

    static func describe(_ e: URLError, server: Server) -> String {
        if server.isNearby, [.cannotConnectToHost, .networkConnectionLost, .timedOut, .notConnectedToInternet].contains(e.code) {
            return "\(server.name) was found nearby, but the connection to it did not come up. Keep the iPhone close to the Mac, with Wi-Fi and Bluetooth switched on on both (no network needed), keep the Mac awake, and try again."
        }
        switch e.code {
        case .notConnectedToInternet: return "This iPhone is offline. Join the same Wi-Fi as your Mac, or a VPN to it."
        case .timedOut: return "\(server.displayAddress) did not answer in time. Is the Mac awake and unplugged.ai running?"
        case .cannotConnectToHost, .networkConnectionLost: return "Nothing is running at \(server.displayAddress). Start unplugged.ai on the Mac (./start.sh), and check the port."
        case .cannotFindHost, .dnsLookupFailed: return "The address \(server.host) could not be found. Check for typos, or use the Mac's IP address."
        case .serverCertificateUntrusted, .serverCertificateHasUnknownRoot, .serverCertificateNotYetValid, .serverCertificateHasBadDate, .secureConnectionFailed:
            return "The secure connection was refused because the certificate is not trusted. Install the certificate profile from your Mac, or turn on \"Trust this server's certificate\" in the server's settings."
        case .appTransportSecurityRequiresSecureConnection: return "This address needs https."
        default: return e.localizedDescription
        }
    }

    func json(_ data: Data) -> [String: Any] {
        (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    func checked(_ r: (Data, HTTPURLResponse)) throws -> [String: Any] {
        let (data, resp) = r
        let obj = json(data)
        if resp.statusCode == 401 { throw APIError.signedOut }
        if resp.statusCode >= 400 { throw APIError.server(obj["error"] as? String ?? "The server answered with error \(resp.statusCode).") }
        return obj
    }

    // MARK: endpoints

    func ping() async throws -> PingInfo {
        let (data, resp) = try await send(request("/api/ping", timeout: 6))
        let obj = json(data)
        if resp.statusCode == 200, obj["app"] as? String == "unplugged.ai" {
            return PingInfo(name: obj["name"] as? String ?? server.host, accounts: obj["accounts"] as? Bool ?? true, tlsPort: obj["tls_port"] as? Int, legacy: false)
        }
        if resp.statusCode == 401, obj["error"] as? String == "Please sign in." {   // older servers ask to sign in for everything
            return PingInfo(name: server.host, accounts: true, tlsPort: nil, legacy: true)
        }
        throw APIError.notUnplugged
    }

    /// Signs in and stores the session token in the Keychain.
    func login(name: String, password: String) async throws {
        let (data, resp) = try await send(request("/api/auth/login", method: "POST", json: ["name": name, "password": password]))
        if resp.statusCode != 200 {
            throw APIError.server(json(data)["error"] as? String ?? "Sign-in failed (\(resp.statusCode)).")
        }
        let headers = resp.allHeaderFields.reduce(into: [String: String]()) { out, kv in
            if let k = kv.key as? String, let v = kv.value as? String { out[k] = v }
        }
        let cookies = HTTPCookie.cookies(withResponseHeaderFields: headers, for: server.baseURL)
        guard let c = cookies.first(where: { $0.name == API.cookieName }) else { throw APIError.server("The server did not start a session.") }
        Keychain.set(c.value, account: server.id.uuidString)
    }

    func logout() async {
        _ = try? await send(request("/api/auth/logout", method: "POST", json: [String: Any]()))
        Keychain.delete(account: server.id.uuidString)
    }

    func me() async throws -> (name: String, kind: String) {
        let obj = try checked(try await send(request("/api/me")))
        return (obj["name"] as? String ?? "", obj["kind"] as? String ?? "user")
    }

    func status() async throws -> (ok: Bool, models: [ModelInfo], busy: Bool) {
        let obj = try checked(try await send(request("/api/chat/status")))
        let models = (obj["models"] as? [[String: Any]] ?? []).compactMap { m -> ModelInfo? in
            guard let n = m["name"] as? String else { return nil }
            return ModelInfo(name: n, label: m["label"] as? String ?? n, desc: m["desc"] as? String ?? "")
        }
        return (obj["ok"] as? Bool ?? false, models, obj["training"] as? Bool ?? false)
    }

    func chats() async throws -> [ChatSummary] {
        let (data, resp) = try await send(request("/api/chat/list"))
        if resp.statusCode == 401 { throw APIError.signedOut }
        if resp.statusCode >= 400 { throw APIError.server("Could not load your chats (\(resp.statusCode)).") }
        let list = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] ?? []
        return list.compactMap { c in
            guard let id = c["id"] as? String else { return nil }
            return ChatSummary(id: id, title: c["title"] as? String ?? "Chat", updated: Date(timeIntervalSince1970: c["updated"] as? Double ?? 0), count: c["n"] as? Int ?? 0, project: c["project"] as? String)
        }
    }

    func chat(_ id: String) async throws -> (title: String, model: String?, messages: [ChatMessage]) {
        let obj = try checked(try await send(request("/api/chat/get?id=\(id)")))
        var out: [ChatMessage] = []
        for m in obj["messages"] as? [[String: Any]] ?? [] {
            let role = m["role"] as? String ?? ""
            var msg = ChatMessage(role: role, content: m["content"] as? String ?? "", thinking: m["thinking"] as? String ?? "")
            if role == "tool" {
                msg.toolName = m["name"] as? String
                msg.attachment = API.attachment(m["card"] as? [String: Any])
            }
            if role == "user" {
                msg.images = m["images"] as? [String] ?? []
                msg.files = (m["files"] as? [Any] ?? []).compactMap { ($0 as? [String: Any])?["name"] as? String ?? $0 as? String }
            }
            if role == "assistant" && msg.content.isEmpty && msg.thinking.isEmpty { continue }   // a tool call without text
            out.append(msg)
        }
        return (obj["title"] as? String ?? "Chat", obj["model"] as? String, out)
    }

    static func attachment(_ card: [String: Any]?) -> ChatAttachment? {
        guard let card, let kind = card["kind"] as? String else { return nil }
        let files = (card["files"] as? [[String: Any]] ?? []).compactMap { f -> String? in
            guard f["image"] as? Bool == true, let n = f["name"] as? String else { return nil }
            let lower = n.lowercased()
            return [".png", ".jpg", ".jpeg", ".gif", ".webp"].contains(where: { lower.hasSuffix($0) }) ? n : nil
        }
        let all = (card["files"] as? [[String: Any]] ?? []).compactMap { $0["name"] as? String }
        return ChatAttachment(kind: kind, job: card["job"] as? String, runID: card["id"] as? String, files: files, allFiles: all,
                              musicID: kind == "music" ? card["id"] as? String : nil,
                              caption: card["caption"] as? String ?? "", lyrics: card["lyrics"] as? String ?? "", length: card["length"] as? String ?? "medium")
    }

    func newChat(model: String?, incognito: Bool = false, project: String? = nil) async throws -> String {
        var body: [String: Any] = ["incognito": incognito]
        if let model { body["model"] = model }
        if let project { body["project"] = project }
        let obj = try checked(try await send(request("/api/chat/new", method: "POST", json: body)))
        guard let id = obj["id"] as? String else { throw APIError.server("The server did not create a chat.") }
        return id
    }

    func delete(chat id: String) async throws {
        _ = try checked(try await send(request("/api/chat/item?id=\(id)", method: "DELETE")))
    }

    func rename(chat id: String, to title: String) async throws {
        _ = try checked(try await send(request("/api/chat/rename", method: "POST", json: ["id": id, "title": title])))
    }

    func stop(chat id: String) async {
        _ = try? await send(request("/api/chat/stop?id=\(id)", method: "POST", json: [String: Any]()))
    }

    /// Sends a message and streams the answer (server-sent events). `extra` carries model, think, tools, web, personal, image, files, regenerate.
    func stream(chat id: String, text: String, extra: [String: Any]) -> AsyncThrowingStream<StreamEvent, Error> {
        var body: [String: Any] = ["id": id, "content": text, "think": "low", "tools": true, "memory": true, "web": false]
        for (k, v) in extra { body[k] = v }
        return events(request("/api/chat/send", method: "POST", json: body, timeout: 600))
    }

    func stream(chat id: String, text: String, model: String?, think: String, tools: Bool = true) -> AsyncThrowingStream<StreamEvent, Error> {
        var extra: [String: Any] = ["think": think, "tools": tools]
        if let model { extra["model"] = model }
        return stream(chat: id, text: text, extra: extra)
    }

    private func events(_ req: URLRequest) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { cont in
            let task = Task {
                do {
                    let (bytes, resp) = try await session.bytes(for: req)
                    if let http = resp as? HTTPURLResponse, http.statusCode != 200 {
                        if http.statusCode == 401 { throw APIError.signedOut }
                        throw APIError.server("The server answered with error \(http.statusCode).")
                    }
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        guard let d = payload.data(using: .utf8), let ev = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] else { continue }
                        switch ev["type"] as? String {
                        case "thinking": cont.yield(.thinking(ev["text"] as? String ?? ""))
                        case "token": cont.yield(.token(ev["text"] as? String ?? ""))
                        case "tool_start": cont.yield(.toolStart(ev["name"] as? String ?? ""))
                        case "tool_result": cont.yield(.toolResult(ev["name"] as? String ?? "", ev["text"] as? String ?? "", API.attachment(ev["card"] as? [String: Any])))
                        case "error": cont.yield(.error(ev["message"] as? String ?? "Error"))
                        case "done": cont.yield(.done)
                        default: break
                        }
                    }
                    cont.finish()
                } catch let e as URLError {
                    cont.finish(throwing: APIError.network(API.describe(e, server: server)))
                } catch {
                    cont.finish(throwing: error)
                }
            }
            cont.onTermination = { _ in task.cancel() }
        }
    }

    /// Picture job state: (finished, result file, message).
    func imageJob(_ job: String) async throws -> (done: Bool, file: String?, message: String) {
        let obj = try checked(try await send(request("/api/img/job?id=\(job)")))
        let st = obj["status"] as? String ?? "error"
        let results = obj["results"] as? [String] ?? []
        if st == "running" || st == "queued" {
            let step = obj["step"] as? Int ?? 0, steps = obj["steps"] as? Int ?? 0
            return (false, nil, step > 0 ? "Step \(step) of \(steps)" : "Loading the picture model...")
        }
        if st == "done" { return (true, results.first, "Done") }
        let msg = obj["message"] as? String ?? st
        return (true, nil, msg == "unknown job" ? "This picture was interrupted by a server restart." : msg)
    }

    func data(_ path: String) async throws -> Data {
        let (data, resp) = try await send(request(path, timeout: 60))
        if resp.statusCode == 401 { throw APIError.signedOut }
        if resp.statusCode >= 400 { throw APIError.server("Could not load \(path) (\(resp.statusCode)).") }
        return data
    }

    func transcribe(_ audio: Data, ext: String) async throws -> String {
        let obj = try checked(try await send(request("/api/voice/transcribe?ext=\(ext)", method: "POST", body: audio, timeout: 300)))
        return obj["text"] as? String ?? ""
    }

    func speak(_ text: String, voice: String?) async throws -> Data {
        var body: [String: Any] = ["text": text]
        if let voice, !voice.isEmpty { body["voice"] = voice }
        let (data, resp) = try await send(request("/api/voice/speak", method: "POST", json: body, timeout: 180))
        if resp.statusCode == 401 { throw APIError.signedOut }
        if resp.statusCode >= 400 { throw APIError.server(json(data)["error"] as? String ?? "Reading aloud failed.") }
        return data
    }

    func voices() async throws -> [(id: String, label: String)] {
        let obj = try checked(try await send(request("/api/voice/voices")))
        return (obj["items"] as? [[String: Any]] ?? []).compactMap { v in
            guard let n = v["name"] as? String else { return nil }
            return (n, v["label"] as? String ?? n)
        }
    }

    // MARK: self-signed certificates (only when the user turned it on for this server)

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge) async -> (URLSession.AuthChallengeDisposition, URLCredential?) {
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
           server.trustCertificate, challenge.protectionSpace.host.lowercased() == server.host.lowercased(),
           let trust = challenge.protectionSpace.serverTrust {
            return (.useCredential, URLCredential(trust: trust))
        }
        return (.performDefaultHandling, nil)
    }
}
