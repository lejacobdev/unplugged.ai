"""Projects: a named workspace with its own instructions and its own documents. Chats can belong to a project; the model then
follows the project's instructions and searches the project's documents (plus the documents you added outside any project).
Accounts keep projects on disk (projects/<uid>.json); guests keep them in memory only."""
import json
import re
import threading
import time
import uuid
from pathlib import Path

DIR = Path(__file__).parent / "projects"
DIR.mkdir(exist_ok=True)
_g: dict = {}
_lock = threading.Lock()
ID_RE = re.compile(r"^[a-f0-9]{8}$")
MAX = 50


def _load(owner):
    if owner["kind"] == "guest":
        return _g.setdefault(owner["uid"], [])
    try:
        return json.loads((DIR / f"{owner['uid']}.json").read_text())
    except Exception:
        return []


def _save(owner, items):
    if owner["kind"] == "guest":
        _g[owner["uid"]] = items
    else:
        (DIR / f"{owner['uid']}.json").write_text(json.dumps(items))


def list_projects(owner):
    return sorted(_load(owner), key=lambda p: p["name"].lower())


def get(owner, pid):
    return next((p for p in _load(owner) if p["id"] == pid), None) if pid else None


def save(owner, pid, name, instructions):
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("Give the project a name.")
    instructions = (instructions or "").strip()[:4000]
    with _lock:
        items = _load(owner)
        p = next((x for x in items if x["id"] == pid), None) if pid else None
        if p:
            p["name"], p["instructions"] = name, instructions
        else:
            if len(items) >= MAX:
                raise ValueError(f"At most {MAX} projects.")
            p = {"id": uuid.uuid4().hex[:8], "name": name, "instructions": instructions, "created": time.time()}
            items.append(p)
        _save(owner, items)
    return p


def delete(owner, pid):
    if not ID_RE.match(pid or ""):
        raise ValueError("bad project id")
    with _lock:
        _save(owner, [p for p in _load(owner) if p["id"] != pid])


def prompt_block(owner, pid):
    p = get(owner, pid)
    if not p:
        return ""
    return (f"\n\nThis chat belongs to the project \"{p['name']}\"." +
            (f" Follow the project's instructions in every answer:\n{p['instructions']}" if p["instructions"] else ""))


def purge_owner(owner):
    _g.pop(owner["uid"], None)
