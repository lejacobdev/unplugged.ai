import Foundation
import Observation

/// App-wide state: the connected server, who is signed in, preferences, and what is on screen.
@MainActor @Observable
final class AppModel {
    static let shared = AppModel()

    enum Connection: Equatable { case none, checking, online, signedOut, offline(String) }
    enum Section: String, CaseIterable, Identifiable {
        case chat, music, pictures, library, console
        var id: String { rawValue }
        var title: String { ["chat": "Chat", "music": "Music", "pictures": "Pictures", "library": "Library", "console": "Console"][rawValue]! }
        var icon: String { ["chat": "message", "music": "music", "pictures": "image", "library": "library", "console": "terminal"][rawValue]! }
    }

    let store = ServerStore.shared
    var connection: Connection = .none
    var userName = ""
    var userKind = "user"
    var models: [ModelInfo] = []
    var busyWarning = false
    var needsSignIn: Server?

    // what is on screen
    var section: Section = .chat
    var drawerOpen = false
    var settingsOpen = false
    var settingsPane: SettingsPane = .general
    /// The open chat (nil: a new, empty one). `chatToken` changes whenever another chat is opened.
    var chatID: String?
    var chatIncognito = false
    /// The model of the open chat (shown in the top bar); nil for a new chat, which uses `model`.
    var chatModel: String?
    var chatToken = UUID()
    var chats: [ChatSummary] = []
    var projects: [[String: Any]] = []

    // preferences (this device)
    private static let d = UserDefaults.standard
    var onboarded = UserDefaults.standard.bool(forKey: "onboarded") { didSet { Self.d.set(onboarded, forKey: "onboarded") } }
    var preferredModel = UserDefaults.standard.string(forKey: "chat.model") ?? "" { didSet { Self.d.set(preferredModel, forKey: "chat.model") } }
    var think = UserDefaults.standard.string(forKey: "chat.think") ?? "low" { didSet { Self.d.set(think, forKey: "chat.think") } }
    var tools = UserDefaults.standard.object(forKey: "chat.tools") as? Bool ?? true { didSet { Self.d.set(tools, forKey: "chat.tools") } }
    var web = UserDefaults.standard.bool(forKey: "chat.web") { didSet { Self.d.set(web, forKey: "chat.web") } }
    var memoryOn = UserDefaults.standard.object(forKey: "chat.memory") as? Bool ?? true { didSet { Self.d.set(memoryOn, forKey: "chat.memory") } }
    var warnHeavy = UserDefaults.standard.object(forKey: "warn.heavy") as? Bool ?? true { didSet { Self.d.set(warnHeavy, forKey: "warn.heavy") } }
    var autoRead = UserDefaults.standard.bool(forKey: "voice.autoRead") { didSet { Self.d.set(autoRead, forKey: "voice.autoRead") } }
    var voice = UserDefaults.standard.string(forKey: "voice.name") ?? "" { didSet { Self.d.set(voice, forKey: "voice.name") } }
    var theme = UserDefaults.standard.string(forKey: "ui.theme") ?? "auto" { didSet { Self.d.set(theme, forKey: "ui.theme") } }
    var textSize = UserDefaults.standard.string(forKey: "ui.size") ?? "m" { didSet { Self.d.set(textSize, forKey: "ui.size") } }
    var enterSends = UserDefaults.standard.object(forKey: "ui.enter") as? Bool ?? false { didSet { Self.d.set(enterSends, forKey: "ui.enter") } }
    var activeProject = UserDefaults.standard.string(forKey: "project.active") ?? "" { didSet { Self.d.set(activeProject, forKey: "project.active") } }
    var pName = UserDefaults.standard.string(forKey: "p.name") ?? "" { didSet { Self.d.set(pName, forKey: "p.name") } }
    var pAbout = UserDefaults.standard.string(forKey: "p.about") ?? "" { didSet { Self.d.set(pAbout, forKey: "p.about") } }
    var pStyle = UserDefaults.standard.string(forKey: "p.style") ?? "default" { didSet { Self.d.set(pStyle, forKey: "p.style") } }
    var pInstr = UserDefaults.standard.string(forKey: "p.instr") ?? "" { didSet { Self.d.set(pInstr, forKey: "p.instr") } }

    @ObservationIgnored private var cachedAPI: API?
    /// One client per server (each holds its own URLSession).
    var api: API? {
        guard let s = store.active else { return nil }
        if let c = cachedAPI, c.server == s { return c }
        cachedAPI?.invalidate()
        let a = API(s)
        cachedAPI = a
        return a
    }
    var server: Server? { store.active }

    /// The model for new chats: the saved choice if this server has it, otherwise the server's first.
    var model: String? {
        if models.contains(where: { $0.name == preferredModel }) { return preferredModel }
        return models.first?.name
    }

    func label(for model: String?) -> String {
        models.first { $0.name == model }?.label ?? model ?? "model"
    }

    var personal: [String: Any] { ["name": pName, "about": pAbout, "style": pStyle, "instr": pInstr] }

    func projectName(_ id: String?) -> String? {
        guard let id, !id.isEmpty else { return nil }
        return projects.first { $0.str("id") == id }?.str("name")
    }

    private init() {
        if store.active != nil { Task { await refresh() } }
    }

    /// Checks the active server: reachable, signed in, which models; then loads chats and projects.
    func refresh() async {
        guard let api else { connection = .none; return }
        if connection != .online { connection = .checking }
        do {
            if let n = api.server.nearbyName { try await Tunnel.shared.start(n) }
            _ = try await api.ping()
            guard api.token != nil else { connection = .signedOut; needsSignIn = api.server; return }
            let me = try await api.me()
            userName = me.name
            userKind = me.kind
            let st = try await api.status()
            models = st.models
            busyWarning = st.busy
            connection = .online
            await loadChats()
            await loadProjects()
        } catch APIError.signedOut {
            Keychain.delete(account: api.server.id.uuidString)
            connection = .signedOut
            needsSignIn = api.server
        } catch {
            connection = .offline(error.localizedDescription)
            // Nearby: the direct link comes and goes; keep trying quietly instead of waiting for the user.
            if api.server.isNearby {
                let id = api.server.id
                Task {
                    try? await Task.sleep(for: .seconds(4))
                    if case .offline = connection, store.activeID == id { await refresh() }
                }
            }
        }
    }

    func loadChats() async {
        guard let api, connection == .online else { return }
        if let c = try? await api.chats() { chats = c }
    }

    func loadProjects() async {
        guard let api, connection == .online else { return }
        projects = (try? await api.get("/api/projects").dicts("items")) ?? projects
        if !activeProject.isEmpty, !projects.contains(where: { $0.str("id") == activeProject }) { activeProject = "" }
    }

    func newChat(incognito: Bool = false) {
        chatID = nil
        chatModel = nil
        chatIncognito = incognito
        chatToken = UUID()
        section = .chat
        drawerOpen = false
    }

    func open(chat id: String) {
        chatID = id
        chatModel = nil
        chatIncognito = false
        chatToken = UUID()
        section = .chat
        drawerOpen = false
    }

    func connect(_ s: Server) async {
        store.activate(s)
        connection = .checking
        models = []
        chats = []
        newChat()
        await refresh()
    }

    func signedIn(on s: Server, as name: String) async {
        var s = s
        s.userName = name
        store.update(s)
        store.activate(s)
        needsSignIn = nil
        await refresh()
    }

    func signOut() async {
        guard let api else { return }
        await api.logout()
        connection = .signedOut
        userName = ""
        models = []
        chats = []
        newChat()
    }

    func disconnect() {
        store.disconnect()
        connection = .none
        userName = ""
        models = []
        chats = []
        newChat()
    }

    func openSettings(_ pane: SettingsPane = .general) {
        settingsPane = pane
        drawerOpen = false
        settingsOpen = true
    }
}

enum SettingsPane: String, CaseIterable, Identifiable {
    case general, personal, memory, projects, tasks, models, api, servers, help
    var id: String { rawValue }
    var title: String {
        ["general": "General", "personal": "Personalization", "memory": "Memory", "projects": "Projects", "tasks": "Tasks",
         "models": "Models", "api": "API", "servers": "Servers", "help": "Help"][rawValue]!
    }
}
