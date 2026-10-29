import SwiftUI

struct OnboardingView: View {
    @Environment(AppModel.self) private var app
    @State private var page = 0

    private let pages: [(icon: String, title: String, text: String)] = [
        ("waveform", "Your AI, on your Mac",
         "unplugged.ai runs chat models, music, pictures and voice entirely on your own Mac. This app is its companion: it connects your iPhone and Apple Watch to it."),
        ("lock.shield", "Private by design",
         "Your chats never go to a cloud. The iPhone talks straight to your Mac over your Wi-Fi, or over your own VPN when you are away. No accounts with us, no tracking."),
        ("antenna.radiowaves.left.and.right", "Finds your Mac by itself",
         "On the same Wi-Fi, or just nearby with no network at all, the app finds a running unplugged.ai automatically. You can also type an IP address or the domain of a remote server."),
        ("applewatch", "On your wrist too",
         "Ask a quick question from your Apple Watch by voice. The iPhone passes it on to your Mac and sends the answer back."),
    ]

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $page) {
                ForEach(Array(pages.enumerated()), id: \.offset) { i, p in
                    VStack(spacing: 22) {
                        Spacer()
                        if i == 0 {
                            Image("Logo").resizable().scaledToFit().frame(width: 110, height: 110)
                        } else {
                            Image(systemName: p.icon).font(.system(size: 64, weight: .light)).foregroundStyle(UP.brand).frame(height: 110)
                        }
                        Text(p.title).font(.title.bold()).multilineTextAlignment(.center)
                        Text(p.text).font(.body).foregroundStyle(.secondary).multilineTextAlignment(.center).padding(.horizontal, 32)
                        Spacer()
                        Spacer()
                    }
                    .tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .always))

            VStack(spacing: 12) {
                Button {
                    if page < pages.count - 1 { withAnimation { page += 1 } } else { finish(.servers) }
                } label: {
                    Text(page < pages.count - 1 ? "Continue" : "Find my Mac").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
                }
                .buttonStyle(.glassProminent)
                .tint(UP.accent)
                .foregroundStyle(UP.accentInk)
                .accessibilityIdentifier("onboarding.next")
                Button("I don't have unplugged.ai yet: show me how") { finish(.help) }
                    .font(.subheadline).foregroundStyle(UP.muted)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 24)
        }
        .background(UP.bg)
    }

    private func finish(_ pane: SettingsPane) {
        app.onboarded = true
        app.openSettings(pane)
    }
}
