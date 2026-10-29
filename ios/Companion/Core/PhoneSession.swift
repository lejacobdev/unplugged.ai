import Foundation
import UIKit
import WatchConnectivity

/// Answers the Apple Watch: it asks, the iPhone sends the question to the connected server and passes the answer back.
final class PhoneSession: NSObject, WCSessionDelegate, @unchecked Sendable {
    static let shared = PhoneSession()

    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {}
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { WCSession.default.activate() }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        switch message[WatchMessage.kind] as? String {
        case WatchMessage.status:
            let s = ServerStore.activeServerSnapshot()
            let signedIn = s.map { Keychain.get(account: $0.id.uuidString) != nil } ?? false
            guard let s else {
                replyHandler([WatchMessage.connected: false, WatchMessage.signedIn: false]); return
            }
            Task {
                let reachable = (try? await API.probe(s)) != nil
                replyHandler([WatchMessage.serverName: s.name, WatchMessage.connected: reachable, WatchMessage.signedIn: signedIn])
            }
        case WatchMessage.ask:
            let text = (message[WatchMessage.text] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let id = message[WatchMessage.id] as? String ?? UUID().uuidString
            guard !text.isEmpty else { replyHandler([WatchMessage.error: "The question was empty."]); return }
            guard let s = ServerStore.activeServerSnapshot(), Keychain.get(account: s.id.uuidString) != nil else {
                replyHandler([WatchMessage.error: "Open unplugged.ai on your iPhone and connect to a server first."]); return
            }
            replyHandler([WatchMessage.accepted: true])
            answer(text, id: id, server: s)
        default:
            replyHandler([WatchMessage.error: "Unknown request."])
        }
    }

    /// Runs the question on the server (as a normal chat) and sends the full answer to the watch.
    private func answer(_ text: String, id: String, server: Server) {
        let bg = BackgroundTask.begin()
        Task {
            let api = API(server)
            var answer = "", failure: String?
            do {
                let model = UserDefaults.standard.string(forKey: "chat.model")
                let status = try await api.status()
                let use = status.models.contains(where: { $0.name == model }) ? model : status.models.first?.name
                let chat = try await api.newChat(model: use)
                let prompt = text + "\n\n(Asked from an Apple Watch: answer briefly, in a few sentences, without tables or code.)"
                for try await ev in api.stream(chat: chat, text: prompt, model: use, think: "low") {
                    switch ev {
                    case .token(let t): answer += t
                    case .toolResult: answer = ""          // the text after a tool step is the real answer
                    case .error(let m): failure = m
                    default: break
                    }
                }
            } catch {
                failure = error.localizedDescription
            }
            api.invalidate()
            let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
            var reply: [String: Any] = [WatchMessage.kind: WatchMessage.answer, WatchMessage.id: id, WatchMessage.question: text, WatchMessage.text: trimmed]
            if trimmed.isEmpty { reply[WatchMessage.error] = failure ?? "No answer came back." }
            let s = WCSession.default
            if s.activationState == .activated {
                if s.isReachable {
                    s.sendMessage(reply, replyHandler: nil) { _ in s.transferUserInfo(reply) }
                } else {
                    s.transferUserInfo(reply)
                }
            }
            BackgroundTask.end(bg)
        }
    }
}

/// Asks iOS for extra time when the watch woke the app in the background.
enum BackgroundTask {
    static func begin() -> UIBackgroundTaskIdentifier {
        let start = { () -> UIBackgroundTaskIdentifier in
            let box = TaskBox()
            box.id = UIApplication.shared.beginBackgroundTask(withName: "watch-question") {
                UIApplication.shared.endBackgroundTask(box.id)   // out of time: iOS requires ending it here
            }
            return box.id
        }
        return Thread.isMainThread ? start() : DispatchQueue.main.sync(execute: start)
    }

    static func end(_ id: UIBackgroundTaskIdentifier) {
        guard id != .invalid else { return }
        DispatchQueue.main.async { UIApplication.shared.endBackgroundTask(id) }
    }
}

private final class TaskBox: @unchecked Sendable { var id = UIBackgroundTaskIdentifier.invalid }
