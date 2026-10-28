"""Runs in .venv-voice and stays running: reads one JSON per line {"text","voice","speed","out"} on stdin, writes a 24 kHz WAV to "out" and prints {"ok":true} (or {"error":...}).
Kokoro-82M through Apple MLX, from the local Hugging Face cache."""
import json
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
proto, sys.stdout = sys.stdout, sys.stderr   # libraries print to stdout; the reply channel stays separate
import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model

model = load_model("mlx-community/Kokoro-82M-bf16")
print(json.dumps({"ready": True}), file=proto, flush=True)
for line in sys.stdin:
    try:
        req = json.loads(line)
        voice = req.get("voice") or "af_heart"
        parts = [np.array(r.audio) for r in model.generate(text=req["text"], voice=voice, speed=float(req.get("speed", 1.0)), lang_code=voice[0])]
        sf.write(req["out"], np.concatenate(parts), 24000)
        print(json.dumps({"ok": True}), file=proto, flush=True)
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}), file=proto, flush=True)
