"""Accounts, sessions and per-user settings for unplugged.ai (all stored on this Mac, nothing leaves it).

Three kinds of visitors:
  * user  - has an account (password stored only as a salted scrypt hash); history and settings are saved.
  * guest - no account; everything lives in memory/temp files and is deleted when the session ends
            (browser closed -> no more heartbeats -> purged after GUEST_IDLE seconds, and always on server restart).
  * incognito chats are a per-chat option handled in chat.py (they work for users and guests).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).parent
UDIR = ROOT / "users"
UDIR.mkdir(exist_ok=True)
UFILE = UDIR / "users.json"
SFILE = UDIR / "sessions.json"
COOKIE = "jacobai_session"
GUEST_IDLE = 30 * 60
USER_SESSION_DAYS = 30
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")

lock = threading.RLock()
sessions: dict = {}      # token -> session dict (the "owner" passed around the server)
fails: dict = {}         # username -> (count, locked_until)
on_end = []              # callbacks(owner) run when a guest session is purged


class AuthError(ValueError):
    pass


def _read(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def _hash(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()


def _tok_id(token):
    return hashlib.sha256(token.encode()).hexdigest()


def users():
    return _read(UFILE, {})


def has_users():
    return bool(users())


def _new_session(uid, kind, name):
    token = secrets.token_urlsafe(32)
    s = {"token": token, "uid": uid, "kind": kind, "name": name, "last": time.time(), "settings": {}, "temp_files": set()}
    with lock:
        sessions[token] = s
        if kind == "user":
            store = _read(SFILE, {})
            store[_tok_id(token)] = {"uid": uid, "created": time.time()}
            _write(SFILE, store)
    return s


def cookie_header(s):
    base = f"{COOKIE}={s['token']}; Path=/; HttpOnly; SameSite=Strict"
    return base + (f"; Max-Age={USER_SESSION_DAYS * 86400}" if s["kind"] == "user" else "")  # guests: browser-session cookie


def clear_cookie_header():
    return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


# ---------- sign up / in / out
def register(name, password):
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise AuthError("Pick a username with 3 to 32 letters, numbers, dots, dashes or underscores.")
    if len(password or "") < 8:
        raise AuthError("Use a password with at least 8 characters.")
    uid = name.lower()
    with lock:
        us = users()
        if uid in us:
            raise AuthError("That username is taken.")
        salt = secrets.token_hex(16)
        first = not us
        us[uid] = {"name": name, "salt": salt, "hash": _hash(password, salt), "created": time.time()}
        _write(UFILE, us)
    (UDIR / uid).mkdir(exist_ok=True)
    return _new_session(uid, "user", name), first


IP_WINDOW, IP_MAX, IP_BLOCK = 15 * 60, 10, 15 * 60
ip_fails: dict = {}   # address -> [times of recent wrong passwords]
ip_blocked: dict = {}  # address -> blocked until


def login(name, password, ip="local"):
    """Per name: 5 wrong passwords lock it for 30 s. Per address: 10 wrong passwords in 15 minutes block that device for 15 minutes,
    whatever names it tries (stops guessing many accounts or many passwords from one place)."""
    uid = (name or "").strip().lower()
    now = time.time()
    with lock:
        if ip_blocked.get(ip, 0) > now:
            raise AuthError(f"Too many wrong passwords from this device. Try again in {int((ip_blocked[ip] - now) / 60) + 1} minutes.")
        cnt, until = fails.get(uid, (0, 0))
        if until > now:
            raise AuthError(f"Too many wrong passwords. Try again in {int(until - now) + 1} seconds.")
    u = users().get(uid)
    ok = bool(u) and hmac.compare_digest(_hash(password or "", u["salt"]), u["hash"])
    if not u:
        _hash(password or "", "00" * 16)  # keep timing similar
    if not ok:
        with lock:
            recent = [t for t in ip_fails.get(ip, []) if now - t < IP_WINDOW] + [now]
            ip_fails[ip] = recent
            if len(recent) >= IP_MAX:
                ip_blocked[ip] = now + IP_BLOCK
                ip_fails.pop(ip, None)
            cnt += 1
            fails[uid] = (cnt, now + 30 if cnt >= 5 else 0)
            if cnt >= 5:
                fails[uid] = (0, now + 30)
        raise AuthError("Wrong username or password.")
    with lock:
        fails.pop(uid, None)
    return _new_session(uid, "user", u["name"])


def guest():
    gid = "guest-" + secrets.token_hex(4)
    return _new_session(gid, "guest", "Guest")


def session_from_cookie(header):
    if not header:
        return None
    try:
        c = SimpleCookie(header)
        token = c[COOKIE].value
    except Exception:
        return None
    with lock:
        s = sessions.get(token)
        if s is None:
            rec = _read(SFILE, {}).get(_tok_id(token))
            u = users().get(rec["uid"]) if rec else None
            if not rec or not u or time.time() - rec["created"] > USER_SESSION_DAYS * 86400:
                return None
            s = {"token": token, "uid": rec["uid"], "kind": "user", "name": u["name"], "last": time.time(), "settings": {}, "temp_files": set()}
            sessions[token] = s
        s["last"] = time.time()
        return s


def logout(s):
    with lock:
        sessions.pop(s["token"], None)
        if s["kind"] == "user":
            store = _read(SFILE, {})
            store.pop(_tok_id(s["token"]), None)
            _write(SFILE, store)
    if s["kind"] == "guest":
        _purge(s)


def change_password(s, old, new):
    if s["kind"] != "user":
        raise AuthError("Guests have no password.")
    if len(new or "") < 6:
        raise AuthError("Use a password with at least 6 characters.")
    with lock:
        us = users()
        u = us[s["uid"]]
        if not hmac.compare_digest(_hash(old or "", u["salt"]), u["hash"]):
            raise AuthError("Your current password is wrong.")
        u["salt"] = secrets.token_hex(16)
        u["hash"] = _hash(new, u["salt"])
        _write(UFILE, us)


def _purge(s):
    for cb in on_end:
        try:
            cb(s)
        except Exception:
            pass


def _sweeper():
    while True:
        time.sleep(60)
        now = time.time()
        with lock:
            dead = [s for s in sessions.values() if s["kind"] == "guest" and now - s["last"] > GUEST_IDLE]
            for s in dead:
                sessions.pop(s["token"], None)
        for s in dead:
            _purge(s)


threading.Thread(target=_sweeper, daemon=True).start()


# ---------- per-user settings (view, form values, chat settings, ...)
def _spath(s):
    d = UDIR / s["uid"]
    d.mkdir(exist_ok=True)
    return d / "settings.json"


def settings_get(s):
    return s["settings"] if s["kind"] == "guest" else _read(_spath(s), {})


def settings_put(s, changes):
    if not isinstance(changes, dict):
        raise AuthError("bad settings")
    with lock:
        cur = dict(settings_get(s))
        for k, v in changes.items():
            if not re.match(r"^[A-Za-z0-9_\-]{1,60}$", k):
                continue
            if v is None:
                cur.pop(k, None)
            elif len(json.dumps(v)) < 4_000_000:
                cur[k] = v
        if s["kind"] == "guest":
            s["settings"] = cur
        else:
            _write(_spath(s), cur)
