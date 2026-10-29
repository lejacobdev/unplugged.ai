import Foundation

/// The rest of the server's API (music, pictures, library, console, settings panes), as plain dictionaries.
extension API {
    func get(_ path: String, timeout: TimeInterval = 30) async throws -> [String: Any] {
        try checked(try await send(request(path, timeout: timeout)))
    }

    func getList(_ path: String) async throws -> [[String: Any]] {
        let (data, resp) = try await send(request(path))
        if resp.statusCode == 401 { throw APIError.signedOut }
        if resp.statusCode >= 400 { throw APIError.server(json(data)["error"] as? String ?? "Error \(resp.statusCode)") }
        return (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] ?? []
    }

    @discardableResult
    func post(_ path: String, _ body: [String: Any] = [:], timeout: TimeInterval = 120) async throws -> [String: Any] {
        try checked(try await send(request(path, method: "POST", json: body, timeout: timeout)))
    }

    @discardableResult
    func delete(_ path: String) async throws -> [String: Any] {
        try checked(try await send(request(path, method: "DELETE")))
    }

    func setProject(chat id: String, project: String?) async throws {
        try await post("/api/chat/project", ["id": id, "project": project ?? ""])
    }

    func endIncognito(chat id: String) async {
        _ = try? await post("/api/chat/end-incognito", ["id": id])
    }

    /// A chat as a file (pdf, docx, md), saved in the temporary folder for sharing.
    func export(chat id: String, title: String, format: String) async throws -> URL {
        let data = try await data("/api/chat/export?id=\(id)&format=\(format)")
        let safe = title.replacingOccurrences(of: "/", with: "-").prefix(60)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(safe.isEmpty ? "chat" : String(safe)).\(format)")
        try data.write(to: url)
        return url
    }

    /// Any file from the server, saved for sharing.
    func download(_ path: String, name: String) async throws -> URL {
        let data = try await data(path)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        try data.write(to: url)
        return url
    }

    /// Downloads a model with Ollama on the server, reporting progress.
    func pull(model: String) -> AsyncThrowingStream<(status: String, fraction: Double?), Error> {
        let req = request("/api/models/pull", method: "POST", json: ["name": model], timeout: 3600)
        return AsyncThrowingStream { cont in
            let task = Task {
                do {
                    let (bytes, resp) = try await session.bytes(for: req)
                    if let http = resp as? HTTPURLResponse, http.statusCode != 200 {
                        var data = Data()
                        for try await b in bytes { data.append(b) }
                        throw APIError.server(json(data)["error"] as? String ?? "Download failed (\(http.statusCode)).")
                    }
                    for try await line in bytes.lines where line.hasPrefix("data:") {
                        guard let d = line.dropFirst(5).trimmingCharacters(in: .whitespaces).data(using: .utf8),
                              let ev = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] else { continue }
                        if let e = ev.str("error") { throw APIError.server(e) }
                        let total = ev.dbl("total") ?? 0, done = ev.dbl("completed") ?? 0
                        cont.yield((ev.str("status") ?? "", total > 0 ? done / total : nil))
                    }
                    cont.finish()
                } catch {
                    cont.finish(throwing: error)
                }
            }
            cont.onTermination = { _ in task.cancel() }
        }
    }

    func addDocument(name: String, data: Data, project: String?) async throws -> [[String: Any]] {
        var body: [String: Any] = ["name": name, "data": data.base64EncodedString()]
        if let project { body["project"] = project }
        return try await post("/api/library", body, timeout: 300).dicts("items")
    }
}
