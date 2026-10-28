"""surround: the music model of unplugged.ai (ACE-Step 1.5, MIT licence, https://github.com/ACE-Step/ACE-Step-1.5).

It writes a whole song as audio (with vocals when lyrics are given) from a text description. mono and stereo (the chat models)
never make sound; they turn a request into a caption and lyrics and hand them to surround.

ACE-Step lives in its own environment (vendor/ACE-Step-1.5, installed by setup_surround.sh). This module starts
surround_worker.py inside it on the first request, keeps it for a while so the next song starts fast, and stops it when idle
so the memory goes back to the chat and picture models.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
ACE = ROOT / "vendor/ACE-Step-1.5"
PY = ACE / ".venv/bin/python"
MARK = "@@SURROUND@@ "
IDLE_STOP = 15 * 60  # seconds without a request before the worker is stopped
LENGTH = {"short": 60, "medium": 120, "long": 180}  # seconds of song

_lock = threading.Lock()   # one song at a time
_state = {"proc": None, "last": 0.0, "ready": False, "token": None}


def ready():
    """True when ACE-Step and its weights are installed."""
    return PY.exists() and (ACE / "checkpoints/acestep-v15-turbo/model.safetensors").exists() and (ACE / "checkpoints/acestep-5Hz-lm-1.7B/model.safetensors").exists()


def busy():
    return _lock.locked()


def _stop():
    p = _state["proc"]
    _state.update(proc=None, ready=False)
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


def _start(progress):
    progress("Loading the surround music model (first song after a pause takes longer)")
    log = open(ROOT / "logs/surround.log", "ab")
    p = subprocess.Popen([str(PY), str(ROOT / "surround_worker.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
    _state.update(proc=p, ready=False)
    return p


def _read(p):
    """Next protocol message from the worker, or None when it exited."""
    for line in p.stdout:
        if line.startswith(MARK):
            return json.loads(line[len(MARK):])
    return None


class Cancelled(RuntimeError):
    pass


def cancel(token):
    """Stops the song with this token: a running one is interrupted by stopping the worker (it reloads for the next song)."""
    if _state["token"] == token and _state["proc"] and _state["proc"].poll() is None:
        _state["cancelled"] = token
        p = _state["proc"]
        p.terminate()


def compose(caption, lyrics, seconds, out_dir, seed=-1, progress=lambda m: None, token=None, cancelled=lambda: False):
    """Makes one song; returns {"path", "seconds", "seed"}. Raises RuntimeError with a readable message on failure."""
    if not ready():
        raise RuntimeError("The surround music model is not installed yet. Run ./setup_surround.sh and restart.")
    with _lock:
        if cancelled():
            raise Cancelled("Stopped")
        _state["token"] = token
        p = _state["proc"]
        if not p or p.poll() is not None:
            p = _start(progress)
        rid = str(time.time())
        while not _state["ready"]:
            m = _read(p)
            if m is None:
                _stop()
                if cancelled():
                    raise Cancelled("Stopped")
                raise RuntimeError("The surround music model stopped while loading. See logs/surround.log.")
            if m.get("event") == "error":
                _stop()
                raise RuntimeError(m.get("message", "surround failed to load"))
            if m.get("event") == "ready":
                _state["ready"] = True
        progress("Composing the song")
        p.stdin.write(json.dumps({"id": rid, "caption": caption, "lyrics": lyrics, "duration": seconds, "seed": seed, "out_dir": str(out_dir)}) + "\n")
        p.stdin.flush()
        while True:
            m = _read(p)
            if m is None:
                _stop()
                if cancelled():
                    raise Cancelled("Stopped")
                raise RuntimeError("The surround music model stopped while composing. See logs/surround.log.")
            if m.get("id") != rid:
                continue
            if m["event"] == "error":
                raise RuntimeError(m.get("message", "surround failed"))
            if m["event"] == "done":
                _state["last"] = time.time()
                _state["token"] = None
                return {"path": m["path"], "seconds": m["seconds"], "seed": m.get("seed")}


def _reaper():
    while True:
        time.sleep(60)
        if _state["proc"] and not _lock.locked() and time.time() - _state["last"] > IDLE_STOP:
            with _lock:
                _stop()


threading.Thread(target=_reaper, daemon=True).start()
