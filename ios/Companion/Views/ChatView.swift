import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// The chat, as in the web app: messages, tool cards, and the composer at the bottom.
struct ChatView: View {
    @Environment(AppModel.self) private var app
    @State private var chatID: String?
    @State private var title = "New chat"
    @State private var messages: [ChatMessage] = []
    @State private var model: String?
    @State private var input = ""
    @State private var streaming = false
    @State private var streamTask: Task<Void, Never>?
    @State private var error: String?
    @State private var loading = false
    @State private var recorder = Recorder()
    @State private var transcribing = false
    @State private var image: (name: String, data: Data)?
    @State private var files: [(name: String, data: Data)] = []
    @State private var photoItem: PhotosPickerItem?
    @State private var showPhotos = false
    @State private var showFiles = false
    @State private var exportURL: URL?
    @State private var exporting = false
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            if app.connection != .online {
                NotConnectedView()
            } else {
                if app.busyWarning && app.warnHeavy {
                    Text("A heavy job (picture editing or training) is running on the Mac. Chat is slower until it finishes.")
                        .font(.footnote).foregroundStyle(UP.muted).padding(10).frame(maxWidth: .infinity)
                        .background(UP.panel).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
                }
                if messages.isEmpty && !loading {
                    Spacer()
                    emptyState.padding(.bottom, 22)
                    if let error { Text("Error: \(error)").font(.subheadline).foregroundStyle(UP.warn).padding(.horizontal, 16) }
                    composer
                    Spacer()
                } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 26) {
                            ForEach(Array(messages.enumerated()), id: \.element.id) { i, m in
                                MessageRow(message: m, streaming: streaming && i == messages.count - 1,
                                           isLastAnswer: !streaming && m.role == "assistant" && i == messages.lastIndex { $0.role == "assistant" },
                                           incognito: app.chatIncognito, regenerate: regenerate)
                            }
                            if let error {
                                Text("Error: \(error)").font(.subheadline).foregroundStyle(UP.warn)
                            }
                            Color.clear.frame(height: 1).id("bottom")
                        }
                        .padding(.horizontal, 16).padding(.vertical, 8)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .defaultScrollAnchor(.bottom)
                    .onChange(of: messages) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
                    .overlay { if loading { ProgressView() } }
                }
                composer
                }
            }
        }
        .background(UP.bg)
        .task { await load() }
        .onDisappear {
            Speaker.shared.stop(); recorder.cancel()
            if app.chatIncognito, let id = chatID { let api = app.api; Task { await api?.endIncognito(chat: id) } }
        }
        .onReceive(NotificationCenter.default.publisher(for: .modelPicked)) { n in model = n.object as? String }
        .photosPicker(isPresented: $showPhotos, selection: $photoItem, matching: .images)
        .onChange(of: photoItem) { _, item in Task { await takePhoto(item) } }
        .fileImporter(isPresented: $showFiles, allowedContentTypes: [.item], allowsMultipleSelection: true) { r in takeFiles(r) }
        .sheet(item: Binding(get: { exportURL.map { DownloadItem(url: $0) } }, set: { exportURL = $0?.url })) { ShareSheet(items: [$0.url]) }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Text(app.chatIncognito ? "Incognito chat" : "What can I help with?").font(.system(size: 24, weight: .semibold)).foregroundStyle(UP.ink)
            if app.chatIncognito {
                Text("Not saved, not remembered, gone when you leave it.").font(.subheadline).foregroundStyle(UP.muted)
            } else if let p = app.projectName(app.activeProject) {
                Text("In project \(p)").font(.subheadline).foregroundStyle(UP.muted)
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: composer

    private var composer: some View {
        VStack(spacing: 6) {
            VStack(alignment: .leading, spacing: 8) {
                if image != nil || !files.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            if let image, let ui = UIImage(data: image.data) {
                                chip(Image(uiImage: ui).resizable().scaledToFill().frame(width: 34, height: 34).clipShape(RoundedRectangle(cornerRadius: 7)), image.name) { self.image = nil }
                            }
                            ForEach(files.indices, id: \.self) { i in
                                chip(Icon("file", size: 18).frame(width: 34, height: 34), files[i].name) { files.remove(at: i) }
                            }
                        }
                    }
                }
                HStack(alignment: .bottom, spacing: 6) {
                    plusMenu
                    TextField("Ask anything", text: $input, axis: .vertical)
                        .lineLimit(1...7)
                        .font(.system(size: 16))
                        .foregroundStyle(UP.ink)
                        .focused($inputFocused)
                        .padding(.vertical, 8).padding(.horizontal, 4)
                        .submitLabel(app.enterSends ? .send : .return)
                        .onSubmit { if app.enterSends { send() } }
                        .accessibilityIdentifier("chat.input")
                    Button { Task { await toggleDictation() } } label: {
                        Group {
                            if transcribing { ProgressView() } else { Icon(recorder.recording ? "stop" : "mic", size: 20) }
                        }
                        .frame(width: 36, height: 36)
                        .foregroundStyle(recorder.recording ? .white : UP.ink)
                        .background(Circle().fill(recorder.recording ? Color.red : Color.clear))
                        .scaleEffect(recorder.recording ? 1 + CGFloat(recorder.level) * 0.2 : 1)
                    }
                    .disabled(transcribing || streaming)
                    .accessibilityLabel(recorder.recording ? "Stop dictation" : "Dictate")
                    Button { if streaming { stop() } else { send() } } label: {
                        Icon(streaming ? "stop" : "arrowup", size: 20).frame(width: 36, height: 36)
                            .foregroundStyle(UP.accentInk)
                            .background(Circle().fill(canSend || streaming ? UP.accent : UP.muted.opacity(0.5)))
                    }
                    .disabled(!canSend && !streaming)
                    .accessibilityLabel(streaming ? "Stop" : "Send").accessibilityIdentifier("chat.send")
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 28).fill(UP.composer))
            Text("Runs fully offline on your Mac. Answers can be wrong.").font(.system(size: 12)).foregroundStyle(UP.muted).padding(.top, 2)
        }
        .padding(.horizontal, 16).padding(.top, 4).padding(.bottom, 10)
        .background(UP.bg)
    }

    private func chip(_ icon: some View, _ name: String, remove: @escaping () -> Void) -> some View {
        HStack(spacing: 6) {
            icon.foregroundStyle(UP.muted)
            Text(name).font(.caption).lineLimit(1).frame(maxWidth: 120).foregroundStyle(UP.ink)
            Button(action: remove) { Icon("x", size: 12) }.foregroundStyle(UP.muted)
        }
        .padding(4).padding(.trailing, 6)
        .background(RoundedRectangle(cornerRadius: 10).fill(UP.bg))
    }

    private var plusMenu: some View {
        @Bindable var app = app
        return Menu {
            Button { showPhotos = true } label: { Label { Text("Add photos") } icon: { Image("i.image") } }
            Button { showFiles = true } label: { Label { Text("Add files") } icon: { Image("i.file") } }
            Divider()
            Toggle(isOn: $app.tools) { Label { Text("Tools (music and pictures)") } icon: { Image("i.settings") } }
            if let id = chatID, !messages.isEmpty, !app.chatIncognito {
                Menu {
                    Button("PDF") { Task { await export(id, "pdf") } }
                    Button("Word") { Task { await export(id, "docx") } }
                    Button("Markdown") { Task { await export(id, "md") } }
                } label: { Label { Text("Export this chat") } icon: { Image("i.download") } }
                if !app.projects.isEmpty {
                    Menu {
                        Button("No project") { Task { try? await app.api?.setProject(chat: id, project: nil); await app.loadChats() } }
                        ForEach(app.projects.indices, id: \.self) { i in
                            let p = app.projects[i]
                            Button(p.str("name") ?? "Project") { Task { try? await app.api?.setProject(chat: id, project: p.str("id")); await app.loadChats() } }
                        }
                    } label: { Label { Text("Move to project") } icon: { Image("i.folder") } }
                }
            }
        } label: {
            Group { if exporting { ProgressView() } else { Icon("plus", size: 20) } }.frame(width: 36, height: 36).foregroundStyle(UP.ink)
        }
        .accessibilityLabel("Add files and more")
    }

    private var canSend: Bool {
        (!input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || image != nil || !files.isEmpty) && app.connection == .online
    }

    // MARK: actions

    private func load() async {
        chatID = app.chatID
        guard let id = chatID, let api = app.api else { return }
        loading = true
        defer { loading = false }
        do {
            let c = try await api.chat(id)
            title = c.title
            model = c.model
            app.chatModel = c.model
            messages = c.messages
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func takePhoto(_ item: PhotosPickerItem?) async {
        guard let item, let data = try? await item.loadTransferable(type: Data.self), let ui = UIImage(data: data) else { return }
        let jpeg = ui.jpegData(compressionQuality: 0.9) ?? data   // HEIC from the camera roll becomes JPEG
        image = ("photo.jpg", jpeg)
        photoItem = nil
    }

    private func takeFiles(_ r: Result<[URL], Error>) {
        guard case .success(let urls) = r else { return }
        for u in urls.prefix(10) {
            let ok = u.startAccessingSecurityScopedResource()
            defer { if ok { u.stopAccessingSecurityScopedResource() } }
            guard let d = try? Data(contentsOf: u), d.count <= 25 * 1024 * 1024 else { error = "\(u.lastPathComponent) is larger than 25 MB."; continue }
            if let t = UTType(filenameExtension: u.pathExtension), t.conforms(to: .image), image == nil, let ui = UIImage(data: d) {
                image = (u.lastPathComponent, ui.jpegData(compressionQuality: 0.9) ?? d)
            } else {
                files.append((u.lastPathComponent, d))
            }
        }
    }

    private func requestBody(regenerate: Bool = false) -> [String: Any] {
        var b: [String: Any] = ["think": app.think, "tools": app.tools, "web": app.web, "memory": app.memoryOn, "personal": app.personal]
        if let m = model ?? app.model { b["model"] = m }
        if regenerate { b["regenerate"] = true }
        if let image { b["image"] = "data:image/jpeg;base64," + image.data.base64EncodedString() }
        if !files.isEmpty { b["files"] = files.map { ["name": $0.name, "data": $0.data.base64EncodedString()] } }
        return b
    }

    private func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canSend, let api = app.api else { return }
        let extra = requestBody()
        var shown = ChatMessage(role: "user", content: text.isEmpty && image != nil ? "(picture attached)" : text)
        if let image { shown.localImage = image.data }
        shown.fileNames = files.map(\.name)
        input = ""; image = nil; files = []
        run(api, text: text, extra: extra, show: shown)
    }

    private func regenerate() {
        guard let api = app.api, chatID != nil, !streaming else { return }
        while let last = messages.last, last.role != "user" { messages.removeLast() }
        run(api, text: "", extra: requestBody(regenerate: true), show: nil)
    }

    private func run(_ api: API, text: String, extra: [String: Any], show: ChatMessage?) {
        error = nil
        Speaker.shared.stop()
        streaming = true
        let useModel = model ?? app.model
        streamTask = Task {
            do {
                let id: String
                if let existing = chatID { id = existing } else {
                    id = try await api.newChat(model: useModel, incognito: app.chatIncognito, project: app.activeProject.isEmpty ? nil : app.activeProject)
                    chatID = id
                    app.chatID = id
                    model = useModel
                }
                if let show { messages.append(show) }
                messages.append(ChatMessage(role: "assistant", content: ""))
                for try await ev in api.stream(chat: id, text: text, extra: extra) { apply(ev) }
            } catch is CancellationError {
            } catch {
                self.error = error.localizedDescription
                if case APIError.signedOut = error { await app.refresh() }
            }
            streaming = false
            streamTask = nil
            await finish()
        }
    }

    private func apply(_ ev: StreamEvent) {
        guard !messages.isEmpty else { return }
        let last = messages.count - 1
        switch ev {
        case .thinking(let t):
            if messages[last].role == "assistant" { messages[last].thinking += t }
        case .token(let t):
            if messages[last].role == "assistant" { messages[last].content += t } else { messages.append(ChatMessage(role: "assistant", content: t)) }
        case .toolStart(let name):
            if messages[last].role == "assistant" && messages[last].content.isEmpty && messages[last].thinking.isEmpty { messages.removeLast() }
            messages.append(ChatMessage(role: "tool", content: "", toolName: name))
        case .toolResult(let name, let text, let card):
            if let i = messages.lastIndex(where: { $0.role == "tool" && $0.toolName == name && $0.content.isEmpty && $0.attachment == nil }) {
                messages[i].content = text
                messages[i].attachment = card
            } else {
                messages.append(ChatMessage(role: "tool", content: text, toolName: name, attachment: card))
            }
            messages.append(ChatMessage(role: "assistant", content: ""))
        case .error(let m):
            error = m
        case .done:
            break
        }
    }

    private func stop() {
        guard let id = chatID else { streamTask?.cancel(); return }
        Task { await app.api?.stop(chat: id) }
    }

    /// After an answer: reload what the server saved, read it aloud if wanted, pick up the chat's new title.
    private func finish() async {
        if let last = messages.last, last.role == "assistant", last.content.isEmpty, last.thinking.isEmpty { messages.removeLast() }
        guard let id = chatID, let api = app.api else { return }
        await app.loadChats()
        if let c = try? await api.chat(id) { messages = c.messages; title = c.title }
        if app.autoRead, error == nil, let m = messages.last(where: { $0.role == "assistant" }), !m.content.isEmpty {
            await MessageRow.readAloud(m, app: app)
        }
        try? await Task.sleep(for: .seconds(8))
        await app.loadChats()
    }

    private func export(_ id: String, _ format: String) async {
        guard let api = app.api else { return }
        exporting = true
        defer { exporting = false }
        do { exportURL = try await api.export(chat: id, title: title, format: format) } catch { self.error = error.localizedDescription }
    }

    private func toggleDictation() async {
        if recorder.recording {
            guard let audio = recorder.stop(), let api = app.api else { return }
            transcribing = true
            defer { transcribing = false }
            do {
                let text = try await api.transcribe(audio, ext: "m4a").trimmingCharacters(in: .whitespacesAndNewlines)
                if !text.isEmpty { input = input.isEmpty ? text : input + " " + text }
            } catch {
                self.error = error.localizedDescription
            }
        } else if !(await recorder.start()) {
            error = "Microphone access is off. Turn it on in Settings, unplugged.ai."
        }
    }
}

struct DownloadItem: Identifiable { let url: URL; var id: URL { url } }

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

/// Shown while no server is usable.
struct NotConnectedView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        VStack(spacing: 14) {
            switch app.connection {
            case .checking:
                ProgressView()
                Text("Connecting to \(app.server?.name ?? "your Mac")...").foregroundStyle(UP.muted)
            case .offline(let msg):
                Icon("x", size: 36).foregroundStyle(UP.muted)
                Text("Can't reach \(app.server?.name ?? "the server")").font(.headline).foregroundStyle(UP.ink)
                Text(msg).font(.subheadline).foregroundStyle(UP.muted).multilineTextAlignment(.center).padding(.horizontal, 30)
                Button("Try again") { Task { await app.refresh() } }.buttonStyle(UPButton(primary: true))
                Button("Choose another server") { app.openSettings(.servers) }.buttonStyle(UPButton())
            case .signedOut:
                Icon("settings", size: 36).foregroundStyle(UP.muted)
                Text("Sign in to \(app.server?.name ?? "your server")").font(.headline).foregroundStyle(UP.ink)
                Button("Sign in") { app.needsSignIn = app.server }.buttonStyle(UPButton(primary: true))
            default:
                Image("Logo").resizable().frame(width: 56, height: 56).clipShape(RoundedRectangle(cornerRadius: 14))
                Text("Connect to your Mac").font(.system(size: 24, weight: .bold)).foregroundStyle(UP.ink)
                Text("Find unplugged.ai nearby or on your network, or add the address of a remote server.")
                    .font(.subheadline).foregroundStyle(UP.muted).multilineTextAlignment(.center).padding(.horizontal, 30)
                Button("Find a server") { app.openSettings(.servers) }.buttonStyle(UPButton(primary: true)).accessibilityIdentifier("connect.find")
                Button("How to set up unplugged.ai") { app.openSettings(.help) }.buttonStyle(UPButton())
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(UP.bg)
    }
}
