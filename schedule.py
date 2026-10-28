"""Scheduled tasks: a prompt the model runs by itself at a set time (every day at HH:MM, or every N hours), optionally reading the text files in a
folder you choose. The result appears as a normal chat in your list. Tasks run only while the server is running (it starts at login).
Only signed-in accounts have tasks (guests do not); the model may use only safe tools there (code sandbox, documents, your library)."""
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import auth
import chat
import logbus

ROOT = Path(__file__).parent
DIR = ROOT / "schedules"
DIR.mkdir(exist_ok=True)
ID_RE = re.compile(r"^[a-f0-9]{8}$")
ALLOWED_TOOLS = {"run_python", "create_document", "search_documents", "search_past_chats", "list_music"}
MAX_FILES, MAX_CHARS = 25, 60000
TEXT_OK = {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html", ".css", ".yaml", ".yml", ".toml", ".pdf", ".docx", ".pptx", ".xlsx", ".tex", ".rst"}
_lock = threading.Lock()
_running = set()


def _file(uid):
    return DIR / f"{uid}.json"


def _load(uid):
    try:
        return json.loads(_file(uid).read_text())
    except Exception:
        return []


def _save(uid, items):
    _file(uid).write_text(json.dumps(items))


def next_run(when, after=None):
    """Next run time (epoch) for {"type":"daily","time":"08:00"} or {"type":"every","hours":N}."""
    after = after or time.time()
    if when.get("type") == "every":
        return after + max(1, min(float(when.get("hours", 24)), 24 * 30)) * 3600
    hh, mm = (int(x) for x in str(when.get("time", "08:00")).split(":")[:2])
    d = datetime.fromtimestamp(after).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if d.timestamp() <= after:
        d += timedelta(days=1)
    return d.timestamp()


def check_folder(path):
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise ValueError("That folder does not exist.")
    if p == ROOT or ROOT in p.parents:
        raise ValueError("Pick a folder outside the app's own folder.")
    return str(p)


def list_tasks(owner):
    return _load(owner["uid"])


def save(owner, body):
    if owner["kind"] != "user":
        raise ValueError("Sign in with an account to schedule tasks.")
    name = str(body.get("name") or "").strip()[:60]
    prompt = str(body.get("prompt") or "").strip()[:4000]
    if not name or not prompt:
        raise ValueError("Give the task a name and a prompt.")
    kind = body.get("type") if body.get("type") in ("daily", "every") else "daily"
    when = {"type": kind, "time": str(body.get("time") or "08:00"), "hours": float(body.get("hours") or 24)}
    if not re.match(r"^\d{1,2}:\d{2}$", when["time"]):
        raise ValueError("Time must look like 08:30.")
    folder = check_folder(body["folder"]) if str(body.get("folder") or "").strip() else ""
    items = _load(owner["uid"])
    t = next((x for x in items if x["id"] == body.get("id")), None) if body.get("id") else None
    if not t:
        if len(items) >= 20:
            raise ValueError("At most 20 tasks.")
        t = {"id": uuid.uuid4().hex[:8], "created": time.time(), "last_run": 0, "last_chat": None, "last_status": ""}
        items.append(t)
    t.update(name=name, prompt=prompt, when=when, folder=folder, model=body.get("model") or "gpt-oss:20b", enabled=bool(body.get("enabled", True)))
    t["next_run"] = next_run(when)
    _save(owner["uid"], items)
    return t


def delete(owner, tid):
    if not ID_RE.match(tid or ""):
        raise ValueError("bad id")
    _save(owner["uid"], [t for t in _load(owner["uid"]) if t["id"] != tid])


def _read_folder(folder):
    """Text of the newest readable files in the folder (not subfolders): a block for the prompt."""
    files = sorted((f for f in Path(folder).iterdir() if f.is_file() and f.suffix.lower() in TEXT_OK and not f.name.startswith(".")), key=lambda f: f.stat().st_mtime, reverse=True)[:MAX_FILES]
    parts, total = [], 0
    for f in files:
        try:
            if f.stat().st_size > chat.MAX_FILE_BYTES:
                continue
            kind, text, _ = chat.extract_text(f.name, f.read_bytes())
            text = text.strip()
            if not text:
                continue
            text = text[:max(500, (MAX_CHARS - total) // 2)]
            parts.append(f"=== {f.name} (changed {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d %H:%M}) ===\n{text}")
            total += len(text)
            if total >= MAX_CHARS:
                break
        except Exception:
            continue
    return "\n\n".join(parts) if parts else "(The folder has no readable text files.)"


def run_task(uid, tid, manual=False):
    """Runs one task now; the answer becomes a chat. Returns the chat id."""
    u = auth.users().get(uid)
    if not u:
        raise ValueError("account not found")
    items = _load(uid)
    t = next((x for x in items if x["id"] == tid), None)
    if not t:
        raise ValueError("task not found")
    owner = {"uid": uid, "kind": "user", "name": u["name"], "last": time.time(), "settings": {}, "temp_files": set()}
    text = t["prompt"]
    if t.get("folder"):
        try:
            text += f"\n\nFiles in the folder {t['folder']}:\n\n" + _read_folder(t["folder"])
        except Exception as e:
            text += f"\n\n(The folder could not be read: {e})"
    t["model"] = {m["label"]: m["name"] for m in chat.models()}.get(t["model"], t["model"])
    c = chat.new_chat(owner, t["model"])
    c["title"] = f"{t['name']} - {datetime.now():%d %b %H:%M}"
    c["scheduled"] = tid
    chat.save(owner, c)
    logbus.log("task", f"running '{t['name']}'", uid)
    status, errors = "ok", []
    try:
        chat.stream_turn({"id": c["id"], "content": text, "model": t["model"], "think": "low", "tools": True, "memory": True, "web": False, "tool_allow": sorted(ALLOWED_TOOLS)},
                         lambda ev: errors.append(ev.get("message", "")) if ev.get("type") == "error" else None, owner)
        if errors:
            status = "failed: " + errors[0][:200]
    except Exception as e:
        status = f"failed: {type(e).__name__}: {e}"
    with _lock:
        items = _load(uid)
        for x in items:
            if x["id"] == tid:
                x.update(last_run=time.time(), last_chat=c["id"], last_status=status)
                x["next_run"] = next_run(x["when"])
        _save(uid, items)
    logbus.log("task", f"'{t['name']}' {status}", uid)
    return c["id"]


def run_now(owner, tid):
    """Starts a task in the background (the browser need not wait)."""
    if not any(t["id"] == tid for t in _load(owner["uid"])):
        raise ValueError("task not found")
    if (owner["uid"], tid) in _running:
        raise ValueError("That task is already running.")
    _running.add((owner["uid"], tid))

    def go():
        try:
            run_task(owner["uid"], tid, True)
        finally:
            _running.discard((owner["uid"], tid))
    threading.Thread(target=go, daemon=True).start()


def running(owner):
    return [tid for uid, tid in _running if uid == owner["uid"]]


def _loop():
    while True:
        time.sleep(30)
        try:
            now = time.time()
            for f in DIR.glob("*.json"):
                uid = f.stem
                for t in _load(uid):
                    if t.get("enabled") and t.get("next_run", 1e18) <= now and (uid, t["id"]) not in _running:
                        _running.add((uid, t["id"]))
                        try:
                            run_task(uid, t["id"])
                        finally:
                            _running.discard((uid, t["id"]))
        except Exception as e:
            logbus.log("task", f"scheduler error: {type(e).__name__}: {e}", None)


def start():
    threading.Thread(target=_loop, daemon=True).start()
