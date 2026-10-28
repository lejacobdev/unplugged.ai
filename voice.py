"""Voice: speech to text with Whisper (local, via mlx-whisper in .venv-voice) and text to speech with the macOS voices (`say`).
Needs ffmpeg for audio conversion (brew install ffmpeg). Everything runs on this Mac."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).parent
PY = ROOT / ".venv-voice" / "bin" / "python"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".oga", ".opus", ".flac", ".webm", ".mp4", ".mov", ".m4v", ".aiff", ".caf", ".3gp"}
MAX_SECONDS = 4 * 3600
_lock = threading.Lock()   # one transcription at a time (the model is large)


def available():
    return PY.exists() and Path(FFMPEG).exists()


def transcribe(data, suffix=".webm"):
    """Audio or video bytes -> {"text", "language"}."""
    if not PY.exists():
        raise RuntimeError("Speech recognition is not set up. See the README (extras).")
    if not Path(FFMPEG).exists():
        raise RuntimeError("ffmpeg is missing. Run: brew install ffmpeg")
    with tempfile.TemporaryDirectory(prefix="voice_") as d:
        src, wav = Path(d) / ("in" + (suffix if suffix in AUDIO_EXT else ".bin")), Path(d) / "a.wav"
        src.write_bytes(data)
        p = subprocess.run([FFMPEG, "-nostdin", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-t", str(MAX_SECONDS), str(wav)], capture_output=True, timeout=600)
        if p.returncode != 0 or not wav.exists():
            raise ValueError("That audio could not be read.")
        with _lock:
            r = subprocess.run([str(PY), str(ROOT / "voice_worker.py"), str(wav)], capture_output=True, timeout=7200,
                               env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
        if r.returncode != 0:
            raise RuntimeError("Speech recognition failed: " + r.stderr.decode("utf-8", "replace")[-300:])
        line = [l for l in r.stdout.decode("utf-8", "replace").splitlines() if l.startswith("{")][-1]
        return json.loads(line)


KOKORO = [("af_heart", "Heart (US, female)"), ("af_bella", "Bella (US, female)"), ("af_nicole", "Nicole (US, female)"), ("af_sarah", "Sarah (US, female)"),
          ("af_sky", "Sky (US, female)"), ("am_michael", "Michael (US, male)"), ("am_adam", "Adam (US, male)"), ("am_fenrir", "Fenrir (US, male)"),
          ("am_puck", "Puck (US, male)"), ("bf_emma", "Emma (UK, female)"), ("bf_isabella", "Isabella (UK, female)"),
          ("bm_george", "George (UK, male)"), ("bm_lewis", "Lewis (UK, male)")]
KOKORO_IDS = {k for k, _ in KOKORO}
_tts = {"proc": None, "last": 0.0}
_tts_lock = threading.Lock()


def natural_available():
    """Kokoro installed and downloaded (setup_extras.sh voice)."""
    if not (ROOT / ".venv-voice/lib").exists() or not list((ROOT / ".venv-voice/lib").glob("python*/site-packages/mlx_audio")):
        return False
    return any((Path.home() / ".cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16").glob("snapshots/*/*.safetensors"))


def _tts_proc():
    p = _tts["proc"]
    if p and p.poll() is None:
        return p
    p = subprocess.Popen([str(PY), str(ROOT / "tts_worker.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                         env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
    for _ in range(40):   # skip any stray output until the ready line
        ln = p.stdout.readline()
        if not ln:
            raise RuntimeError("The natural voice could not start.")
        if '"ready"' in ln:
            break
    _tts["proc"] = p
    threading.Thread(target=_tts_reaper, daemon=True).start()
    return p


def _tts_reaper():
    """Gives the memory back after 10 idle minutes."""
    import time
    while True:
        time.sleep(30)
        p = _tts["proc"]
        if not p or p.poll() is not None:
            return
        if time.time() - _tts["last"] > 600 and _tts_lock.acquire(blocking=False):
            try:
                p.terminate(); _tts["proc"] = None
            finally:
                _tts_lock.release()
            return


def _speak_natural(text, voice, rate, out_wav):
    import time
    speed = max(0.6, min(float(rate) / 175.0, 1.6)) if rate else 1.0
    with _tts_lock:
        p = _tts_proc()
        p.stdin.write(json.dumps({"text": text, "voice": voice, "speed": speed, "out": str(out_wav)}) + "\n"); p.stdin.flush()
        ln = p.stdout.readline()
        while ln and not ln.startswith("{"):
            ln = p.stdout.readline()
        reply = json.loads(ln or '{"error": "the voice stopped"}')
        _tts["last"] = time.time()
    if reply.get("error"):
        raise RuntimeError(reply["error"])


_voices = None


def voices():
    """Installed macOS voices: [{name, lang}]. Only voices that are really on this Mac (Settings > Accessibility > Spoken Content adds more)."""
    global _voices
    if natural_available():
        return [{"name": k, "label": l, "lang": "en", "natural": True} for k, l in KOKORO] + [{"name": v["name"], "label": v["name"] + " (macOS, basic)", "lang": v["lang"]} for v in _mac_voices()]
    return [{"name": v["name"], "label": v["name"] + " (macOS)", "lang": v["lang"]} for v in _mac_voices()]


def _mac_voices():
    global _voices
    if _voices is None:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        _voices = []
        for ln in out.splitlines():
            m = re.match(r"^(.+?)\s{2,}([a-z]{2,3}_[A-Za-z0-9]+)\s+#", ln)
            if m:
                _voices.append({"name": m.group(1).strip(), "lang": m.group(2)})
    return _voices


def clean_for_speech(text):
    t = re.sub(r"```.*?```", " (code block) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*_#>|]+", " ", t)
    t = re.sub(r"^\s*[-+]\s+", "", t, flags=re.M)
    return re.sub(r"\s+\n", "\n", t).strip()[:6000]


def speak(text, voice=None, rate=None):
    """Text -> AAC (.m4a) bytes. Uses the natural neural voice (Kokoro) when installed and the text is English; otherwise a macOS voice."""
    text = clean_for_speech(text)
    if not text:
        raise ValueError("Nothing to read aloud.")
    latin = sum(c.isascii() and c.isalpha() for c in text) / max(1, sum(c.isalpha() for c in text)) > 0.9
    use_natural = natural_available() and latin and (voice in KOKORO_IDS or voice in (None, ""))
    mac_names = {v["name"] for v in _mac_voices()}
    with tempfile.TemporaryDirectory(prefix="say_") as d:
        m4a = Path(d) / "s.m4a"
        if use_natural:
            wav = Path(d) / "s.wav"
            _speak_natural(text, voice or "af_heart", rate, wav)
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(wav), str(m4a)], check=True, timeout=120)
        else:
            aiff = Path(d) / "s.aiff"
            cmd = ["say", "-o", str(aiff)]
            if voice in mac_names:
                cmd += ["-v", voice]
            if rate:
                cmd += ["-r", str(max(80, min(int(rate), 400)))]
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=300)
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(m4a)], check=True, timeout=120)
        return m4a.read_bytes(), "audio/mp4"
