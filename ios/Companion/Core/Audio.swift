import AVFoundation
import Observation

/// Records a short voice note for dictation (AAC in .m4a). The server turns it into text with Whisper.
@MainActor @Observable
final class Recorder {
    var recording = false
    var level: Float = 0
    private var recorder: AVAudioRecorder?
    private var meter: Timer?
    private let url = FileManager.default.temporaryDirectory.appendingPathComponent("dictation.m4a")

    /// Asks for the microphone the first time. Returns false when access is refused.
    func start() async -> Bool {
        let allowed = await AVAudioApplication.requestRecordPermission()
        guard allowed else { return false }
        do {
            let s = AVAudioSession.sharedInstance()
            try s.setCategory(.playAndRecord, mode: .spokenAudio, options: [.defaultToSpeaker])
            try s.setActive(true)
            let settings: [String: Any] = [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
                                           AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue]
            try? FileManager.default.removeItem(at: url)
            let r = try AVAudioRecorder(url: url, settings: settings)
            r.isMeteringEnabled = true
            guard r.record() else { return false }
            recorder = r
            recording = true
            meter = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let self, let r = self.recorder else { return }
                    r.updateMeters()
                    self.level = max(0, min(1, (r.averagePower(forChannel: 0) + 50) / 50))
                }
            }
            return true
        } catch {
            return false
        }
    }

    /// Stops and returns the recording, or nil when it was too short to contain speech.
    func stop() -> Data? {
        meter?.invalidate(); meter = nil
        let dur = recorder?.currentTime ?? 0
        recorder?.stop()
        recorder = nil
        recording = false
        level = 0
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        guard dur > 0.4 else { return nil }
        return try? Data(contentsOf: url)
    }

    func cancel() { _ = stop() }
}

/// Plays answers read aloud by the Mac (AAC from /api/voice/speak).
@MainActor @Observable
final class Speaker: NSObject, AVAudioPlayerDelegate {
    static let shared = Speaker()
    var playingID: UUID?
    var loadingID: UUID?
    private var player: AVAudioPlayer?

    func play(_ data: Data, id: UUID) {
        stop()
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
            try AVAudioSession.sharedInstance().setActive(true)
            let p = try AVAudioPlayer(data: data)
            p.delegate = self
            p.play()
            player = p
            playingID = id
        } catch {
            playingID = nil
        }
    }

    func stop() {
        player?.stop()
        player = nil
        playingID = nil
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.playingID = nil; self.player = nil }
    }
}
