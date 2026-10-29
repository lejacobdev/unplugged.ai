import PhotosUI
import SwiftUI

/// Pictures, as in the web app: create one from a description, or edit a photo with FLUX Kontext; history below.
struct PicturesView: View {
    @Environment(AppModel.self) private var app
    // create
    @State private var gPrompt = ""
    @State private var gAspect = "square"
    @State private var gJob: String?
    @State private var gStatus = ""
    @State private var gResults: [String] = []
    @State private var gReady = true
    // edit
    @State private var photoItem: PhotosPickerItem?
    @State private var source: UIImage?
    @State private var ePrompt = ""
    @State private var preserve = true
    @State private var livePreview = true
    @State private var quality = "high"
    @State private var size = 1024
    @State private var guidance = 2.5
    @State private var eJob: String?
    @State private var eStatus = ""
    @State private var ePreview: String?
    @State private var eResult: String?
    @State private var eReady = true
    @State private var history: [[String: Any]] = []
    @State private var error: String?

    var body: some View {
        if app.connection != .online { NotConnectedView() } else {
            ScrollView {
                VStack(spacing: 16) {
                    create
                    edit
                    historyCard
                }
                .padding(14)
            }
            .background(UP.bg)
            .scrollDismissesKeyboard(.interactively)
            .task { await loadStatus(); await loadHistory() }
            .refreshable { await loadHistory() }
            .onChange(of: photoItem) { _, item in Task { await pick(item) } }
        }
    }

    private var create: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardTitle("Create a picture")
            if !gReady {
                Text("Setup needed: run ./setup_extras.sh image on the Mac, then restart the server.").font(.footnote).foregroundStyle(UP.warn)
            }
            FieldLabel(title: "Describe the picture")
            WandlessField(text: $gPrompt, placeholder: "A small log cabin in a snowy pine forest next to a ski slope, soft morning light", minHeight: 80)
            FieldLabel(title: "Shape")
            GlassSelect(options: [("square", "Square (1024 x 1024)", nil), ("landscape", "Landscape (1344 x 768)", nil), ("portrait", "Portrait (768 x 1344)", nil)], selection: $gAspect)
            if let job = gJob {
                ProgressView().progressViewStyle(.linear)
                Text(gStatus.isEmpty ? "Starting..." : gStatus).font(.footnote).foregroundStyle(UP.muted)
                Button("Cancel") { Task { _ = try? await app.api?.post("/api/img/cancel?id=\(job)") } }.buttonStyle(UPButton())
                    .task(id: job) { await followCreate(job) }
            } else {
                Button("Create picture") { Task { await startCreate() } }.buttonStyle(UPButton(primary: true, wide: true))
                    .disabled(gPrompt.trimmingCharacters(in: .whitespaces).isEmpty || !gReady)
                if !gStatus.isEmpty { Text(gStatus).font(.footnote).foregroundStyle(UP.muted) }
            }
            ForEach(gResults, id: \.self) { f in
                RemoteImage(path: "/img/\(f)").clipShape(RoundedRectangle(cornerRadius: 12))
            }
        }
        .upCard()
    }

    private var edit: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardTitle("Edit a picture")
            if !eReady {
                Text("Setup needed: the image model (FLUX.1 Kontext) is not installed. Run ./setup_image_model.sh on the Mac.").font(.footnote).foregroundStyle(UP.warn)
            }
            PhotosPicker(selection: $photoItem, matching: .images) {
                Group {
                    if let source {
                        Image(uiImage: source).resizable().scaledToFit().frame(maxHeight: 260).clipShape(RoundedRectangle(cornerRadius: 12))
                    } else {
                        VStack(spacing: 8) {
                            Icon("image", size: 28)
                            Text("Choose a picture").font(.subheadline)
                        }
                        .foregroundStyle(UP.muted).frame(maxWidth: .infinity).frame(height: 130)
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(style: StrokeStyle(lineWidth: 1.5, dash: [6])).foregroundStyle(UP.line))
                    }
                }
            }
            if source != nil { Button("Remove picture", role: .destructive) { source = nil; photoItem = nil }.font(.footnote) }
            FieldLabel(title: "What should change?")
            WandlessField(text: $ePrompt, placeholder: "Make the dog wear a red knitted hat", minHeight: 80)
            Toggle("Live preview while it works", isOn: $livePreview).font(.system(size: 15))
            Toggle("Keep everything else exactly the same", isOn: $preserve).font(.system(size: 15))
            FieldLabel(title: "Quality")
            GlassSelect(options: [("standard", "Standard (28 steps)", nil), ("high", "High (40 steps)", nil), ("maximum", "Maximum (60 steps, slowest)", nil)], selection: $quality)
            FieldLabel(title: "Picture size (long side)")
            GlassSelect(options: [(768, "768 px (faster)", nil), (1024, "1024 px (what the model is best at)", nil), (1280, "1280 px", nil)], selection: $size)
            FieldLabel(title: "Prompt strength  \(String(format: "%.1f", guidance))")
            Slider(value: $guidance, in: 1.5...4.5, step: 0.1)
            if let job = eJob {
                if let p = ePreview { RemoteImage(path: "/img/\(p)").id(p).clipShape(RoundedRectangle(cornerRadius: 12)) }
                ProgressView().progressViewStyle(.linear)
                Text(eStatus.isEmpty ? "Starting..." : eStatus).font(.footnote).foregroundStyle(UP.muted)
                Button("Cancel") { Task { _ = try? await app.api?.post("/api/img/cancel?id=\(job)") } }.buttonStyle(UPButton())
                    .task(id: job) { await followEdit(job) }
            } else {
                Button("Edit picture") { Task { await startEdit() } }.buttonStyle(UPButton(primary: true, wide: true))
                    .disabled(source == nil || ePrompt.trimmingCharacters(in: .whitespaces).isEmpty || !eReady)
                if !eStatus.isEmpty { Text(eStatus).font(.footnote).foregroundStyle(UP.muted) }
            }
            if let r = eResult { RemoteImage(path: "/img/\(r)").clipShape(RoundedRectangle(cornerRadius: 12)) }
            if let error { Text(error).font(.footnote).foregroundStyle(UP.warn) }
        }
        .upCard()
    }

    private var historyCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardTitle("History")
            if history.isEmpty { Text("No edits yet.").font(.subheadline).foregroundStyle(UP.muted) }
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ForEach(history.indices, id: \.self) { i in
                    let h = history[i]
                    if let f = (h["results"] as? [String])?.first {
                        VStack(alignment: .leading, spacing: 4) {
                            RemoteImage(path: "/img/\(f)").frame(height: 150).clipped().clipShape(RoundedRectangle(cornerRadius: 10))
                            Text(h.str("prompt") ?? "").font(.caption2).foregroundStyle(UP.muted).lineLimit(2)
                        }
                        .contextMenu {
                            Button(role: .destructive) {
                                Task { _ = try? await app.api?.delete("/api/img/item?id=\(h.str("id") ?? "")"); await loadHistory() }
                            } label: { Label { Text("Delete") } icon: { Image("i.x") } }
                        }
                    }
                }
            }
        }
        .upCard()
    }

    private func loadStatus() async {
        guard let api = app.api else { return }
        gReady = (try? await api.get("/api/img/gen-status"))?.bool("ready") ?? true
        eReady = (try? await api.get("/api/img/status"))?.bool("ready") ?? true
    }

    private func loadHistory() async {
        history = (try? await app.api?.getList("/api/img/history")) ?? history
    }

    private func pick(_ item: PhotosPickerItem?) async {
        guard let item, let d = try? await item.loadTransferable(type: Data.self), let ui = UIImage(data: d) else { return }
        source = ui
        eResult = nil
    }

    private func startCreate() async {
        guard let api = app.api else { return }
        gStatus = ""
        do { gJob = try await api.post("/api/img/generate", ["prompt": gPrompt, "aspect": gAspect]).str("job") }
        catch { gStatus = error.localizedDescription }
    }

    private func followCreate(_ job: String) async {
        guard let api = app.api else { return }
        let t0 = Date()
        while !Task.isCancelled {
            guard let st = try? await api.imageJob(job) else { gStatus = "Lost track of this picture."; gJob = nil; return }
            if st.done {
                gJob = nil
                if let f = st.file { gResults.insert(f, at: 0); gStatus = "Done in \(Int(Date().timeIntervalSince(t0))) s." } else { gStatus = st.message }
                return
            }
            gStatus = st.message + " · \(Int(Date().timeIntervalSince(t0))) s"
            try? await Task.sleep(for: .seconds(1.5))
        }
    }

    private func startEdit() async {
        guard let api = app.api, let src = source, let jpeg = src.jpegData(compressionQuality: 0.92) else { return }
        error = nil; eStatus = ""; eResult = nil; ePreview = nil
        do {
            let r = try await api.post("/api/img/edit", ["image": "data:image/jpeg;base64," + jpeg.base64EncodedString(), "prompt": ePrompt, "preserve": preserve,
                                                         "quality": quality, "max_side": size, "live_preview": livePreview, "guidance": guidance, "variations": 1], timeout: 120)
            eJob = r.str("job")
        } catch { self.error = error.localizedDescription }
    }

    private func followEdit(_ job: String) async {
        guard let api = app.api else { return }
        let t0 = Date()
        while !Task.isCancelled {
            guard let j = try? await api.get("/api/img/job?id=\(job)") else { eStatus = "Lost track of this edit."; eJob = nil; return }
            let st = j.str("status") ?? ""
            if st == "running" || st == "queued" {
                let step = j.int("step") ?? 0, steps = j.int("steps") ?? 0
                eStatus = (step > 0 ? "Editing… step \(step) of \(steps)" : "Loading the model…") + " · \(Int(Date().timeIntervalSince(t0)) / 60):\(String(format: "%02d", Int(Date().timeIntervalSince(t0)) % 60))"
                if let p = j.str("preview") { ePreview = p + "?n=\(j.int("preview_n") ?? 0)" }
                try? await Task.sleep(for: .seconds(2))
                continue
            }
            eJob = nil
            if st == "done", let f = (j["results"] as? [String])?.first { eResult = f; eStatus = "Done." } else {
                eStatus = st == "cancelled" ? "Cancelled." : (j.str("message") == "unknown job" ? "This edit was interrupted by a server restart." : (j.str("message") ?? st))
            }
            await loadHistory()
            return
        }
    }
}

/// A plain multi-line field in the web app's style.
struct WandlessField: View {
    @Binding var text: String
    var placeholder: String
    var minHeight: CGFloat
    var body: some View {
        ZStack(alignment: .topLeading) {
            if text.isEmpty { Text(placeholder).foregroundStyle(UP.muted.opacity(0.7)).padding(.top, 8).padding(.leading, 5) }
            TextEditor(text: $text).scrollContentBackground(.hidden).foregroundStyle(UP.ink).frame(minHeight: minHeight)
        }
        .upField()
    }
}
