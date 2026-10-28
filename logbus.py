"""In-memory log shared by the dashboard; the Console tab and the Pictures tab read it.
Lines with an owner are only shown to that account (owner None = system lines everyone may see)."""
import threading
import time
from collections import deque

_lock = threading.Lock()
_lines = deque(maxlen=3000)
_next_id = 1


def log(src: str, text: str, owner=None):
    """src: img | music | chat | system. owner: account id or None."""
    global _next_id
    text = str(text).rstrip()
    if not text:
        return
    with _lock:
        for part in text.splitlines():
            _lines.append({"id": _next_id, "t": time.time(), "src": src, "text": part[:600], "owner": owner})
            _next_id += 1


def since(last_id: int, owner=None, limit: int = 500):
    with _lock:
        out = [{k: v for k, v in l.items() if k != "owner"} for l in _lines if l["id"] > last_id and l["owner"] in (None, owner)][-limit:]
        return {"lines": out, "last": out[-1]["id"] if out else last_id}


def purge(owner):
    with _lock:
        keep = [l for l in _lines if l["owner"] != owner]
        _lines.clear()
        _lines.extend(keep)
