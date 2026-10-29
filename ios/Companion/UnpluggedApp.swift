import SwiftUI

@main
struct UnpluggedApp: App {
    @State private var app = AppModel.shared
    @Environment(\.scenePhase) private var phase

    init() {
        if CommandLine.arguments.contains("-reset") {   // used by the UI tests: start like a fresh install
            for s in ServerStore.shared.servers { ServerStore.shared.remove(s) }
            if let id = Bundle.main.bundleIdentifier { UserDefaults.standard.removePersistentDomain(forName: id) }
            AppModel.shared.onboarded = false
            AppModel.shared.disconnect()
            AppModel.shared.settingsOpen = false
        }
        #if DEBUG
        Self.applyDebugArguments()
        #endif
        PhoneSession.shared.activate()
    }

    #if DEBUG
    /// Development only (never in TestFlight/App Store builds): -seed-server host:port -seed-token T -section music -settings general
    static func applyDebugArguments() {
        let a = CommandLine.arguments
        func value(_ k: String) -> String? { a.firstIndex(of: k).flatMap { a.indices.contains($0 + 1) ? a[$0 + 1] : nil } }
        let app = AppModel.shared
        if let addr = value("-seed-server"), let p = ParsedAddress.parse(addr), let token = value("-seed-token") {
            let s = ServerStore.shared.add(Server(name: "Test server", host: p.host, port: p.port, secure: p.secure))
            Keychain.set(token, account: s.id.uuidString)
            ServerStore.shared.activate(s)
            app.onboarded = true
            Task { await app.refresh() }
        }
        if let sec = value("-section"), let s = AppModel.Section(rawValue: sec) { app.section = s }
        if let pane = value("-settings"), let p = SettingsPane(rawValue: pane) { app.openSettings(p) }
        if a.contains("-drawer") { app.drawerOpen = true }
        if let chat = value("-chat") { app.open(chat: chat) }
    }
    #endif

    var body: some Scene {
        WindowGroup {
            Group {
                if app.onboarded {
                    Shell()
                } else {
                    OnboardingView()
                }
            }
            .environment(app)
            .tint(UP.ink)
            .onChange(of: phase) { _, now in
                if now == .active, let s = app.server {
                    Task {
                        if s.isNearby { await Tunnel.shared.restart() }
                        await app.refresh()
                    }
                }
            }
        }
    }
}
