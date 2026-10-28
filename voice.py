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


_voices = None


def voices():
    """Installed macOS voices: [{name, lang}]. Only voices that are really on this Mac (Settings > Accessibility > Spoken Content adds more)."""
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
    """Text -> AAC (.m4a) bytes, made with the macOS voice. Returns (bytes, content_type)."""
    text = clean_for_speech(text)
    if not text:
        raise ValueError("Nothing to read aloud.")
    names = {v["name"] for v in voices()}
    with tempfile.TemporaryDirectory(prefix="say_") as d:
        aiff, m4a = Path(d) / "s.aiff", Path(d) / "s.m4a"
        cmd = ["say", "-o", str(aiff)]
        if voice in names:
            cmd += ["-v", voice]
        if rate:
            cmd += ["-r", str(max(80, min(int(rate), 400)))]
        subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=300)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(m4a)], check=True, timeout=120)
        return m4a.read_bytes(), "audio/mp4"
