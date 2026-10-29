import SwiftUI
import UIKit

/// How to set up unplugged.ai on a Mac, step by step, with commands you can copy.
struct GuideView: View {
    var embedded = true

    var body: some View {
        if embedded { content } else { NavigationStack { content } }
    }

    private var content: some View {
        List {
            Section {
                Text("unplugged.ai runs on a Mac with Apple Silicon. You set it up once on the Mac (about an hour, mostly downloads); after that this app connects to it.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Section("Set up the Mac") {
                ForEach(GuideStep.all) { step in
                    NavigationLink { GuideStepView(step: step) } label: {
                        HStack(spacing: 12) {
                            Text("\(step.number)").font(.headline).frame(width: 28, height: 28).background(Circle().fill(Color.accentColor.opacity(0.18)))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(step.title)
                                Text(step.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                    }
                }
            }
            Section("Connect this app") {
                NavigationLink { ConnectHelp() } label: { Label("Connect on the same Wi-Fi", systemImage: "wifi") }
                NavigationLink { RemoteAccessHelp() } label: { Label("Connect from outside your home", systemImage: "globe") }
                NavigationLink { NearbyHelp() } label: { Label("Connect without any network", systemImage: "antenna.radiowaves.left.and.right") }
                NavigationLink { WatchHelp() } label: { Label("Use the Apple Watch", systemImage: "applewatch") }
            }
            Section("Help") {
                NavigationLink { TroubleshootingView() } label: { Label("Troubleshooting", systemImage: "wrench.and.screwdriver") }
                Link(destination: URL(string: "https://github.com/lejacobdev/unplugged.ai")!) { Label("Project on GitHub", systemImage: "chevron.left.forwardslash.chevron.right") }
            }
        }
        .navigationTitle("Setup guide")
    }
}

struct GuideStep: Identifiable {
    let number: Int
    let title: String
    let summary: String
    let body: String
    let commands: [String]
    var id: Int { number }

    static let all: [GuideStep] = [
        GuideStep(number: 1, title: "Check your Mac", summary: "Apple Silicon, macOS, about 105 GB free",
                  body: "You need a Mac with an Apple chip (M1 or newer) and about 105 GB of free disk for all features. 16 GB of memory works for chat; 24 GB or more is better for pictures and music. It was developed on an M5 Pro with 24 GB.",
                  commands: []),
        GuideStep(number: 2, title: "Install the tools", summary: "Homebrew, Python, Ollama, git, uv, ffmpeg",
                  body: "Install Homebrew from brew.sh first (open Terminal on the Mac and paste the command shown on that page). Then install the rest:",
                  commands: ["brew install python@3.11 python@3.12 git uv ffmpeg ollama"]),
        GuideStep(number: 3, title: "Get unplugged.ai", summary: "Download the code into your home folder",
                  body: "Keep the folder in a permanent place (your home folder is fine), because the server runs from it.",
                  commands: ["cd ~ && git clone https://github.com/lejacobdev/unplugged.ai.git && cd unplugged.ai"]),
        GuideStep(number: 4, title: "Download the chat models", summary: "stereo, mono, vision and document search",
                  body: "Start Ollama, then download the models (about 30 GB):",
                  commands: ["ollama serve &", "ollama pull gpt-oss:20b", "ollama pull qwen3:14b", "ollama pull qwen3-vl:8b", "ollama pull nomic-embed-text"]),
        GuideStep(number: 5, title: "Python environment", summary: "Everything the server needs",
                  body: "Make the Python environments inside the project folder (the second one is for pictures):",
                  commands: ["python3.11 -m venv .venv && .venv/bin/pip install -r requirements-music.txt", "python3.12 -m venv .venv-img && .venv-img/bin/pip install -r requirements-image.txt"]),
        GuideStep(number: 6, title: "Optional: pictures, music, extras", summary: "Picture editing, songs, code, voice, picture creation",
                  body: "Each part is optional. The picture model needs a free Hugging Face account and accepting the FLUX.1 Kontext license (non-commercial). Run only the ones you want:",
                  commands: ["./setup_image_model.sh", "./setup_surround.sh", "./setup_extras.sh"]),
        GuideStep(number: 7, title: "Start it", summary: "Run the server and make your account",
                  body: "Start the server, then open http://127.0.0.1:8000 on the Mac and create your account there (accounts can only be created on the Mac itself).",
                  commands: ["./start.sh"]),
        GuideStep(number: 8, title: "Start automatically", summary: "Runs at login, restarts if it stops",
                  body: "So you never have to start it by hand, install the login item once. It keeps running in the background and this app can always find it while the Mac is awake.",
                  commands: ["./setup_autostart.sh"]),
        GuideStep(number: 9, title: "Optional: secure connection", summary: "https for the full app and microphone in the browser",
                  body: "This makes a certificate for your Mac. Install the profile it shows on your iPhone (Settings, General, VPN & Device Management) and turn it on under Settings, General, About, Certificate Trust Settings. Then add the server here with its https address on port 8443.",
                  commands: ["./setup_https.sh"]),
    ]
}

struct GuideStepView: View {
    let step: GuideStep
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(step.body).fixedSize(horizontal: false, vertical: true)
                ForEach(step.commands, id: \.self) { CommandBox(command: $0) }
                if step.number == 7 {
                    Text("When it runs, Terminal shows the addresses it can be reached at, for example http://192.168.1.20:8000. This app finds it by itself on the same Wi-Fi.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            .padding()
        }
        .navigationTitle(step.title)
    }
}

struct CommandBox: View {
    let command: String
    @State private var copied = false
    var body: some View {
        HStack(alignment: .top) {
            Text(command).font(.system(.footnote, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            Button {
                UIPasteboard.general.string = command
                copied = true
                Task { try? await Task.sleep(for: .seconds(1.2)); copied = false }
            } label: { Image(systemName: copied ? "checkmark" : "doc.on.doc") }
                .buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("Copy command")
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground)))
    }
}

struct HelpPage: View {
    let title: String
    let paragraphs: [String]
    var commands: [String] = []
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(paragraphs, id: \.self) { Text($0).fixedSize(horizontal: false, vertical: true) }
                ForEach(commands, id: \.self) { CommandBox(command: $0) }
            }
            .padding()
        }
        .navigationTitle(title)
    }
}

struct ConnectHelp: View {
    var body: some View {
        HelpPage(title: "Same Wi-Fi", paragraphs: [
            "1. Make sure unplugged.ai is running on the Mac and the Mac is awake.",
            "2. Join the same Wi-Fi with this iPhone.",
            "3. Open Settings, Servers. Your Mac appears under \"On this network\" within a few seconds. Tap it and sign in with your unplugged.ai account.",
            "If it does not appear: allow Local Network for this app (Settings, Privacy & Security, Local Network), check that the Mac's firewall lets Python accept connections, or add it by address: the Mac's IP address is shown in Terminal when the server starts, and under System Settings, Wi-Fi, Details.",
            "Some guest and office networks block devices from seeing each other. Then use the address, or connect as described under \"outside your home\".",
        ])
    }
}

struct RemoteAccessHelp: View {
    var body: some View {
        HelpPage(title: "From anywhere", paragraphs: [
            "unplugged.ai is not hardened for the open internet, so do not forward its port on your router. Use a private network to your Mac instead.",
            "The simplest way is a mesh VPN such as Tailscale: install it on the Mac and on this iPhone and sign in to both with the same account. The Mac then has an address like 100.x.y.z or a name like mymac.your-tailnet.ts.net. Add that address here (Settings, Servers, Add a server by address), for example 100.64.1.5:8000.",
            "If you run the server behind your own reverse proxy with a proper certificate, add it with its https address, for example https://ai.example.com.",
            "Remote servers can be any machine running unplugged.ai, not only your own Mac, as long as you have an account there.",
        ])
    }
}

struct NearbyHelp: View {
    var body: some View {
        HelpPage(title: "Nearby", paragraphs: [
            "Your iPhone can reach the Mac with no Wi-Fi network and no internet at all, just by being close to it (a few metres, like AirDrop).",
            "How it works: Bluetooth finds the Mac, and a direct peer-to-peer Wi-Fi link between the two carries the data. Both Wi-Fi and Bluetooth must be switched on, on the iPhone and on the Mac, but neither has to join a network.",
            "On the Mac nothing extra is needed: unplugged.ai starts its nearby service by itself (it builds a small helper, unplugged-bridge, the first time; this needs the Xcode command line tools: xcode-select --install).",
            "In this app, open Settings, Servers. The Mac appears with an antenna icon under Nearby. Tap it and sign in.",
            "Keep this app open while you use it: iOS pauses the nearby link when the app is in the background. Speed is like AirDrop, fine for chat, music and pictures.",
        ], commands: ["xcode-select --install"])
    }
}

struct WatchHelp: View {
    var body: some View {
        HelpPage(title: "Apple Watch", paragraphs: [
            "Install the watch app from the Watch app on your iPhone (it is included with this app).",
            "On the watch, tap Ask and speak or scribble your question. The watch hands it to this iPhone, the iPhone sends it to the server you are connected to here, and the answer appears on the watch.",
            "The iPhone must be nearby with this app connected and signed in. Each question becomes a chat on the server, so you can read it later on the phone or the Mac.",
        ])
    }
}

struct TroubleshootingView: View {
    private let items: [(String, String)] = [
        ("The Mac is not found", "Check that the server runs (open http://127.0.0.1:8000 on the Mac), that both devices are on the same Wi-Fi, and that Local Network is allowed for this app. You can always add the Mac by its IP address."),
        ("\"Nothing is running at this address\"", "The address is right but no server answers: start it with ./start.sh, or install the login item with ./setup_autostart.sh. The default port is 8000."),
        ("It worked, then stopped", "The Mac went to sleep or changed its IP address. Wake it, or give it a fixed address in your router. The login item keeps the Mac awake while the server runs."),
        ("Sign-in fails", "Use the account made on the Mac. After five wrong passwords sign-in pauses for 30 seconds. Guest mode only works on the Mac itself."),
        ("Answers are very slow", "A picture, song or training job is running and shares the Mac's memory. Wait until it finishes, or plug the Mac in."),
        ("Certificate errors with https", "Install and trust the profile from setup_https.sh on the iPhone, or turn on \"Trust this server's certificate\" in the server's settings here."),
        ("Microphone does not work in Full app", "Browsers only allow the microphone on secure (https) pages. Use dictation in the Chats tab instead, which works on any connection."),
        ("The watch says the iPhone is not reachable", "Open this app on the iPhone once, keep the phone near the watch, and make sure the app is connected to a server."),
    ]

    var body: some View {
        List(items, id: \.0) { item in
            VStack(alignment: .leading, spacing: 6) {
                Text(item.0).font(.headline)
                Text(item.1).font(.subheadline).foregroundStyle(.secondary)
            }
            .padding(.vertical, 4)
        }
        .navigationTitle("Troubleshooting")
    }
}
