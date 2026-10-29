import SwiftUI

/// Music, as in the web app: describe a song, let a chat model write caption and lyrics, review, generate with surround.
struct MusicView: View {
    @Environment(AppModel.self) private var app
    static let lengths: [(value: String, title: String, detail: String?)] = [("short", "Short, about 1 minute", nil), ("medium", "Medium, about 2 minutes", nil), ("long", "Long, about 3 minutes", nil)]

    @State private var idea = ""
    @State private var writer = ""
    @State private var instrumental = false
    @State private var caption = ""
    @State private var lyrics = ""
    @State private var length = "medium"
    @State private var busy: String?          // which button is working
    @State private var job: String?
    @State private var status = ""
    @State private var error: String?
    @State private var songs: [[String: Any]] = []

    var body: some View {
        if app.connection != .online { NotConnectedView() } else {
            ScrollView {
                VStack(spacing: 16) {
                    make
                    library
                }
                .padding(14)
            }
            .background(UP.bg)
            .scrollDismissesKeyboard(.interactively)
            .task { if writer.isEmpty { writer = app.model ?? "" }; await loadSongs() }
            .refreshable { await loadSongs() }
        }
    }

    private var make: some View {
        VStack(alignment: .leading, spacing: 14) {
            CardTitle("Make music")
            FieldLabel(title: "Describe the song", hint: "optional: your chat model writes the caption and lyrics for you to review")
            WandField(text: $idea, placeholder: "A mellow acoustic indie song about driving home at night", minHeight: 70, busy: busy == "idea") { await wand("idea") }
            FieldLabel(title: "Written by")
            GlassSelect(options: app.models.map { ($0.name, $0.label, $0.desc) }, selection: $writer)
            Toggle("Instrumental (no vocals)", isOn: $instrumental).font(.system(size: 15)).foregroundStyle(UP.ink)
            Button { Task { await plan() } } label: {
                HStack { if busy == "plan" { ProgressView() } else { Icon("pencil", size: 16) }; Text("Write caption and lyrics") }
            }
            .buttonStyle(UPButton(wide: true)).disabled(idea.trimmingCharacters(in: .whitespaces).isEmpty || busy != nil)

            FieldLabel(title: "Caption", hint: "the sound")
            WandField(text: $caption, placeholder: "slow atmospheric rock ballad, soft clean electric guitar, warm organ pads", minHeight: 90, busy: busy == "caption") { await wand("caption") }
            FieldLabel(title: "Lyrics", hint: "use [verse], [chorus], [bridge] on their own lines; empty for instrumental")
            WandField(text: $lyrics, placeholder: "[Verse]\n...", minHeight: 160, busy: busy == "lyrics") { await wand("lyrics") }
            FieldLabel(title: "Length")
            GlassSelect(options: MusicView.lengths, selection: $length)

            if let job {
                VStack(alignment: .leading, spacing: 8) {
                    ProgressView().progressViewStyle(.linear)
                    Text(status.isEmpty ? "Starting the music model..." : status).font(.footnote).foregroundStyle(UP.muted)
                    Button("Stop generating") { Task { _ = try? await app.api?.post("/api/music/cancel?id=\(job)") } }.buttonStyle(UPButton(wide: true))
                }
                .task(id: job) { await follow(job) }
            } else {
                Button("Generate song") { Task { await generate() } }
                    .buttonStyle(UPButton(primary: true, wide: true)).disabled(caption.trimmingCharacters(in: .whitespaces).isEmpty)
                    .accessibilityIdentifier("music.generate")
            }
            if let error { Text(error).font(.footnote).foregroundStyle(UP.warn) }
            if !status.isEmpty && job == nil { Text(status).font(.footnote).foregroundStyle(UP.muted) }
        }
        .upCard()
    }

    private var library: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardTitle("Your music")
            if songs.isEmpty { Text("No songs yet.").font(.subheadline).foregroundStyle(UP.muted) }
            ForEach(songs.indices, id: \.self) { i in
                let s = songs[i]
                VStack(alignment: .leading, spacing: 6) {
                    SongPlayer(id: s.str("id") ?? "", caption: s.str("caption"))
                    if let secs = s.int("seconds") { Text("\(secs / 60):\(String(format: "%02d", secs % 60))").font(.caption2).foregroundStyle(UP.muted) }
                }
                .padding(.vertical, 6)
                .overlay(alignment: .bottom) { if i < songs.count - 1 { Rectangle().fill(UP.line).frame(height: 1) } }
            }
        }
        .upCard()
    }

    private func loadSongs() async {
        songs = (try? await app.api?.getList("/api/samples")) ?? songs
    }

    private func plan() async {
        guard let api = app.api else { return }
        busy = "plan"; error = nil
        defer { busy = nil }
        do {
            let r = try await api.post("/api/music/prompt", ["prompt": idea, "model": writer, "instrumental": instrumental], timeout: 300)
            let p = r["plan"] as? [String: Any] ?? [:]
            caption = p.str("caption") ?? caption
            lyrics = p.str("lyrics") ?? ""
            if let l = p.str("length"), MusicView.lengths.contains(where: { $0.value == l }) { length = l }
        } catch { self.error = error.localizedDescription }
    }

    private func wand(_ field: String) async {
        guard let api = app.api else { return }
        busy = field; error = nil
        defer { busy = nil }
        do {
            let r = try await api.post("/api/music/field", ["model": writer, "field": field, "prompt": idea, "caption": caption, "lyrics": lyrics, "instrumental": instrumental], timeout: 300)
            let t = r.str("text") ?? ""
            switch field { case "idea": idea = t; case "caption": caption = t; default: lyrics = t }
        } catch { self.error = error.localizedDescription }
    }

    private func generate() async {
        guard let api = app.api else { return }
        error = nil; status = ""
        do { job = try await api.post("/api/music/make", ["caption": caption, "lyrics": instrumental ? "" : lyrics, "length": length]).str("job") }
        catch { self.error = error.localizedDescription }
    }

    private func follow(_ id: String) async {
        guard let api = app.api else { return }
        while !Task.isCancelled {
            guard let j = try? await api.get("/api/job?id=\(id)") else { status = "Lost track of this song."; job = nil; return }
            let st = j.str("status") ?? ""
            if st == "running" || st == "queued" { status = j.str("message") ?? "Composing..."; try? await Task.sleep(for: .seconds(2)); continue }
            job = nil
            status = st == "done" ? "Done. The song is below." : st == "cancelled" ? "Stopped. No song was made." : (j.str("message") ?? "No song came out.")
            await loadSongs()
            return
        }
    }
}

/// A multi-line field with the magic wand inside (asks the chat model to write it).
struct WandField: View {
    @Binding var text: String
    var placeholder: String
    var minHeight: CGFloat
    var busy: Bool
    var wand: () async -> Void

    var body: some View {
        ZStack(alignment: .topTrailing) {
            ZStack(alignment: .topLeading) {
                if text.isEmpty { Text(placeholder).foregroundStyle(UP.muted.opacity(0.7)).padding(.top, 8).padding(.leading, 5) }
                TextEditor(text: $text).scrollContentBackground(.hidden).foregroundStyle(UP.ink).frame(minHeight: minHeight)
            }
            .padding(.trailing, 34)
            .upField()
            Button { Task { await wand() } } label: {
                Group { if busy { ProgressView().controlSize(.small) } else { Icon("wand", size: 18) } }
                    .frame(width: 32, height: 32).glassEffect(.regular.interactive(), in: RoundedRectangle(cornerRadius: 9))
            }
            .buttonStyle(.plain).foregroundStyle(UP.ink).padding(6).disabled(busy)
            .accessibilityLabel("Let the model write this")
        }
    }
}
