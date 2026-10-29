import SwiftUI

/// Settings > Servers: the connected server, Macs found nearby or on this network, saved servers, add by address.
struct ServersPane: View {
    @Environment(AppModel.self) private var app
    @State private var discovery = Discovery()
    @State private var adding = false
    @State private var editing: Server?
    @State private var reachable: [UUID: Bool] = [:]
    @State private var confirmSignOut = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let s = app.server {
                section("Connected")
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 10) {
                        StatusDot(on: app.connection == .online)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.name).font(.system(size: 16, weight: .semibold)).foregroundStyle(UP.ink)
                            Text(s.displayAddress + " · " + connectionText).font(.caption).foregroundStyle(UP.muted).lineLimit(3)
                        }
                    }
                    HStack {
                        if app.connection == .online {
                            Button("Sign out") { confirmSignOut = true }.buttonStyle(UPButton())
                        } else if app.connection == .signedOut {
                            Button("Sign in") { app.needsSignIn = s }.buttonStyle(UPButton(primary: true))
                        } else {
                            Button("Try again") { Task { await app.refresh() } }.buttonStyle(UPButton())
                        }
                        Button("Disconnect") { app.disconnect() }.buttonStyle(UPButton())
                    }
                }
                .padding(14).background(RoundedRectangle(cornerRadius: 14).fill(UP.bg))
            }

            HStack { section("Nearby and on this network"); if discovery.state == .searching { ProgressView().controlSize(.mini) } }
            ForEach(discovery.nearby) { f in
                serverRow(icon: "antenna.radiowaves.left.and.right", title: f.macName, detail: "Nearby, works without Wi-Fi network or internet") { Task { await connectNearby(f) } }
            }
            ForEach(discovery.found) { f in
                serverRow(icon: "wifi", title: f.macName, detail: "\(f.host):\(f.port) on this network") { Task { await connectFound(f) } }
            }
            discoveryFooter

            section("Saved")
            if app.store.servers.isEmpty { Text("No saved servers yet.").font(.subheadline).foregroundStyle(UP.muted) }
            ForEach(app.store.servers.sorted { $0.lastUsed > $1.lastUsed }) { s in
                HStack(spacing: 10) {
                    Button { Task { await app.connect(s) } } label: {
                        HStack(spacing: 10) {
                            StatusDot(on: reachable[s.id] ?? false, unknown: reachable[s.id] == nil)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(s.name).font(.system(size: 15)).foregroundStyle(UP.ink)
                                Text(s.displayAddress + (s.userName.map { " · \($0)" } ?? "")).font(.caption).foregroundStyle(UP.muted)
                            }
                            Spacer()
                            if s.id == app.store.activeID { Icon("check", size: 16).foregroundStyle(UP.ink) }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Menu {
                        if !s.isNearby { Button { editing = s } label: { Label { Text("Edit") } icon: { Image("i.pencil") } } }
                        Button(role: .destructive) { app.store.remove(s); if app.store.activeID == nil { app.disconnect() } } label: { Label { Text("Delete") } icon: { Image("i.x") } }
                    } label: { Icon("pencil", size: 16).frame(width: 32, height: 32) }
                        .foregroundStyle(UP.muted)
                }
                .padding(.vertical, 8).overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
            }
            Button { adding = true } label: { HStack(spacing: 8) { Icon("plus", size: 16); Text("Add a server by address") } }
                .buttonStyle(UPButton(wide: true)).accessibilityIdentifier("servers.add")
            Text("An IP address, a name like mymac.local, a VPN address (for example Tailscale) or an https domain of a remote server.")
                .font(.caption).foregroundStyle(UP.muted)
        }
        .padding(.top, 14)
        .task { discovery.start(); await checkSaved() }
        .onDisappear { discovery.stop() }
        .sheet(isPresented: $adding) { ServerEditor(server: nil) }
        .sheet(item: $editing) { s in ServerEditor(server: s) }
        .confirmationDialog("Sign out of \(app.server?.name ?? "this server")?", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("Sign out", role: .destructive) { Task { await app.signOut() } }
        }
    }

    private func section(_ t: String) -> some View { CardTitle(t).padding(.top, 6) }

    private func serverRow(icon: String, title: String, detail: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon).frame(width: 24).foregroundStyle(UP.ink)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.system(size: 15)).foregroundStyle(UP.ink)
                    Text(detail).font(.caption).foregroundStyle(UP.muted)
                }
                Spacer()
                Icon("chevron", size: 14).rotationEffect(.degrees(-90)).foregroundStyle(UP.muted)
            }
            .padding(12)
            .glassEffect(.regular.interactive(), in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }

    private var connectionText: String {
        switch app.connection {
        case .online: return "Connected" + (app.userName.isEmpty ? "" : " as \(app.userName)")
        case .checking: return "Connecting..."
        case .signedOut: return "Signed out"
        case .offline(let m): return m
        case .none: return ""
        }
    }

    @ViewBuilder private var discoveryFooter: some View {
        switch discovery.state {
        case .denied:
            VStack(alignment: .leading, spacing: 6) {
                Text("Local Network access is off for this app, so it cannot look for your Mac.").font(.subheadline).foregroundStyle(UP.ink)
                Button("Open Settings") { if let u = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(u) } }.buttonStyle(UPButton())
            }
        case .failed(let m):
            Text("Searching stopped: \(m)").font(.footnote).foregroundStyle(UP.muted)
        default:
            if discovery.found.isEmpty && discovery.nearby.isEmpty {
                Text("Looking for unplugged.ai. Keep the Mac awake with unplugged.ai running. Nearby works without any network as long as Wi-Fi and Bluetooth are switched on (no need to join a network).")
                    .font(.footnote).foregroundStyle(UP.muted)
            }
        }
    }

    private func connectFound(_ f: FoundServer) async {
        let s = app.store.add(Server(name: f.macName, host: f.host, port: f.port, secure: false))
        app.settingsOpen = false
        await app.connect(s)
    }

    private func connectNearby(_ f: FoundServer) async {
        var n = Server(name: f.macName, host: "127.0.0.1", port: 0, secure: false)
        n.nearbyName = f.name
        let s = app.store.add(n)
        app.settingsOpen = false
        await app.connect(s)
    }

    private func checkSaved() async {
        await withTaskGroup(of: (UUID, Bool).self) { group in
            for s in app.store.servers where !s.isNearby || s.id == app.store.activeID {
                group.addTask { (s.id, (try? await API.probe(s)) != nil) }
            }
            for await (id, ok) in group { reachable[id] = ok }
        }
        for s in app.store.servers where s.isNearby && s.id != app.store.activeID {
            reachable[s.id] = discovery.nearby.contains { $0.name == s.nearbyName }
        }
    }
}

struct StatusDot: View {
    var on: Bool
    var unknown = false
    var body: some View {
        Circle().fill(unknown ? Color.gray.opacity(0.4) : (on ? Color.green : Color.red.opacity(0.8))).frame(width: 9, height: 9)
    }
}

/// Add a server by address, or edit a saved one.
struct ServerEditor: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    let server: Server?
    @State private var name = ""
    @State private var address = ""
    @State private var trust = false
    @State private var testing = false
    @State private var result: String?
    @State private var ok = false

    private var parsed: ParsedAddress? { ParsedAddress.parse(address) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("192.168.1.20, mymac.local or https://ai.example.com", text: $address)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .accessibilityIdentifier("editor.address")
                    TextField("Name (optional)", text: $name)
                } header: { Text("Address") } footer: {
                    if let p = parsed {
                        Text("Connects to \(Server(name: "", host: p.host, port: p.port, secure: p.secure).displayAddress). Without a port, plain addresses use 8000, the port unplugged.ai starts on.")
                    } else if !address.isEmpty {
                        Text("That does not look like an address.").foregroundStyle(.red)
                    }
                }
                if parsed?.secure == true {
                    Section {
                        Toggle("Trust this server's certificate", isOn: $trust)
                    } footer: {
                        Text("Only for your own Mac with the certificate made by setup_https.sh. Leave it off for a server with a normal certificate.")
                    }
                }
                Section {
                    Button { Task { await test() } } label: {
                        HStack { Text("Test connection"); Spacer(); if testing { ProgressView() } }
                    }
                    .disabled(parsed == nil || testing)
                    if let result {
                        Label(result, systemImage: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(ok ? .green : .orange).font(.subheadline)
                    }
                }
            }
            .navigationTitle(server == nil ? "Add server" : "Edit server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(server == nil ? "Connect" : "Save") { Task { await save() } }.disabled(parsed == nil || testing)
                        .accessibilityIdentifier("editor.save")
                }
            }
            .onAppear {
                if let s = server { name = s.name; address = s.displayAddress; trust = s.trustCertificate }
            }
        }
    }

    private func candidate() -> Server? {
        guard let p = parsed else { return nil }
        var s = server ?? Server(name: "", host: p.host, port: p.port, secure: p.secure)
        s.host = p.host; s.port = p.port; s.secure = p.secure
        s.trustCertificate = p.secure && trust
        s.name = name.trimmingCharacters(in: .whitespaces).isEmpty ? p.host : name.trimmingCharacters(in: .whitespaces)
        return s
    }

    @discardableResult
    private func test() async -> Bool {
        guard let s = candidate() else { return false }
        testing = true
        defer { testing = false }
        do {
            let info = try await API.probe(s)
            ok = true
            result = info.legacy ? "Found unplugged.ai (an older version)." : "Found unplugged.ai on \(info.name)."
            if name.isEmpty && !info.legacy { name = info.name }
            return true
        } catch {
            ok = false
            result = error.localizedDescription
            return false
        }
    }

    private func save() async {
        guard await test(), let s = candidate() else { return }
        if let old = server, old.host != s.host || old.port != s.port || old.secure != s.secure {
            Keychain.delete(account: s.id.uuidString)   // a different address needs a new sign-in
        }
        if server == nil {
            let saved = app.store.add(s)
            dismiss()
            app.settingsOpen = false
            await app.connect(saved)
        } else {
            app.store.update(s)
            dismiss()
            if app.store.activeID == s.id { await app.refresh() }
        }
    }
}
