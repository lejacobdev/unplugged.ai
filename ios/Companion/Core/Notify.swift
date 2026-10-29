import UIKit
import UserNotifications

/// Local notifications: when an answer finishes while the app is in the background, the iPhone (and a paired Apple Watch) shows it.
/// The app keeps the answer coming for as long as iOS allows in the background (usually around 30 seconds).
@MainActor
enum Notify {
    static func askOnce() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    static var inBackground: Bool { UIApplication.shared.applicationState != .active }

    static func answer(_ text: String, chat: String) {
        guard inBackground, !text.isEmpty else { return }
        let c = UNMutableNotificationContent()
        c.title = chat.isEmpty || chat == "New chat" ? "unplugged.ai" : chat
        c.body = String(text.prefix(240))
        c.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}

/// Shows notifications also while the app is open in another screen is not wanted; only banners in the background.
final class NotifyDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotifyDelegate()
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [] }
}
