import AVFoundation
import Combine
import SwiftUI
import UIKit

struct MessageRow: View {
    @Environment(AppModel.self) private var app
    let message: ChatMessage
    let streaming: Bool
    var isLastAnswer = false
    var incognito = false
    var regenerate: () -> Void = {}
    @State private var showThinking = false
    @State private var copied = false

    var body: some View {
        switch message.role {
        case "user":
            HStack {
                Spacer(minLength: 60)
                VStack(alignment: .trailing, spacing: 6) {
                    if let d = message.localImage, let ui = UIImage(data: d) {
                        Image(uiImage: ui).resizable().scaledToFit().frame(maxWidth: 220, maxHeight: 220).clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    ForEach(message.images, id: \.self) { name in
                        RemoteImage(path: "/img/\(name)").frame(maxWidth: 220, maxHeight: 220).clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    ForEach(message.files + message.fileNames, id: \.self) { f in
                        Label { Text(f) } icon: { Icon("file", size: 14) }.font(.caption).foregroundStyle(UP.muted)
                            .padding(.horizontal, 10).padding(.vertical, 6).background(RoundedRectangle(cornerRadius: 10).stroke(UP.line))
                    }
                    if !message.content.isEmpty && message.content != "(picture attached)" {
                        Text(message.content)
                            .font(.system(size: 16))
                            .foregroundStyle(UP.ink)
                            .textSelection(.enabled)
                            .padding(.horizontal, 18).padding(.vertical, 10)
                            .background(RoundedRectangle(cornerRadius: 22).fill(UP.bubble))
                    }
                }
            }
        case "tool":
            ToolCard(message: message, incognito: incognito)
        default:
            VStack(alignment: .leading, spacing: 8) {
                if !message.thinking.isEmpty {
                    Button { withAnimation { showThinking.toggle() } } label: {
                        HStack(spacing: 6) {
                            Icon("chevron", size: 12).rotationEffect(.degrees(showThinking ? 0 : -90))
                            Text(streaming && message.content.isEmpty ? "Thinking…" : "Thought process").font(.system(size: 13))
                        }
                        .foregroundStyle(UP.muted)
                    }
                    .buttonStyle(.plain)
                    if showThinking {
                        Text(message.thinking).font(.system(size: 13)).foregroundStyle(UP.muted).textSelection(.enabled)
                            .padding(.leading, 10).overlay(alignment: .leading) { Rectangle().fill(UP.line).frame(width: 2) }
                    }
                }
                if message.content.isEmpty && message.thinking.isEmpty && streaming {
                    ProgressView().padding(.vertical, 4)
                } else if !message.content.isEmpty {
                    MarkdownText(message.content)
                }
                if !streaming && !message.content.isEmpty {
                    HStack(spacing: 2) {
                        act(copied ? "check" : "copy", "Copy") {
                            UIPasteboard.general.string = message.content
                            copied = true
                            Task { try? await Task.sleep(for: .seconds(1.2)); copied = false }
                        }
                        act(Speaker.shared.playingID == message.id ? "stop" : "speaker", "Read aloud", loading: Speaker.shared.loadingID == message.id) {
                            Task { await MessageRow.readAloud(message, app: app) }
                        }
                        if isLastAnswer { act("refresh", "Regenerate", action: regenerate) }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func act(_ icon: String, _ label: String, loading: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Group { if loading { Spinner(size: 13) } else { Icon(icon, size: 16) } }
                .frame(width: 30, height: 30)
        }
        .buttonStyle(.plain).foregroundStyle(UP.muted).accessibilityLabel(label)
    }

    /// Reads a message aloud with the voice chosen in Settings (made on the Mac). Pressing again stops it.
    @MainActor static func readAloud(_ m: ChatMessage, app: AppModel) async {
        let sp = Speaker.shared
        if sp.playingID == m.id { sp.stop(); return }
        guard let api = app.api else { return }
        sp.loadingID = m.id
        defer { if sp.loadingID == m.id { sp.loadingID = nil } }
        if let data = try? await api.speak(m.content, voice: app.voice) { sp.play(data, id: m.id) }
    }
}

/// Markdown for chat answers: paragraphs with inline formatting, headings, lists, quotes and code blocks.
struct MarkdownText: View {
    let text: String
    init(_ text: String) { self.text = text }

    enum Block: Hashable { case text(String), code(String, String), heading(String, Int), rule }

    var blocks: [Block] {
        var out: [Block] = []
        var buf: [String] = []
        var code: [String]? = nil
        var lang = ""
        func flush() {
            let t = buf.joined(separator: "\n").trimmingCharacters(in: .newlines)
            if !t.isEmpty { out.append(.text(t)) }
            buf = []
        }
        for line in text.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("```") {
                if let c = code { out.append(.code(lang, c.joined(separator: "\n"))); code = nil } else { flush(); lang = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces); code = [] }
                continue
            }
            if code != nil { code?.append(line); continue }
            if let m = trimmed.firstMatch(of: #/^(#{1,6})\s+(.+)$/#) { flush(); out.append(.heading(String(m.2), m.1.count)); continue }
            if trimmed.firstMatch(of: #/^([-*_])\1{2,}$/#) != nil { flush(); out.append(.rule); continue }
            if trimmed.isEmpty { flush(); continue }
            buf.append(line)
        }
        if let c = code { out.append(.code(lang, c.joined(separator: "\n"))) }
        flush()
        return out
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, b in
                switch b {
                case .text(let t):
                    Text(MarkdownText.inline(t)).font(.system(size: 16)).foregroundStyle(UP.ink).textSelection(.enabled).fixedSize(horizontal: false, vertical: true).lineSpacing(7)
                case .heading(let t, _):
                    Text(MarkdownText.inline(t)).font(.system(size: 16, weight: .semibold)).foregroundStyle(UP.ink).padding(.top, 6)
                case .code(let lang, let c):
                    CodeBlock(lang: lang, code: c)
                case .rule:
                    Rectangle().fill(UP.line).frame(height: 1)
                }
            }
        }
    }

    static func inline(_ s: String) -> AttributedString {
        let lines = s.components(separatedBy: "\n").map { line -> String in
            if let m = line.firstMatch(of: #/^(\s*)[-*+]\s+(.*)$/#) { return "\(m.1)•  \(m.2)" }
            if let m = line.firstMatch(of: #/^\s*>\s?(.*)$/#) { return "│ \(m.1)" }
            return line
        }.joined(separator: "\n")
        let opts = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace, failurePolicy: .returnPartiallyParsedIfPossible)
        var out = (try? AttributedString(markdown: lines, options: opts)) ?? AttributedString(lines)
        for run in out.runs where run.inlinePresentationIntent?.contains(.code) == true {
            out[run.range].font = .system(.subheadline, design: .monospaced)
            out[run.range].backgroundColor = UP.card
        }
        return out
    }
}

struct CodeBlock: View {
    let lang: String
    let code: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(lang.isEmpty ? "text" : lang).font(.system(size: 12.5, design: .monospaced)).foregroundStyle(Color(white: 0.64))
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    copied = true
                    Task { try? await Task.sleep(for: .seconds(1.5)); copied = false }
                } label: { HStack(spacing: 6) { Icon(copied ? "check" : "copy", size: 14); Text(copied ? "Copied" : "Copy") }.font(.system(size: 12.5)) }
                    .buttonStyle(.plain).foregroundStyle(Color(white: 0.64))
            }
            .padding(.leading, 14).padding(.trailing, 8).padding(.vertical, 6)
            .background(Color.white.opacity(0.06))
            ScrollView(.horizontal, showsIndicators: false) {
                Text(Highlighter.highlight(code, lang: lang)).font(.system(size: 13, design: .monospaced)).textSelection(.enabled).padding(14)
            }
        }
        .background(Color(red: 0.05, green: 0.05, blue: 0.05))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

/// Simple syntax colouring (keywords, strings, comments, numbers), like the web app's hl.js.
enum Highlighter {
    static let keywords: Set<String> = ["func", "let", "var", "if", "else", "for", "while", "return", "import", "from", "def", "class", "struct", "enum",
        "const", "function", "async", "await", "try", "catch", "throw", "in", "of", "new", "true", "false", "nil", "null", "None", "True", "False",
        "self", "this", "public", "private", "static", "switch", "case", "break", "continue", "with", "as", "lambda", "yield", "pass", "elif", "export", "default", "interface", "type"]

    static func highlight(_ code: String, lang: String) -> AttributedString {
        var out = AttributedString(code)
        out.foregroundColor = Color(white: 0.925)
        let ns = code as NSString
        func hex(_ h: UInt32) -> Color { Color(UIColor(hex: h)) }
        func paint(_ pattern: String, _ color: Color, italic: Bool = false) {
            guard let re = try? NSRegularExpression(pattern: pattern, options: [.anchorsMatchLines]) else { return }
            for m in re.matches(in: code, range: NSRange(location: 0, length: ns.length)) {
                guard let r = Range(m.range, in: code), let ar = Range(r, in: out) else { continue }
                out[ar].foregroundColor = color
                if italic { out[ar].font = .system(size: 13, design: .monospaced).italic() }
            }
        }
        // colours of the web app's hl.js theme (app.css .tk-*)
        paint("\\b[A-Za-z_][A-Za-z0-9_]*(?=\\()", hex(0x82AAFF))
        paint("\\b\\d+(\\.\\d+)?\\b", hex(0xF2A86B))
        paint("\\b(" + keywords.joined(separator: "|") + ")\\b", hex(0xC792EA))
        paint("</?[A-Za-z][A-Za-z0-9-]*|/?>", hex(0xF07178))
        paint("\"(\\\\.|[^\"\\\\])*\"|'(\\\\.|[^'\\\\])*'|`[^`]*`", hex(0xA5D6A7))
        paint(lang.lowercased().hasPrefix("py") || ["bash", "sh", "zsh", "yaml", "toml", "shell"].contains(lang.lowercased()) ? "#.*$" : "//.*$|/\\*[\\s\\S]*?\\*/", hex(0x7F8C98), italic: true)
        return out
    }
}

/// A tool step in the chat, as in the web app: a panel with a status dot, and the picture, song or files it made.
struct ToolCard: View {
    @Environment(AppModel.self) private var app
    let message: ChatMessage
    var incognito = false
    @State private var jobText = ""
    @State private var jobFile: String?
    @State private var caption = ""
    @State private var lyrics = ""
    @State private var length = "medium"
    @State private var musicJob: String?
    @State private var musicText = ""
    @State private var song: String?
    @State private var shareURL: URL?

    static let labels = ["generate_music": "Making music", "edit_picture": "Editing picture", "generate_image": "Creating a picture",
                         "list_music": "Looking up your music", "look_at_picture": "Looking at the picture", "ask_about_picture": "Looking closer at the picture",
                         "search_documents": "Searching your documents", "remember": "Remembering", "forget": "Forgetting",
                         "search_past_chats": "Searching earlier chats", "run_python": "Running code", "create_document": "Creating a file",
                         "web_search": "Searching the web", "fetch_page": "Reading a web page"]

    private var running: Bool { message.content.isEmpty && message.attachment == nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if running { Spinner(size: 10) } else { Circle().fill(UP.ok).frame(width: 10, height: 10) }
                Text((ToolCard.labels[message.toolName ?? ""] ?? (message.toolName ?? "Tool")) + (running ? "…" : "")).font(.system(size: 13, weight: .semibold)).foregroundStyle(UP.ink)
            }
            content
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: 520, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(UP.card))
        .task(id: message.attachment?.job) { await followImage() }
        .onAppear {
            if let a = message.attachment, a.kind == "music_draft", caption.isEmpty { caption = a.caption; lyrics = a.lyrics; length = a.length }
            if let a = message.attachment, a.kind == "music", let id = a.musicID { song = id }
        }
        .sheet(item: Binding(get: { shareURL.map { DownloadItem(url: $0) } }, set: { shareURL = $0?.url })) { ShareSheet(items: [$0.url]) }
    }

    @ViewBuilder private var content: some View {
        if let a = message.attachment {
            switch a.kind {
            case "image_job":
                if let f = jobFile {
                    RemoteImage(path: "/img/\(f)").frame(maxWidth: .infinity).clipShape(RoundedRectangle(cornerRadius: 10))
                } else {
                    Text(jobText.isEmpty ? "Starting the picture model..." : jobText).font(.footnote).foregroundStyle(UP.muted)
                }
            case "run":
                ForEach(a.files, id: \.self) { f in
                    RemoteImage(path: runPath(a, f)).frame(maxWidth: .infinity).clipShape(RoundedRectangle(cornerRadius: 10))
                }
                if !summary.isEmpty { Text(summary).font(.system(size: 12.5, design: .monospaced)).foregroundStyle(UP.muted).lineLimit(10) }
                ForEach(a.allFiles, id: \.self) { f in
                    Button { Task { shareURL = try? await app.api?.download(runPath(a, f) + "&download=1", name: f) } } label: {
                        HStack(spacing: 6) { Icon("download", size: 14); Text(f) }.font(.system(size: 12))
                    }
                    .buttonStyle(UPButton())
                }
            case "music_draft":
                musicDraft
            case "music":
                if let id = a.musicID { SongPlayer(id: id) }
            case "music_job":
                Text("Open Music to follow this song.").font(.footnote).foregroundStyle(UP.muted)
            default:
                if !summary.isEmpty { Text(summary).font(.footnote).foregroundStyle(UP.muted).lineLimit(6) }
            }
        } else if !message.content.isEmpty {
            Text(summary).font(.footnote).foregroundStyle(UP.muted).lineLimit(6)
        }
    }

    private func runPath(_ a: ChatAttachment, _ f: String) -> String {
        "/api/run/file?run=\(a.runID ?? "")&name=\(f.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? f)"
    }

    private var summary: String { String(message.content.prefix(700)) }

    /// The editable caption and lyrics the model wrote; nothing is made until Generate song.
    @ViewBuilder private var musicDraft: some View {
        if let s = song {
            SongPlayer(id: s)
        } else if let job = musicJob {
            VStack(alignment: .leading, spacing: 8) {
                ProgressView(value: nil as Double?).progressViewStyle(.linear)
                Text(musicText.isEmpty ? "Starting the music model..." : musicText).font(.footnote).foregroundStyle(UP.muted)
                Button("Stop generating") { Task { _ = try? await app.api?.post("/api/music/cancel?id=\(job)") } }.buttonStyle(UPButton())
            }
            .task(id: job) { await followSong(job) }
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Text("Caption (the sound)").font(.caption).foregroundStyle(UP.muted)
                TextEditor(text: $caption).frame(minHeight: 80).scrollContentBackground(.hidden).upField()
                Text("Lyrics (empty for instrumental)").font(.caption).foregroundStyle(UP.muted)
                TextEditor(text: $lyrics).frame(minHeight: 140).scrollContentBackground(.hidden).upField()
                GlassSelect(options: MusicView.lengths, selection: $length)
                Button("Generate song") { Task { await makeSong() } }.buttonStyle(UPButton(primary: true))
                    .disabled(caption.trimmingCharacters(in: .whitespaces).isEmpty)
                Text("Review or edit, then press Generate song. Nothing is made until you do.").font(.caption).foregroundStyle(UP.muted)
                if !musicText.isEmpty { Text(musicText).font(.footnote).foregroundStyle(UP.warn) }
            }
        }
    }

    private func makeSong() async {
        guard let api = app.api else { return }
        do {
            let r = try await api.post("/api/music/make", ["caption": caption, "lyrics": lyrics, "length": length, "incognito": incognito])
            musicJob = r.str("job")
        } catch { musicText = error.localizedDescription }
    }

    private func followSong(_ job: String) async {
        guard let api = app.api else { return }
        while !Task.isCancelled {
            guard let j = try? await api.get("/api/job?id=\(job)") else { musicText = "Lost track of this song."; return }
            let st = j.str("status") ?? ""
            if st == "running" || st == "queued" { musicText = j.str("message") ?? "Composing..."; try? await Task.sleep(for: .seconds(2)); continue }
            if st == "done", let r = (j["results"] as? [String])?.first { song = r; musicJob = nil; return }
            musicJob = nil
            musicText = st == "cancelled" ? "Stopped. No song was made." : (j.str("message") ?? "No song came out.")
            return
        }
    }

    private func followImage() async {
        guard let a = message.attachment, a.kind == "image_job", let job = a.job, let api = app.api else { return }
        while !Task.isCancelled {
            guard let st = try? await api.imageJob(job) else { jobText = "Lost track of this picture."; return }
            if st.done { if let f = st.file { jobFile = f } else { jobText = st.message }; return }
            jobText = st.message
            try? await Task.sleep(for: .seconds(2))
        }
    }
}

/// Plays one song from the server (downloaded once, then played on the phone), with a share button.
struct SongPlayer: View {
    @Environment(AppModel.self) private var app
    let id: String
    var caption: String?
    @State private var player: AVAudioPlayer?
    @State private var loading = false
    @State private var playing = false
    @State private var progress: Double = 0
    @State private var fileURL: URL?
    @State private var share: URL?
    @State private var error: String?
    private let tick = Timer.publish(every: 0.25, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let caption, !caption.isEmpty { Text(caption).font(.footnote).foregroundStyle(UP.muted).lineLimit(2) }
            HStack(spacing: 12) {
                Button { Task { await toggle() } } label: {
                    Group { if loading { ProgressView() } else { Icon(playing ? "pause" : "play", size: 18) } }
                        .frame(width: 40, height: 40).foregroundStyle(UP.accentInk).background(Circle().fill(UP.accent))
                }
                .buttonStyle(.plain)
                Slider(value: Binding(get: { progress }, set: { v in progress = v; if let p = player { p.currentTime = v * p.duration } }), in: 0...1)
                    .disabled(player == nil)
                Text(timeText).font(.caption.monospacedDigit()).foregroundStyle(UP.muted)
                Button { Task { if fileURL == nil { await fetch() }; share = fileURL } } label: { Icon("download", size: 18) }
                    .buttonStyle(.plain).foregroundStyle(UP.muted).accessibilityLabel("Share song")
            }
            if let error { Text(error).font(.caption).foregroundStyle(UP.warn) }
        }
        .onReceive(tick) { _ in
            guard let p = player else { return }
            playing = p.isPlaying
            if p.duration > 0 { progress = p.currentTime / p.duration }
        }
        .onDisappear { player?.stop() }
        .sheet(item: Binding(get: { share.map { DownloadItem(url: $0) } }, set: { share = $0?.url })) { ShareSheet(items: [$0.url]) }
    }

    private var timeText: String {
        guard let p = player else { return "--:--" }
        let t = Int(p.isPlaying || progress > 0 ? p.currentTime : p.duration)
        return String(format: "%d:%02d", t / 60, t % 60)
    }

    private func fetch() async {
        guard let api = app.api else { return }
        loading = true
        defer { loading = false }
        do {
            let name = (id.split(separator: "/").last.map(String.init) ?? "song") + ".wav"
            fileURL = try await api.download("/audio?id=\(id.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? id)", name: name)
        } catch { self.error = error.localizedDescription }
    }

    private func toggle() async {
        if let p = player {
            if p.isPlaying { p.pause() } else { p.play() }
            playing = p.isPlaying
            return
        }
        if fileURL == nil { await fetch() }
        guard let u = fileURL else { return }
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback)
            try AVAudioSession.sharedInstance().setActive(true)
            let p = try AVAudioPlayer(contentsOf: u)
            p.play()
            player = p
            playing = true
        } catch { self.error = "This song could not be played." }
    }
}

/// An image from the server, loaded with this server's session; long-press to share or save.
struct RemoteImage: View {
    @Environment(AppModel.self) private var app
    let path: String
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().scaledToFit()
                    .contextMenu {
                        ShareLink(item: Image(uiImage: image), preview: SharePreview("Picture", image: Image(uiImage: image)))
                        Button { UIImageWriteToSavedPhotosAlbum(image, nil, nil, nil) } label: { Label { Text("Save to Photos") } icon: { Image("i.download") } }
                    }
            } else if failed {
                Label { Text("Picture not available") } icon: { Image("i.image") }.font(.footnote).foregroundStyle(UP.muted).padding()
            } else {
                ProgressView().frame(height: 120).frame(maxWidth: .infinity)
            }
        }
        .task(id: path) {
            guard let api = app.api else { failed = true; return }
            if let d = try? await api.data(path), let img = UIImage(data: d) { image = img } else { failed = true }
        }
    }
}
