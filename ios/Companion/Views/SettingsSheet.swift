import SwiftUI

/// The settings overlay of the web app (General, Personalization, Memory, Projects, Tasks, Models, API), plus Servers and Help.
struct SettingsSheet: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var app = app
        NavigationStack {
            VStack(spacing: 0) {
                HStack {
                    Text("SETTINGS").font(.system(size: 17, weight: .semibold)).tracking(1.2).foregroundStyle(UP.ink)
                    Spacer()
                    Button { dismiss() } label: { Icon("x", size: 18).frame(width: 36, height: 36) }
                        .buttonStyle(.glass).accessibilityLabel("Close").accessibilityIdentifier("settings.close")
                }
                .padding(.horizontal, 18).padding(.top, 16).padding(.bottom, 10)
                ScrollViewReader { proxy in
                    ScrollView(.horizontal, showsIndicators: false) {
                        GlassEffectContainer {
                            HStack(spacing: 6) {
                                ForEach(SettingsPane.allCases) { p in
                                    Button { withAnimation(.snappy) { app.settingsPane = p } } label: {
                                        Text(p.title).font(.system(size: 14, weight: app.settingsPane == p ? .semibold : .regular))
                                            .foregroundStyle(app.settingsPane == p ? UP.ink : UP.muted)
                                            .padding(.horizontal, 14).padding(.vertical, 8)
                                    }
                                    .buttonStyle(.plain)
                                    .glassEffect(app.settingsPane == p ? .regular.interactive() : .identity, in: Capsule())
                                    .id(p)
                                    .accessibilityIdentifier("pane.\(p.rawValue)")
                                }
                            }
                            .padding(.horizontal, 14).padding(.vertical, 4)
                        }
                    }
                    .onAppear { proxy.scrollTo(app.settingsPane, anchor: .center) }
                }
                Rectangle().fill(UP.line).frame(height: 1).padding(.top, 6)
                ScrollView {
                    Group {
                        switch app.settingsPane {
                        case .general: GeneralPane()
                        case .personal: PersonalPane()
                        case .memory: MemoryPane()
                        case .projects: ProjectsPane()
                        case .tasks: TasksPane()
                        case .models: ModelsPane()
                        case .api: APIPane()
                        case .servers: ServersPane()
                        case .help: HelpPane()
                        }
                    }
                    .padding(.horizontal, 18).padding(.bottom, 30)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .background(UP.panel)
            .toolbar(.hidden, for: .navigationBar)
        }
        .presentationDragIndicator(.visible)
        .presentationBackground(UP.panel)
    }
}

private func hint(_ s: String) -> some View {
    Text(s).font(.footnote).foregroundStyle(UP.muted).padding(.top, 12).fixedSize(horizontal: false, vertical: true)
}

// MARK: General

struct GeneralPane: View {
    @Environment(AppModel.self) private var app
    @State private var voices: [(id: String, label: String)] = []
    @State private var askWeb = false

    var body: some View {
        @Bindable var app = app
        VStack(alignment: .leading, spacing: 0) {
            SettingRow(title: "Appearance", detail: "Light, dark, or follow this device.", stacked: true) {
                UPSegmented(options: [("auto", "System"), ("light", "Light"), ("dark", "Dark")], selection: $app.theme)
            }
            SettingRow(title: "Text size", detail: "Size of messages and the composer.", stacked: true) {
                UPSegmented(options: [("s", "Small"), ("m", "Medium"), ("l", "Large")], selection: $app.textSize)
            }
            SettingRow(title: "Return sends the message", detail: "Off: Return adds a new line; use the arrow to send.") { UPSwitch(isOn: $app.enterSends) }
            if !app.models.isEmpty {
                SettingRow(title: "Default model", detail: "Used for new chats on this device.", stacked: true) {
                    GlassSelect(options: app.models.map { ($0.name, $0.label, $0.desc) }, selection: Binding(get: { app.model ?? "" }, set: { app.preferredModel = $0 }))
                }
            }
            SettingRow(title: "Default reasoning", detail: "How long the model thinks before answering.", stacked: true) {
                GlassSelect(options: [("off", "Off", nil), ("low", "Low", nil), ("medium", "Medium", nil), ("high", "High", nil)], selection: $app.think)
            }
            SettingRow(title: "Heavy job warning", detail: "Shows a notice when a picture or training job makes chat slow.") { UPSwitch(isOn: $app.warnHeavy) }
            SettingRow(title: "Read answers aloud", detail: "Speaks every answer with a voice from your Mac when it is finished.") { UPSwitch(isOn: $app.autoRead) }
            SettingRow(title: "Voice", detail: "The natural voices need ./setup_extras.sh voice on the Mac.", stacked: true) {
                GlassSelect(options: [("", "Default", nil)] + voices.map { ($0.id, $0.label, nil) }, selection: $app.voice)
            }
            SettingRow(title: "Web access", detail: "Lets the model search the web and read pages. Off keeps everything on your Mac.") {
                UPSwitch(isOn: Binding(get: { app.web }, set: { v in if v { askWeb = true } else { app.web = false } }))
            }
            SettingRow(title: "Tools", detail: "Let the model make music and pictures, run code and create files.") { UPSwitch(isOn: $app.tools) }
        }
        .task(id: app.connection) {
            guard app.connection == .online, let api = app.api else { return }
            voices = (try? await api.voices()) ?? []
            if !app.voice.isEmpty, !voices.contains(where: { $0.id == app.voice }) { app.voice = "" }
        }
        .alert("Allow web access?", isPresented: $askWeb) {
            Button("Cancel", role: .cancel) {}
            Button("Allow") { app.web = true }
        } message: { Text("Searches and the pages the model opens will leave your Mac and go to the internet. Everything else stays local.") }
    }
}

// MARK: Personalization

struct PersonalPane: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        @Bindable var app = app
        VStack(alignment: .leading, spacing: 14) {
            hint("What you write here is added to the instructions the model gets in every chat from this iPhone. It is sent only to your server.")
            FieldLabel(title: "What should it call you?")
            TextField("Your name", text: $app.pName).upField()
            FieldLabel(title: "What do you do?")
            TextField("For example: student, designer, software engineer", text: $app.pAbout).upField()
            FieldLabel(title: "Answer style")
            UPSegmented(options: [("default", "Default"), ("concise", "Concise"), ("detailed", "Detailed"), ("friendly", "Friendly")], selection: $app.pStyle)
            FieldLabel(title: "Custom instructions")
            WandlessField(text: $app.pInstr, placeholder: "Anything else the model should always know or do", minHeight: 120)
            Button("Clear personalization") { app.pName = ""; app.pAbout = ""; app.pStyle = "default"; app.pInstr = "" }.buttonStyle(UPButton())
        }
    }
}

// MARK: Memory

struct MemoryPane: View {
    @Environment(AppModel.self) private var app
    @State private var items: [[String: Any]] = []
    @State private var new = ""
    @State private var confirmClear = false

    var body: some View {
        @Bindable var app = app
        VStack(alignment: .leading, spacing: 12) {
            SettingRow(title: "Use memory", detail: "The model remembers lasting things you tell it, across chats, and can search your earlier chats. Incognito chats never use it.") {
                UPSwitch(isOn: $app.memoryOn)
            }
            Text(items.isEmpty ? "Nothing remembered yet. It learns from your chats as you go, or tell it to remember something." : "\(items.count) \(items.count == 1 ? "thing" : "things") remembered.")
                .font(.footnote).foregroundStyle(UP.muted)
            HStack(spacing: 8) {
                TextField("Add something for it to remember", text: $new).upField().onSubmit { Task { await add() } }
                Button("Add") { Task { await add() } }.buttonStyle(UPButton())
            }
            ForEach(items.reversed().indices, id: \.self) { i in
                let it = Array(items.reversed())[i]
                HStack(alignment: .top) {
                    Text(it.str("text") ?? "").font(.system(size: 14)).foregroundStyle(UP.ink).fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    Button { Task { await remove(it) } } label: { Icon("x", size: 14) }.buttonStyle(.plain).foregroundStyle(UP.muted)
                }
                .padding(.vertical, 8).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
            }
            if !items.isEmpty { Button("Clear all memory", role: .destructive) { confirmClear = true }.buttonStyle(UPButton()) }
        }
        .task { await load() }
        .confirmationDialog("Everything the model remembers about you will be erased.", isPresented: $confirmClear, titleVisibility: .visible) {
            Button("Clear memory", role: .destructive) { Task { items = (try? await app.api?.delete("/api/memory?all=1").dicts("items")) ?? items } }
        }
    }

    private func load() async { items = (try? await app.api?.get("/api/memory").dicts("items")) ?? items }
    private func add() async {
        let t = new.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        new = ""
        items = (try? await app.api?.post("/api/memory", ["text": t]).dicts("items")) ?? items
    }
    private func remove(_ it: [String: Any]) async {
        items = (try? await app.api?.delete("/api/memory?id=\(it.str("id") ?? "")").dicts("items")) ?? items
    }
}

// MARK: Projects

struct ProjectsPane: View {
    @Environment(AppModel.self) private var app
    @State private var editing: String?
    @State private var name = ""
    @State private var instr = ""
    @State private var error: String?
    @State private var deleting: [String: Any]?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            hint("A project gives chats their own instructions and their own documents. Pick one in the sidebar; new chats and the Library then belong to it. Memory is shared.")
            if app.projects.isEmpty { Text("No projects yet.").font(.subheadline).foregroundStyle(UP.muted) }
            ForEach(app.projects.indices, id: \.self) { i in
                let p = app.projects[i]
                HStack(alignment: .top, spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.str("name") ?? "").font(.system(size: 15, weight: .semibold)).foregroundStyle(UP.ink)
                        Text((p.str("instructions") ?? "").isEmpty ? "no instructions" : p.str("instructions")!).font(.caption).foregroundStyle(UP.muted).lineLimit(2)
                    }
                    Spacer()
                    Button { editing = p.str("id"); name = p.str("name") ?? ""; instr = p.str("instructions") ?? "" } label: { Icon("pencil", size: 16) }.buttonStyle(.plain).foregroundStyle(UP.muted)
                    Button { deleting = p } label: { Icon("x", size: 16) }.buttonStyle(.plain).foregroundStyle(UP.muted)
                }
                .padding(.vertical, 8).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
            }
            TextField("Project name", text: $name).upField()
            WandlessField(text: $instr, placeholder: "Instructions for every chat in this project (optional)", minHeight: 100)
            HStack {
                Button(editing == nil ? "Add project" : "Save changes") { Task { await save() } }.buttonStyle(UPButton(primary: true)).disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                if editing != nil { Button("Cancel") { editing = nil; name = ""; instr = "" }.buttonStyle(UPButton()) }
            }
            if let error { Text(error).font(.footnote).foregroundStyle(UP.warn) }
        }
        .task { await app.loadProjects() }
        .confirmationDialog("The project and the documents in it are deleted. Its chats are kept.", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Delete \(deleting?.str("name") ?? "project")", role: .destructive) {
                if let id = deleting?.str("id") {
                    Task { _ = try? await app.api?.delete("/api/projects?id=\(id)"); if app.activeProject == id { app.activeProject = "" }; await app.loadProjects(); await app.loadChats() }
                }
            }
        }
    }

    private func save() async {
        guard let api = app.api else { return }
        var body: [String: Any] = ["name": name, "instructions": instr]
        if let editing { body["id"] = editing }
        do {
            let r = try await api.post("/api/projects", body)
            if editing == nil, app.activeProject.isEmpty, let id = (r["project"] as? [String: Any])?.str("id") { app.activeProject = id }
            editing = nil; name = ""; instr = ""; error = nil
            await app.loadProjects()
        } catch { self.error = error.localizedDescription }
    }
}

// MARK: Tasks

struct TasksPane: View {
    @Environment(AppModel.self) private var app
    @State private var items: [[String: Any]] = []
    @State private var running: [String] = []
    @State private var can = true
    @State private var editing: String?
    @State private var name = ""
    @State private var prompt = ""
    @State private var type = "daily"
    @State private var time = Calendar.current.date(from: DateComponents(hour: 8, minute: 0)) ?? Date()
    @State private var hours = 24
    @State private var folder = ""
    @State private var model = ""
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            hint("Tasks run by themselves at the time you set and leave their answer as a chat. They run while the Mac is on and the server is running. They may use the code sandbox, document files and your library, never the web, music or pictures.")
            if !can { Text("Sign in with an account to schedule tasks.").font(.subheadline).foregroundStyle(UP.muted) }
            ForEach(items.indices, id: \.self) { i in
                let t = items[i]
                let id = t.str("id") ?? ""
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(t.str("name") ?? "").font(.system(size: 15, weight: .semibold)).foregroundStyle(UP.ink)
                        Spacer()
                        Button { Task { await run(id) } } label: { Icon(running.contains(id) ? "refresh" : "play", size: 16) }.disabled(running.contains(id))
                        Button { Task { await toggle(t) } } label: { Icon(t.bool("enabled") == true ? "pause" : "play", size: 16) }
                        Button { edit(t) } label: { Icon("pencil", size: 16) }
                        Button { Task { items = (try? await app.api?.delete("/api/tasks?id=\(id)").dicts("items")) ?? items } } label: { Icon("x", size: 16) }
                    }
                    .buttonStyle(.plain).foregroundStyle(UP.muted)
                    Text(describe(t)).font(.caption).foregroundStyle(UP.muted)
                }
                .padding(.vertical, 8).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
            }
            if items.isEmpty && can { Text("No tasks yet.").font(.subheadline).foregroundStyle(UP.muted) }
            if can {
                TextField("Task name, for example Morning summary", text: $name).upField()
                WandlessField(text: $prompt, placeholder: "What should it do? For example: Summarize the files in the folder below in five bullet points.", minHeight: 90)
                UPSegmented(options: [("daily", "Every day"), ("every", "Every N hours")], selection: $type)
                if type == "daily" {
                    DatePicker("At", selection: $time, displayedComponents: .hourAndMinute).foregroundStyle(UP.ink)
                } else {
                    Stepper("Every \(hours) hours", value: $hours, in: 1...720).foregroundStyle(UP.ink)
                }
                if !app.models.isEmpty { GlassSelect(options: app.models.map { ($0.name, $0.label, $0.desc) }, selection: $model) }
                TextField("Folder on the Mac to read (optional)", text: $folder).upField().textInputAutocapitalization(.never).autocorrectionDisabled()
                HStack {
                    Button(editing == nil ? "Add task" : "Save changes") { Task { await save() } }.buttonStyle(UPButton(primary: true))
                    if editing != nil { Button("Cancel") { reset() }.buttonStyle(UPButton()) }
                }
            }
            if let error { Text(error).font(.footnote).foregroundStyle(UP.warn) }
        }
        .task {
            if model.isEmpty { model = app.model ?? "" }
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(running.isEmpty ? 30 : 4))
            }
        }
    }

    private func describe(_ t: [String: Any]) -> String {
        let w = t["when"] as? [String: Any] ?? [:]
        let when = w.str("type") == "every" ? "every \(w.int("hours") ?? 24) h" : "daily at \(w.str("time") ?? "")"
        let last = (t.dbl("last_run") ?? 0) > 0 ? "last " + Date(timeIntervalSince1970: t.dbl("last_run")!).formatted(date: .abbreviated, time: .shortened) : "not run yet"
        let st = t.str("last_status").flatMap { $0 == "ok" || $0.isEmpty ? nil : " (\($0))" } ?? ""
        return when + " · " + (running.contains(t.str("id") ?? "") ? "running now…" : last + st) + (t.bool("enabled") == true ? "" : " · paused")
    }

    private func load() async {
        guard let api = app.api, let r = try? await api.get("/api/tasks") else { return }
        items = r.dicts("items"); running = r["running"] as? [String] ?? []; can = r.bool("can") ?? false
    }

    private func payload(_ base: [String: Any]? = nil) -> [String: Any] {
        let c = Calendar.current.dateComponents([.hour, .minute], from: time)
        var b: [String: Any] = ["name": name, "prompt": prompt, "type": type, "time": String(format: "%02d:%02d", c.hour ?? 8, c.minute ?? 0), "hours": hours, "folder": folder, "model": model, "enabled": true]
        if let editing { b["id"] = editing }
        return b
    }

    private func save() async {
        guard let api = app.api else { return }
        do { items = try await api.post("/api/tasks", payload()).dicts("items"); reset() } catch { self.error = error.localizedDescription }
    }

    private func toggle(_ t: [String: Any]) async {
        let w = t["when"] as? [String: Any] ?? [:]
        var b = t
        b["type"] = w.str("type"); b["time"] = w.str("time"); b["hours"] = w.int("hours"); b["enabled"] = !(t.bool("enabled") ?? true)
        b.removeValue(forKey: "when")
        items = (try? await app.api?.post("/api/tasks", b).dicts("items")) ?? items
    }

    private func run(_ id: String) async {
        do { try await app.api?.post("/api/tasks/run", ["id": id]); running.append(id) } catch { self.error = error.localizedDescription }
    }

    private func edit(_ t: [String: Any]) {
        let w = t["when"] as? [String: Any] ?? [:]
        editing = t.str("id"); name = t.str("name") ?? ""; prompt = t.str("prompt") ?? ""; folder = t.str("folder") ?? ""; model = t.str("model") ?? model
        type = w.str("type") ?? "daily"; hours = w.int("hours") ?? 24
        let parts = (w.str("time") ?? "08:00").split(separator: ":").compactMap { Int($0) }
        time = Calendar.current.date(from: DateComponents(hour: parts.first ?? 8, minute: parts.count > 1 ? parts[1] : 0)) ?? time
    }

    private func reset() { editing = nil; name = ""; prompt = ""; folder = ""; type = "daily"; hours = 24; error = nil }
}

// MARK: Models

struct ModelsPane: View {
    @Environment(AppModel.self) private var app
    @State private var items: [[String: Any]] = []
    @State private var suggest: [[String: Any]] = []
    @State private var can = false
    @State private var name = ""
    @State private var pulling = false
    @State private var progress: Double?
    @State private var status = ""
    @State private var removing: [String: Any]?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            hint(can ? "Models run on your Mac. Downloading one needs the internet once on the Mac; after that it works offline." : "Sign in with an account to download or remove models.")
            HStack(spacing: 8) {
                TextField("Model name, for example qwen3:14b", text: $name).upField().textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("Download") { Task { await pull() } }.buttonStyle(UPButton()).disabled(!can || pulling || name.isEmpty)
            }
            if pulling || !status.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    if pulling { ProgressView(value: progress).progressViewStyle(.linear) }
                    Text(status).font(.caption).foregroundStyle(UP.muted)
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(suggest.indices, id: \.self) { i in
                        let s = suggest[i]
                        if !items.contains(where: { $0.str("name") == s.str("name") }) {
                            Button(s.str("name") ?? "") { name = s.str("name") ?? "" }.font(.footnote).padding(.horizontal, 12).padding(.vertical, 6)
                                .glassEffect(.regular.interactive(), in: Capsule()).foregroundStyle(UP.ink)
                        }
                    }
                }
            }
            ForEach(items.indices, id: \.self) { i in
                let m = items[i]
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        let n = m.str("name") ?? "", l = m.str("label") ?? n
                        Text(l == n ? n : "\(l) (\(n))").font(.system(size: 15, weight: .semibold)).foregroundStyle(UP.ink)
                        Text(gb(m.dbl("size") ?? 0) + (m.bool("helper") == true ? " · used behind the scenes" : "")).font(.caption).foregroundStyle(UP.muted)
                    }
                    Spacer()
                    if can { Button { removing = m } label: { Icon("x", size: 16) }.buttonStyle(.plain).foregroundStyle(UP.muted) }
                }
                .padding(.vertical, 8).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
            }
        }
        .task { await load() }
        .confirmationDialog("The files are deleted from the Mac. You can download the model again later.", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("Remove \(removing?.str("name") ?? "")", role: .destructive) {
                if let n = removing?.str("name") {
                    Task {
                        do { items = try await app.api?.delete("/api/models?name=\(n.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? n)").dicts("items") ?? items } catch { status = error.localizedDescription }
                        await app.refresh()
                    }
                }
            }
        }
    }

    private func gb(_ b: Double) -> String { b >= 1e9 ? String(format: "%.1f GB", b / 1e9) : "\(max(1, Int(b / 1e6))) MB" }

    private func load() async {
        guard let api = app.api, let r = try? await api.get("/api/models/installed") else { return }
        items = r.dicts("items"); suggest = r.dicts("suggest"); can = r.bool("can_manage") ?? false
    }

    private func pull() async {
        guard let api = app.api else { return }
        pulling = true; progress = nil; status = "Starting..."
        do {
            for try await p in api.pull(model: name.trimmingCharacters(in: .whitespaces)) {
                progress = p.fraction
                status = (p.fraction.map { "\(Int($0 * 100))% " } ?? "") + p.status
            }
            status = "Done."
            name = ""
        } catch { status = error.localizedDescription }
        pulling = false
        await load()
        await app.refresh()
    }
}

// MARK: API

struct APIPane: View {
    @Environment(AppModel.self) private var app
    @State private var keys: [[String: Any]] = []
    @State private var can = false
    @State private var name = ""
    @State private var newKey: String?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            hint("Other programs can use your models through an OpenAI-compatible API. Calls are not saved and do not use your memory.")
            SettingRow(title: "Base URL", detail: (app.server?.displayAddress ?? "") + "/v1") { EmptyView() }
            if !can { Text("Sign in with an account to make API keys.").font(.subheadline).foregroundStyle(UP.muted) }
            if can {
                HStack(spacing: 8) {
                    TextField("Name for a new key", text: $name).upField()
                    Button("Create key") { Task { await create() } }.buttonStyle(UPButton())
                }
            }
            if let k = newKey {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Your new key. Copy it now, it is not shown again.").font(.footnote.weight(.semibold)).foregroundStyle(UP.ink)
                    Text(k).font(.system(size: 12, design: .monospaced)).textSelection(.enabled).foregroundStyle(UP.ink)
                    Button("Copy") { UIPasteboard.general.string = k }.buttonStyle(UPButton())
                }
                .padding(12).background(RoundedRectangle(cornerRadius: 12).fill(UP.bg))
            }
            ForEach(keys.indices, id: \.self) { i in
                let k = keys[i]
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(k.str("name") ?? "").font(.system(size: 15, weight: .semibold)).foregroundStyle(UP.ink)
                        Text((k.str("prefix") ?? "") + "… · " + ((k.dbl("last_used") ?? 0) > 0 ? "used " + Date(timeIntervalSince1970: k.dbl("last_used")!).formatted(date: .abbreviated, time: .omitted) : "never used"))
                            .font(.caption).foregroundStyle(UP.muted)
                    }
                    Spacer()
                    Button { Task { keys = (try? await app.api?.delete("/api/keys?id=\(k.str("id") ?? "")").dicts("items")) ?? keys } } label: { Icon("x", size: 16) }
                        .buttonStyle(.plain).foregroundStyle(UP.muted)
                }
                .padding(.vertical, 8).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
            }
            if let error { Text(error).font(.footnote).foregroundStyle(UP.warn) }
        }
        .task {
            guard let r = try? await app.api?.get("/api/keys") else { return }
            keys = r.dicts("items"); can = r.bool("can") ?? false
        }
    }

    private func create() async {
        guard let api = app.api else { return }
        do {
            let r = try await api.post("/api/keys", ["name": name])
            newKey = r.str("key"); keys = r.dicts("items"); name = ""
        } catch { self.error = error.localizedDescription }
    }
}

// MARK: Help

struct HelpPane: View {
    @Environment(AppModel.self) private var app
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            hint("unplugged.ai runs on a Mac with Apple Silicon. Set it up once there; this app then connects to it on the same Wi-Fi, nearby without any network, or through your own VPN.")
            NavigationLink { GuideView() } label: { navRow("Set up unplugged.ai on a Mac", "book") }
            NavigationLink { ConnectHelp() } label: { navRow("Connect on the same Wi-Fi", "wifi") }
            NavigationLink { NearbyHelp() } label: { navRow("Connect without any network (nearby)", "antenna.radiowaves.left.and.right") }
            NavigationLink { RemoteAccessHelp() } label: { navRow("Connect from outside your home", "globe") }
            NavigationLink { WatchHelp() } label: { navRow("Use the Apple Watch", "applewatch") }
            NavigationLink { TroubleshootingView() } label: { navRow("Troubleshooting", "wrench.and.screwdriver") }
            NavigationLink { PrivacyView() } label: { navRow("Privacy", "lock.shield") }
            Link(destination: URL(string: "https://github.com/lejacobdev/unplugged.ai")!) { navRow("Project on GitHub", "chevron.left.forwardslash.chevron.right") }
            Button { app.settingsOpen = false; app.onboarded = false } label: { navRow("Show the welcome screens again", "sparkles") }
            Text("Version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""))")
                .font(.caption).foregroundStyle(UP.muted).padding(.top, 8)
        }
    }

    private func navRow(_ title: String, _ icon: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon).frame(width: 22).foregroundStyle(UP.muted)
            Text(title).foregroundStyle(UP.ink)
            Spacer()
            Icon("chevron", size: 14).rotationEffect(.degrees(-90)).foregroundStyle(UP.muted)
        }
        .font(.system(size: 15))
        .padding(.vertical, 12)
        .overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
        .contentShape(Rectangle())
    }
}

struct PrivacyView: View {
    var body: some View {
        HelpPage(title: "Privacy", paragraphs: [
            "This app has no servers of its own and collects nothing. It talks only to the unplugged.ai servers you add.",
            "Your sign-in is kept as a session token in this iPhone's Keychain. Your password is not stored.",
            "Chats, pictures and voice recordings are sent to your server and processed there. On a plain http address they are not encrypted on the way; on networks you do not trust, use https, a VPN, or the nearby connection.",
            "Local Network access is used only to find unplugged.ai servers. The microphone is used only while you dictate.",
        ])
    }
}
