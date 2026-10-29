import SwiftUI

/// The app's frame, laid out like the unplugged.ai web app on a phone: a top bar, the current section, and a sidebar
/// that slides in from the left.
struct Shell: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        @Bindable var app = app
        GeometryReader { geo in
        ZStack(alignment: .leading) {
            VStack(spacing: 0) {
                TopBar()
                Group {
                    switch app.section {
                    case .chat: ChatView().id(app.chatToken)
                    case .music: MusicView()
                    case .pictures: PicturesView()
                    case .library: LibraryView()
                    case .console: ConsoleView()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(UP.bg)

            if app.drawerOpen {
                Color.black.opacity(0.45).ignoresSafeArea()
                    .onTapGesture { withAnimation(.snappy) { app.drawerOpen = false } }
                    .transition(.opacity)
                Sidebar()
                    .frame(width: min(geo.size.width * 0.86, 320))
                    .transition(.move(edge: .leading))
            }
        }
        }
        .gesture(DragGesture(minimumDistance: 24).onEnded { g in
            if g.translation.width > 80, abs(g.translation.height) < 60, g.startLocation.x < 40 { withAnimation(.snappy) { app.drawerOpen = true } }
            if g.translation.width < -80, app.drawerOpen { withAnimation(.snappy) { app.drawerOpen = false } }
        })
        .sheet(isPresented: $app.settingsOpen) { SettingsSheet() }
        .sheet(item: $app.needsSignIn) { s in SignInView(server: s) }
        .preferredColorScheme(app.theme == "dark" ? .dark : app.theme == "light" ? .light : nil)
        .dynamicTypeSize(app.textSize == "s" ? .medium : app.textSize == "l" ? .xLarge : .large)
    }
}

struct TopBar: View {
    @Environment(AppModel.self) private var app
    @State private var modelMenu = false

    var body: some View {
        HStack(spacing: 6) {
            Button { withAnimation(.snappy) { app.drawerOpen = true } } label: {
                Icon("menu", size: 24).frame(width: 44, height: 44)
            }
            .accessibilityLabel("Menu").accessibilityIdentifier("top.menu")
            if app.section == .chat, app.connection == .online {
                ModelPill()
            }
            Spacer()
            if app.section == .chat, app.connection == .online {
                Button { app.newChat(incognito: !app.chatIncognito) } label: {
                    Icon(app.chatIncognito ? "eye" : "incognito", size: 20).foregroundStyle(UP.muted).frame(width: 40, height: 44)
                }
                .accessibilityLabel(app.chatIncognito ? "Leave incognito" : "Incognito chat")
            }
            Button { app.newChat() } label: {
                Icon("compose", size: 24).frame(width: 44, height: 44)
            }
            .accessibilityLabel("New chat").accessibilityIdentifier("top.new")
        }
        .foregroundStyle(UP.ink)
        .padding(.horizontal, 6)
        .frame(height: 56)
    }
}

/// "stereo ⌄": model and reasoning, in a Liquid Glass menu.
struct ModelPill: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        @Bindable var app = app
        Menu {
            Section("Model") {
                ForEach(app.models) { m in
                    Button {
                        app.preferredModel = m.name
                        app.chatModel = m.name
                        NotificationCenter.default.post(name: .modelPicked, object: m.name)
                    } label: {
                        Label { Text(m.label); if !m.desc.isEmpty { Text(m.desc) } } icon: { if m.name == (app.chatModel ?? app.model) { Image("i.check") } }
                    }
                }
            }
            Section("Reasoning") {
                Picker("Reasoning", selection: $app.think) {
                    Text("Off").tag("off"); Text("Low").tag("low"); Text("Medium").tag("medium"); Text("High").tag("high")
                }
                .pickerStyle(.palette)
            }
            Section {
                Toggle(isOn: $app.tools) { Label { Text("Tools (music and pictures)") } icon: { Image("i.wand") } }
            }
        } label: {
            HStack(spacing: 5) {
                Text(app.label(for: app.chatModel ?? app.model)).font(.system(size: 17, weight: .semibold))
                Icon("chevron", size: 16).foregroundStyle(UP.muted)
            }
            .foregroundStyle(UP.ink)
            .padding(.horizontal, 10).padding(.vertical, 8)
            .glassEffect(.regular.interactive(), in: Capsule())
        }
        .accessibilityIdentifier("top.model")
    }
}

extension Notification.Name {
    static let modelPicked = Notification.Name("modelPicked")
}

struct Sidebar: View {
    @Environment(AppModel.self) private var app
    @State private var renaming: ChatSummary?
    @State private var newTitle = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { app.newChat() } label: {
                HStack(spacing: 10) {
                    Image("Logo").resizable().frame(width: 24, height: 24).clipShape(RoundedRectangle(cornerRadius: 6))
                    Text("unplugged.ai").font(.system(size: 15, weight: .semibold))
                }
                .foregroundStyle(UP.ink)
            }
            .padding(.horizontal, 10).padding(.top, 10).padding(.bottom, 8)

            row("New chat", icon: "compose", on: false, weight: .medium) { app.newChat() }
                .accessibilityIdentifier("side.new")

            ProjectPicker().padding(.vertical, 6)

            ForEach(AppModel.Section.allCases) { s in
                row(s.title, icon: s.icon, on: app.section == s) {
                    app.section = s
                    withAnimation(.snappy) { app.drawerOpen = false }
                }
                .accessibilityIdentifier("side.\(s.rawValue)")
            }

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if app.connection == .online {
                        if visibleChats.isEmpty {
                            Text("No chats yet").font(.system(size: 12, weight: .semibold)).foregroundStyle(UP.muted).padding(.horizontal, 10).padding(.top, 14)
                        }
                        ForEach(groups, id: \.0) { title, items in
                            Text(title).font(.system(size: 12, weight: .semibold)).foregroundStyle(UP.muted)
                                .padding(.horizontal, 10).padding(.top, 14).padding(.bottom, 6)
                            ForEach(items) { c in historyRow(c) }
                        }
                    } else {
                        Text(app.server == nil ? "Not connected" : "Connecting...").font(.system(size: 13, weight: .semibold)).foregroundStyle(UP.muted)
                            .padding(.horizontal, 10).padding(.top, 18)
                    }
                }
            }
            .refreshable { await app.loadChats() }

            footer
        }
        .padding(.horizontal, 8)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(UP.panel.ignoresSafeArea())
        .alert("Rename chat", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Title", text: $newTitle)
            Button("Cancel", role: .cancel) { renaming = nil }
            Button("Rename") {
                if let c = renaming {
                    let t = newTitle.trimmingCharacters(in: .whitespaces)
                    Task { if !t.isEmpty { try? await app.api?.rename(chat: c.id, to: t) }; await app.loadChats() }
                }
                renaming = nil
            }
        }
        .task { await app.loadChats() }
    }

    private func row(_ title: String, icon: String, on: Bool, weight: Font.Weight = .regular, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Icon(icon, size: 16)
                Text(title).font(.system(size: 14, weight: weight))
                Spacer()
            }
            .foregroundStyle(UP.ink)
            .padding(.horizontal, 10).padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: 10).fill(on ? UP.hover : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func historyRow(_ c: ChatSummary) -> some View {
        Button { app.open(chat: c.id) } label: {
            Text(c.title).font(.system(size: 14)).lineLimit(1).foregroundStyle(UP.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10).padding(.vertical, 8)
                .background(RoundedRectangle(cornerRadius: 10).fill(app.chatID == c.id ? UP.hover : Color.clear))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button { newTitle = c.title; renaming = c } label: { Label { Text("Rename") } icon: { Image("i.pencil") } }
            if !app.projects.isEmpty {
                Menu {
                    Button("No project") { Task { try? await app.api?.setProject(chat: c.id, project: nil); await app.loadChats() } }
                    ForEach(app.projects.indices, id: \.self) { i in
                        let p = app.projects[i]
                        Button(p.str("name") ?? "Project") { Task { try? await app.api?.setProject(chat: c.id, project: p.str("id")); await app.loadChats() } }
                    }
                } label: { Label { Text("Move to project") } icon: { Image("i.folder") } }
            }
            Button(role: .destructive) {
                Task {
                    try? await app.api?.delete(chat: c.id)
                    if app.chatID == c.id { app.newChat() }
                    await app.loadChats()
                }
            } label: { Label { Text("Delete") } icon: { Image("i.x") } }
        }
    }

    private var visibleChats: [ChatSummary] {
        app.activeProject.isEmpty ? app.chats : app.chats.filter { $0.project == app.activeProject }
    }

    private var groups: [(String, [ChatSummary])] {
        let cal = Calendar.current
        var t: [ChatSummary] = [], y: [ChatSummary] = [], w: [ChatSummary] = [], o: [ChatSummary] = []
        for c in visibleChats {
            if cal.isDateInToday(c.updated) { t.append(c) }
            else if cal.isDateInYesterday(c.updated) { y.append(c) }
            else if c.updated > Date().addingTimeInterval(-7 * 86400) { w.append(c) }
            else { o.append(c) }
        }
        return [("Today", t), ("Yesterday", y), ("Previous 7 days", w), ("Older", o)].filter { !$0.1.isEmpty }
    }

    private var footer: some View {
        HStack(spacing: 10) {
            Button { app.openSettings(.servers) } label: {
                HStack(spacing: 10) {
                    Text(String((app.userName.isEmpty ? (app.server?.name ?? "?") : app.userName).prefix(1)).uppercased())
                        .font(.system(size: 14, weight: .bold)).foregroundStyle(UP.accentInk)
                        .frame(width: 32, height: 32).background(Circle().fill(UP.accent))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(app.userName.isEmpty ? (app.server?.name ?? "Not connected") : app.userName).font(.system(size: 14, weight: .semibold)).foregroundStyle(UP.ink).lineLimit(1)
                        HStack(spacing: 4) {
                            Text(statusText).font(.system(size: 11)).foregroundStyle(UP.muted).lineLimit(1)
                            Circle().fill(app.connection == .online ? UP.ok : Color.red.opacity(0.8)).frame(width: 7, height: 7)
                        }
                    }
                }
            }
            .buttonStyle(.plain)
            Spacer()
            Button {
                app.theme = app.theme == "dark" ? "light" : app.theme == "light" ? "auto" : "dark"
            } label: { Icon("theme", size: 17).frame(width: 36, height: 36) }
                .accessibilityLabel("Theme")
            Button { app.openSettings() } label: { Icon("settings", size: 17).frame(width: 36, height: 36) }
                .accessibilityLabel("Settings").accessibilityIdentifier("side.settings")
        }
        .foregroundStyle(UP.muted)
        .padding(.horizontal, 2).padding(.top, 6).padding(.bottom, 2)
    }

    private var statusText: String {
        switch app.connection {
        case .online: return (app.server?.name ?? "") + " ·"
        case .checking: return "Connecting ·"
        case .signedOut: return "Signed out ·"
        case .offline: return "Not reachable ·"
        case .none: return "Not connected ·"
        }
    }
}

/// The project switcher under "New chat" (Liquid Glass menu).
struct ProjectPicker: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        Menu {
            Button { app.activeProject = "" } label: { CheckLabel(title: "All chats", on: app.activeProject.isEmpty) }
            ForEach(app.projects.indices, id: \.self) { i in
                let p = app.projects[i]
                Button { app.activeProject = p.str("id") ?? "" } label: {
                    CheckLabel(title: p.str("name") ?? "Project", on: app.activeProject == p.str("id"))
                }
            }
            Divider()
            Button { app.openSettings(.projects) } label: { Label { Text("Manage projects") } icon: { Image("i.settings") } }
        } label: {
            HStack(spacing: 8) {
                Icon("folder", size: 16)
                Text(app.projectName(app.activeProject) ?? "All chats").font(.system(size: 14)).lineLimit(1)
                Spacer()
                Icon("chevron", size: 14).foregroundStyle(UP.muted)
            }
            .foregroundStyle(UP.ink)
            .padding(.horizontal, 12).padding(.vertical, 9)
            .glassEffect(.regular.interactive(), in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

/// A menu item with a check mark when chosen.
struct CheckLabel: View {
    let title: String
    let on: Bool
    var body: some View {
        if on { Label { Text(title) } icon: { Image("i.check") } } else { Text(title) }
    }
}
