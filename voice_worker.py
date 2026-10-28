"""Runs in .venv-voice: python voice_worker.py AUDIO.wav  ->  prints one JSON line {"text": ..., "language": ...}.
Whisper large-v3-turbo through Apple MLX, from the local Hugging Face cache (no internet)."""
import json
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
import mlx_whisper

res = mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo="mlx-community/whisper-large-v3-turbo", verbose=None)
print(json.dumps({"text": res["text"].strip(), "language": res.get("language", "")}))
