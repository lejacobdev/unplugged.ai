import SwiftUI

struct SignInView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    let server: Server
    @State private var name = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?
    @FocusState private var focus: Field?
    enum Field { case name, password }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $name)
                        .textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .focused($focus, equals: .name).submitLabel(.next).onSubmit { focus = .password }
                        .accessibilityIdentifier("signin.name")
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                        .focused($focus, equals: .password).submitLabel(.go).onSubmit { Task { await signIn() } }
                        .accessibilityIdentifier("signin.password")
                } header: {
                    Text("Your account on \(server.name)")
                } footer: {
                    Text("Use the account you made in unplugged.ai on your Mac. New accounts can only be created on the Mac itself (open http://127.0.0.1:8000 there). Guest mode also works only on the Mac.")
                }
                if let error {
                    Section { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange) }
                }
                Section {
                    Button { Task { await signIn() } } label: {
                        HStack { Spacer(); if busy { ProgressView() } else { Text("Sign in").bold() }; Spacer() }
                    }
                    .disabled(name.isEmpty || password.isEmpty || busy)
                    .accessibilityIdentifier("signin.go")
                }
            }
            .navigationTitle("Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .onAppear { name = server.userName ?? ""; focus = name.isEmpty ? .name : .password }
        }
        .interactiveDismissDisabled(busy)
    }

    private func signIn() async {
        guard !name.isEmpty, !password.isEmpty else { return }
        busy = true
        error = nil
        defer { busy = false }
        let api = API(server)
        defer { api.invalidate() }
        do {
            try await api.login(name: name.trimmingCharacters(in: .whitespaces), password: password)
            password = ""
            await app.signedIn(on: server, as: name.trimmingCharacters(in: .whitespaces))
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
