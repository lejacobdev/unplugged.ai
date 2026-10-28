"""API keys for the OpenAI-compatible endpoint (/v1). A key belongs to one account. Only a hash of it is stored, so the key is shown once, when it is made."""
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path

FILE = Path(__file__).parent / "apikeys.json"
_lock = threading.Lock()


def _h(key):
    return hashlib.sha256(key.encode()).hexdigest()


def _load():
    try:
        return json.loads(FILE.read_text())
    except Exception:
        return {}


def _save(d):
    FILE.write_text(json.dumps(d))
    FILE.chmod(0o600)


def create(uid, name):
    name = (name or "").strip()[:60] or "API key"
    key = "sk-unplugged-" + secrets.token_hex(24)
    with _lock:
        d = _load()
        if sum(1 for v in d.values() if v["uid"] == uid) >= 20:
            raise ValueError("At most 20 keys. Revoke one first.")
        d[_h(key)] = {"uid": uid, "name": name, "prefix": key[:18], "created": time.time(), "last_used": 0, "id": secrets.token_hex(4)}
        _save(d)
    return key


def list_keys(uid):
    return sorted(({k: v[k] for k in ("id", "name", "prefix", "created", "last_used")} for v in _load().values() if v["uid"] == uid), key=lambda v: v["created"])


def revoke(uid, kid):
    with _lock:
        d = _load()
        _save({h: v for h, v in d.items() if not (v["uid"] == uid and v["id"] == kid)})


def lookup(key):
    """The uid a key belongs to (and note the use), or None."""
    h = _h(key or "")
    d = _load()
    v = d.get(h)
    if not v:
        return None
    if time.time() - v["last_used"] > 60:
        with _lock:
            d = _load()
            if h in d:
                d[h]["last_used"] = time.time()
                _save(d)
    return v["uid"]
