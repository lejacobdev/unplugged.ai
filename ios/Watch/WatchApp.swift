import SwiftUI
import WatchConnectivity

@main
struct UnpluggedWatchApp: App {
    @State private var model = WatchModel.shared

    var body: some Scene {
        WindowGroup {
            WatchHome().environment(model)
        }
    }
}

struct Exchange: Codable, Identifiable, Hashable {
    var id: String
    var question: String
    var answer: String = ""
    var error: String?
    var pending = true
    var date = Date()
}

/// Talks to the iPhone app, which does the network work.
@MainActor @Observable
final class WatchModel: NSObject, WCSessionDelegate {
    static let shared = WatchModel()

    var serverName: String?
    var connected = false
    var signedIn = false
    var phoneReachable = false
    var checking = false
    var history: [Exchange] = [] { didSet { save() } }

    private override init() {
        super.init()
        if let d = UserDefaults.standard.data(forKey: "history"), let h = try? JSONDecoder().decode([Exchange].self, from: d) {
            history = h.map { var e = $0; if e.pending && e.date < Date().addingTimeInterval(-600) { e.pending = false; e.error = e.error ?? "No answer arrived." }; return e }
        }
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
    }

    private func save() {
        if let d = try? JSONEncoder().encode(Array(history.prefix(30))) { UserDefaults.standard.set(d, forKey: "history") }
    }

    func refresh() {
        let s = WCSession.default
        phoneReachable = s.activationState == .activated && s.isReachable
        guard phoneReachable else { checking = false; return }
        checking = true
        s.sendMessage([WatchMessage.kind: WatchMessage.status], replyHandler: { reply in
            Task { @MainActor in
                self.serverName = reply[WatchMessage.serverName] as? String
                self.connected = reply[WatchMessage.connected] as? Bool ?? false
                self.signedIn = reply[WatchMessage.signedIn] as? Bool ?? false
                self.checking = false
            }
        }, errorHandler: { _ in
            Task { @MainActor in self.checking = false; self.phoneReachable = false }
        })
    }

    func ask(_ text: String) {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return }
        let id = UUID().uuidString
        history.insert(Exchange(id: id, question: q), at: 0)
        let s = WCSession.default
        guard s.activationState == .activated, s.isReachable else {
            finish(id, text: "", error: "Your iPhone is not reachable. Keep it nearby and open unplugged.ai on it.")
            return
        }
        s.sendMessage([WatchMessage.kind: WatchMessage.ask, WatchMessage.text: q, WatchMessage.id: id], replyHandler: { reply in
            if let e = reply[WatchMessage.error] as? String { Task { @MainActor in self.finish(id, text: "", error: e) } }
        }, errorHandler: { e in
            Task { @MainActor in self.finish(id, text: "", error: e.localizedDescription) }
        })
    }

    func delete(_ e: Exchange) { history.removeAll { $0.id == e.id } }

    private func finish(_ id: String, text: String, error: String?) {
        guard let i = history.firstIndex(where: { $0.id == id }) else { return }
        history[i].answer = text
        history[i].error = error
        history[i].pending = false
    }

    private func received(_ m: [String: Any]) {
        guard m[WatchMessage.kind] as? String == WatchMessage.answer, let id = m[WatchMessage.id] as? String else { return }
        let text = m[WatchMessage.text] as? String ?? ""
        let err = m[WatchMessage.error] as? String
        if history.contains(where: { $0.id == id }) {
            finish(id, text: text, error: err)
        } else {
            history.insert(Exchange(id: id, question: m[WatchMessage.question] as? String ?? "", answer: text, error: err, pending: false), at: 0)
        }
    }

    // MARK: WCSessionDelegate (called on a background queue)

    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        Task { @MainActor in self.refresh() }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.refresh() }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor in self.received(message) }
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        Task { @MainActor in self.received(userInfo) }
    }
}

struct WatchHome: View {
    @Environment(WatchModel.self) private var model
    @State private var question = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Ask", text: $question)
                        .onSubmit { model.ask(question); question = "" }
                        .accessibilityIdentifier("watch.ask")
                } footer: {
                    Text(statusLine).font(.footnote)
                }
                ForEach(model.history) { e in
                    NavigationLink(value: e) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(e.question).font(.headline).lineLimit(2)
                            if e.pending { HStack(spacing: 6) { ProgressView().frame(width: 16, height: 16); Text("Thinking...").font(.footnote).foregroundStyle(.secondary) } }
                            else if let err = e.error { Text(err).font(.footnote).foregroundStyle(.orange).lineLimit(2) }
                            else { Text(e.answer).font(.footnote).foregroundStyle(.secondary).lineLimit(2) }
                        }
                    }
                    .swipeActions { Button(role: .destructive) { model.delete(e) } label: { Image(systemName: "trash") } }
                }
            }
            .navigationTitle("unplugged.ai")
            .navigationDestination(for: Exchange.self) { e in AnswerView(id: e.id) }
            .onAppear { model.refresh() }
        }
    }

    private var statusLine: String {
        if model.checking { return "Checking your iPhone..." }
        if !model.phoneReachable { return "iPhone not reachable. Keep it nearby." }
        guard let name = model.serverName else { return "Connect to a server in the iPhone app." }
        if !model.signedIn { return "Sign in to \(name) on the iPhone." }
        return model.connected ? "Connected to \(name)" : "\(name) is not reachable right now."
    }
}

struct AnswerView: View {
    @Environment(WatchModel.self) private var model
    let id: String

    var body: some View {
        ScrollView {
            if let e = model.history.first(where: { $0.id == id }) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(e.question).font(.headline)
                    if e.pending { ProgressView() }
                    else if let err = e.error { Text(err).foregroundStyle(.orange) }
                    else { Text(e.answer) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}
