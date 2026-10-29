import SwiftUI
import UniformTypeIdentifiers

/// Your documents, searchable by the chat models (per project when one is chosen).
struct LibraryView: View {
    @Environment(AppModel.self) private var app
    @State private var docs: [[String: Any]] = []
    @State private var query = ""
    @State private var hits: [[String: Any]] = []
    @State private var importing = false
    @State private var adding = false
    @State private var error: String?
    @State private var searching = false

    private var project: String? { app.activeProject.isEmpty ? nil : app.activeProject }

    var body: some View {
        if app.connection != .online { NotConnectedView() } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .firstTextBaseline) {
                        CardTitle("Library")
                        Text(app.projectName(project).map { "project: \($0)" } ?? "your own documents, searchable by the chat models").font(.caption).foregroundStyle(UP.muted)
                    }
                    Text("Add PDFs, Word files, notes, code or audio. They are split into passages and indexed on your Mac; in a chat, ask about them.")
                        .font(.footnote).foregroundStyle(UP.muted)
                    Button { importing = true } label: {
                        HStack { if adding { ProgressView() } else { Icon("plus", size: 18) }; Text("Add documents") }
                            .frame(maxWidth: .infinity).frame(height: 80)
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(style: StrokeStyle(lineWidth: 1.5, dash: [6])).foregroundStyle(UP.line))
                    }
                    .buttonStyle(.plain).foregroundStyle(UP.muted).disabled(adding)
                    HStack(spacing: 8) {
                        TextField("Search your documents (by meaning)", text: $query).upField().onSubmit { Task { await search() } }
                        Button { Task { await search() } } label: { if searching { ProgressView() } else { Text("Search") } }.buttonStyle(UPButton())
                    }
                    ForEach(hits.indices, id: \.self) { i in
                        let h = hits[i]
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(h.str("name") ?? "") · passage \(h.int("passage") ?? 0)").font(.caption.weight(.semibold)).foregroundStyle(UP.ink)
                            Text(h.str("text") ?? "").font(.footnote).foregroundStyle(UP.muted).lineLimit(6)
                        }
                        .padding(10).frame(maxWidth: .infinity, alignment: .leading).background(RoundedRectangle(cornerRadius: 10).fill(UP.bg))
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(UP.warn) }
                    if docs.isEmpty { Text("No documents yet.").font(.subheadline).foregroundStyle(UP.muted) }
                    ForEach(docs.indices, id: \.self) { i in
                        let d = docs[i]
                        HStack(spacing: 10) {
                            Icon("file", size: 18).foregroundStyle(UP.muted)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(d.str("name") ?? "").font(.system(size: 15)).foregroundStyle(UP.ink).lineLimit(1)
                                Text(detail(d)).font(.caption).foregroundStyle(d.str("status") == "error" ? UP.warn : UP.muted).lineLimit(2)
                            }
                            Spacer()
                            Button { Task { await remove(d) } } label: { Icon("x", size: 14) }
                                .buttonStyle(.plain).foregroundStyle(UP.muted).accessibilityLabel("Remove")
                        }
                        .padding(.vertical, 8)
                        .overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
                    }
                }
                .upCard()
                .padding(14)
            }
            .background(UP.bg)
            .task(id: app.activeProject) { await load() }
            .refreshable { await load() }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.item], allowsMultipleSelection: true) { r in Task { await add(r) } }
        }
    }

    private func detail(_ d: [String: Any]) -> String {
        let size = Double(d.int("size") ?? 0)
        let s = size > 1_048_576 ? String(format: "%.1f MB", size / 1_048_576) : "\(max(1, Int(size / 1024))) KB"
        let st = d.str("status") == "ready" ? "\(d.int("n") ?? 0) passages" : d.str("status") == "indexing" ? "Indexing…" : (d.str("error") ?? "Failed")
        return [s, d.str("note") ?? "", st].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func load() async {
        guard let api = app.api else { return }
        docs = (try? await api.get("/api/library?project=\(project ?? "")").dicts("items")) ?? docs
        if docs.contains(where: { $0.str("status") == "indexing" }) {
            try? await Task.sleep(for: .seconds(2))
            await load()
        }
    }

    private func add(_ r: Result<[URL], Error>) async {
        guard case .success(let urls) = r, let api = app.api else { return }
        adding = true
        defer { adding = false }
        for u in urls {
            let ok = u.startAccessingSecurityScopedResource()
            defer { if ok { u.stopAccessingSecurityScopedResource() } }
            guard let data = try? Data(contentsOf: u) else { continue }
            if data.count > 25 * 1024 * 1024 { error = "\(u.lastPathComponent) is larger than 25 MB."; continue }
            do { docs = try await api.addDocument(name: u.lastPathComponent, data: data, project: project) } catch { self.error = "\(u.lastPathComponent): \(error.localizedDescription)" }
        }
        await load()
    }

    private func remove(_ d: [String: Any]) async {
        guard let id = d.str("id") else { return }
        docs = (try? await app.api?.delete("/api/library?id=\(id)&project=\(project ?? "")").dicts("items")) ?? docs
    }

    private func search() async {
        guard let api = app.api, !query.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        searching = true
        defer { searching = false }
        var body: [String: Any] = ["query": query]
        if let project { body["project"] = project }
        do { hits = try await api.post("/api/library/search", body).dicts("hits") } catch { self.error = error.localizedDescription }
    }
}

/// The live log of what the models are doing.
struct ConsoleView: View {
    @Environment(AppModel.self) private var app
    @State private var lines: [[String: Any]] = []
    @State private var last = 0

    var body: some View {
        if app.connection != .online { NotConnectedView() } else {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 3) {
                        if lines.isEmpty { Text("Nothing logged yet. Activity of the models shows up here.").font(.footnote).foregroundStyle(UP.muted) }
                        ForEach(lines.indices, id: \.self) { i in
                            let l = lines[i]
                            HStack(alignment: .top, spacing: 8) {
                                Text(time(l.dbl("t") ?? 0)).foregroundStyle(UP.muted)
                                Text(l.str("src") ?? "").foregroundStyle(UP.brand).frame(width: 46, alignment: .leading)
                                Text(l.str("text") ?? "").foregroundStyle(UP.ink).textSelection(.enabled)
                            }
                            .font(.system(size: 11.5, design: .monospaced))
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .padding(12)
                }
                .background(UP.bg)
                .onChange(of: lines.count) { _, _ in proxy.scrollTo("end", anchor: .bottom) }
            }
            .task {
                while !Task.isCancelled {
                    if let r = try? await app.api?.get("/api/console?since=\(last)") {
                        let new = r.dicts("lines")
                        if !new.isEmpty { lines = Array((lines + new).suffix(1500)) }
                        last = r.int("last") ?? last
                    }
                    try? await Task.sleep(for: .seconds(1.5))
                }
            }
        }
    }

    private func time(_ t: Double) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: Date(timeIntervalSince1970: t))
    }
}
