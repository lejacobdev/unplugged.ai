"""unplugged.ai server: chat, music (surround) and picture editing, all on this Mac.

    .venv/bin/python server.py          then open http://127.0.0.1:8000

Everything runs on this Mac; the server only listens on localhost.
"""
import json
import os
import random
import re
import socket
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


import auth
import chat
import library
import imgedit
import logbus
import surround

ROOT = Path(__file__).parent

MINE = ROOT / "dashboard_samples"   # songs made by surround: <name>.wav + <name>.json (owner, caption, lyrics, ...)
WEB = ROOT / "web"
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
MINE.mkdir(exist_ok=True)
jobs = {}


def _meta(p: Path):
    mp = p.with_suffix(".json")
    try:
        return json.loads(mp.read_text()) if mp.exists() else {}
    except Exception:
        return {}


def resolve(sample_id: str, owner=None) -> Path:
    kind, _, name = sample_id.partition("/")
    if kind != "mine" or not NAME_RE.match(name):
        raise ValueError("bad sample id")
    p = MINE / f"{name}.wav"
    if not p.exists() or (owner is not None and _meta(p).get("owner") != owner["uid"]):
        raise FileNotFoundError(sample_id)
    return p


def list_samples(owner):
    out = []
    for p in sorted(MINE.glob("*.wav"), key=lambda q: q.stat().st_mtime, reverse=True):
        meta = _meta(p)
        if meta.get("owner") != owner["uid"]:
            continue
        meta.pop("owner", None)
        out.append({"id": f"mine/{p.stem}", "name": p.stem, "kind": "mine", "created": p.stat().st_mtime, **meta})
    return out


def run_job(job_id, p):
    """Background: asks surround for one song. mono/stereo already wrote the caption and lyrics."""
    job = jobs[job_id]
    owner = p["owner"]
    try:
        eph = bool(p.get("ephemeral")) or owner["kind"] == "guest"
        name = ("tmp_" if eph else "") + time.strftime("song_%m%d_%H%M%S") + "_" + job_id
        if eph:
            owner["temp_files"].add("m:" + name)
        seconds = surround.LENGTH.get(p["length"], 120)
        logbus.log("music", owner=owner["uid"], text=f"surround: composing about {seconds} s ({'with lyrics' if p['lyrics'].strip() else 'instrumental'}): {p['caption'][:120]}")
        job["message"] = "Waiting for the music model" if surround.busy() else "Starting the music model"
        t = time.time()
        got = surround.compose(p["caption"], p["lyrics"], seconds, MINE / ".work", progress=lambda m: job.update(message=m), token=job_id, cancelled=lambda: bool(job.get("cancel")))
        os.replace(got["path"], MINE / f"{name}.wav")
        meta = {"caption": p["caption"], "lyrics": p["lyrics"], "length": p["length"], "seconds": seconds, "made_in": round(time.time() - t), "seed": got.get("seed"), "owner": owner["uid"]}
        (MINE / f"{name}.json").write_text(json.dumps(meta))
        job["results"].append(f"mine/{name}")
        logbus.log("music", owner=owner["uid"], text=f"saved {name}.wav (took {meta['made_in']} s)")
        job["status"] = "done"
        job["message"] = "Done"
    except surround.Cancelled:
        job["status"] = "cancelled"
        job["message"] = "Stopped"
        logbus.log("music", owner=owner["uid"], text="song stopped by the user")
    except Exception as e:
        job["status"] = "error"
        job["message"] = f"{type(e).__name__}: {e}"
        logbus.log("music", owner=owner["uid"], text="surround failed: " + job["message"])


def start_music(owner, ephemeral, caption, lyrics="", length="medium"):
    """Starts a background song job. Returns the job id."""
    caption = (caption or "").strip()[:500]
    if not caption:
        raise ValueError("Describe the music you want first.")
    p = {"owner": owner, "ephemeral": bool(ephemeral), "caption": caption, "lyrics": (lyrics or "").strip()[:4000],
         "length": length if length in surround.LENGTH else "medium"}
    jid = uuid.uuid4().hex[:8]
    jobs[jid] = {"status": "running", "owner": owner["uid"], "message": "Starting the music model", "results": [], "count": 1, "started": time.time()}
    threading.Thread(target=run_job, args=(jid, p), daemon=True).start()
    return jid


def tool_generate_music(args, chat_obj, owner):
    """Does not start anything: shows the user an editable draft (caption + lyrics) in the chat; the song starts when they press Generate."""
    caption = (args.get("caption") or args.get("style") or "").strip()
    if not caption:
        return "No caption was given. Call generate_music again with a caption describing the sound of the song.", None
    length = args.get("length") if args.get("length") in surround.LENGTH else "medium"
    return ("The caption and lyrics are now shown to the user in the chat as an editable draft. Nothing has been generated yet: the user reviews or edits them and presses Generate song. "
            "Tell the user briefly that the draft is ready to review. Do not describe how it will sound."), {"kind": "music_draft", "caption": caption[:500], "lyrics": (args.get("lyrics") or "")[:4000], "length": length}


def tool_edit_picture(args, chat_obj, owner):
    if not imgedit.status()["ready"]:
        return "The offline image model is not installed yet. Tell the user to run setup_image_model.sh (see the Pictures tab).", None
    name = next((m["images"][-1] for m in reversed(chat_obj["messages"]) if m.get("images")), None)
    if not name:
        return "No picture is attached to this chat. Ask the user to drag a picture into the chat (or use the paperclip).", None
    import base64 as b64
    data = "data:image/png;base64," + b64.b64encode(imgedit.image_path(name).read_bytes()).decode()
    said = next((m["content"].strip() for m in reversed(chat_obj["messages"]) if m["role"] == "user"), "")
    instruction = (args.get("instruction") or "").strip() or (said if said != "(picture attached)" else "")
    if not instruction:
        return "No instruction was given. Ask the user what they want changed in the picture.", None
    ask = next((m["content"].lower() for m in reversed(chat_obj["messages"]) if m["role"] == "user"), "")
    if re.search(r"highest|maximum|max settings|max quality|best (quality|settings)|ultra|as good as possible", ask):
        quality, size, why = "maximum", 1536, "you asked for the highest settings"
    elif re.search(r"\b(quick|fast|draft|low quality|lowest|standard quality)\b", ask):
        quality, size, why = "standard", 768, "you asked for a fast result"
    elif re.search(r"high quality|high settings", ask):
        quality, size, why = "high", 1024, "you asked for high quality"
    else:
        quality, size, why = imgedit.auto_quality(imgedit.image_path(name), instruction)
        why = "chosen automatically: " + why
    if not chat_obj.get("incognito"):
        logbus.log("chat", f"edit_picture settings: {quality}, {size}px ({why})", owner["uid"])
    job = imgedit.start_edit({"image": data, "prompt": instruction, "quality": quality,
                              "preserve": True, "max_side": size, "guidance": 2.5, "variations": 1,
                              "owner": owner, "ephemeral": bool(chat_obj.get("incognito"))})
    return f"Started editing the picture (job {job}) with {quality} quality at {size} px ({why}). Mention this briefly to the user. A live progress card with the current picture is now shown in the chat and the result appears there when finished (a few minutes). Tell the user briefly what you are changing; do not call the tool again for the same request.", {"kind": "image_job", "job": job, "note": f"{quality} quality, {size} px"}


def tool_list_music(args, chat_obj, owner):
    items = list_samples(owner)
    return json.dumps([{"id": s["id"], "seconds": s.get("seconds"), "caption": s.get("caption", "")[:120]} for s in items][:20]), None


def tool_search_documents(args, chat_obj, owner):
    hits = library.search(owner, args.get("query", ""))
    if not hits:
        return "The user's library has no passages for that. Say so; do not guess.", None
    return "Passages from the user's documents (best first):\n\n" + "\n\n".join(f"[{h['name']}, passage {h['passage']}, relevance {h['score']}]\n{h['text']}" for h in hits), None


chat.LIB_COUNT = library.count
chat.LIB_PROMPT = library.prompt_block
chat.TOOL_IMPL.update({"search_documents": tool_search_documents})
chat.TOOL_IMPL.update({"generate_music": tool_generate_music, "edit_picture": tool_edit_picture, "list_music": tool_list_music})


def purge_guest(owner):
    """A guest session ended: delete everything it created."""
    chat.purge_owner(owner)
    library.purge_owner(owner)
    imgedit.purge_owner(owner)
    logbus.purge(owner["uid"])
    for t in list(owner.get("temp_files", [])):
        if t.startswith("m:"):
            for f in MINE.glob(t[2:] + "*"):
                f.unlink(missing_ok=True)


auth.on_end.append(purge_guest)
for _f in ([] if os.environ.get("JACOBAI_NOSWEEP") == "1" else MINE.glob("tmp_*")):
    _f.unlink(missing_ok=True)
if os.environ.get("JACOBAI_NOSWEEP") != "1":
    imgedit.sweep_temp()


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def claim_legacy(uid):
    """The first account adopts everything created before accounts existed."""
    for f in ROOT.glob("chats/*.json"):
        (ROOT / "chats" / uid).mkdir(exist_ok=True)
        f.rename(ROOT / "chats" / uid / f.name)
    for f in imgedit.DIR.glob("*.json"):
        try:
            m = json.loads(f.read_text())
            if "owner" not in m:
                m["owner"] = uid
                f.write_text(json.dumps(m))
        except Exception:
            pass
    for f in MINE.glob("*.json"):
        try:
            m = json.loads(f.read_text())
            if "owner" not in m:
                m["owner"] = uid
                f.write_text(json.dumps(m))
        except Exception:
            pass
    d = imgedit.LORA_DIR / uid
    d.mkdir(exist_ok=True)
    for f in list(imgedit.LORA_DIR.glob("*.safetensors")) + list(imgedit.LORA_DIR.glob("registry.json")):
        f.rename(d / f.name)


class Handler(BaseHTTPRequestHandler):
    owner = None
    tls = False

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None, cookies=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.owner is not None and self.owner["kind"] == "user" and self.path.split("?")[0] in CACHEABLE:
            self.send_header("X-Cache-OK", "1")  # lets the phone keep this for offline use (never guests)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        for c in cookies:
            self.send_header("Set-Cookie", c + ("; Secure" if self.tls and "Max-Age=0" not in c else ""))
        self.end_headers()
        self.wfile.write(body)

    # ---------- helpers
    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def body_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def same_origin(self):
        o = self.headers.get("Origin")
        return not o or urlparse(o).netloc == self.headers.get("Host")

    def need_login(self):
        self.owner = auth.session_from_cookie(self.headers.get("Cookie"))
        if self.owner is None:
            self.send(401, {"error": "Please sign in."})
            return False
        return True

    def me(self):
        o = self.owner
        return {"uid": o["uid"], "name": o["name"], "kind": o["kind"], "settings": auth.settings_get(o)}

    def page(self):
        o = auth.session_from_cookie(self.headers.get("Cookie"))
        if o is None:
            html = (WEB / "login.html").read_text()
            info = {"first": not auth.has_users(), "local": self.is_local()}
            return self.send(200, html.replace("/*INFO*/", "window.INFO=" + json.dumps(info) + ";"), "text/html; charset=utf-8")
        chat.end_incognito(o)  # incognito chats never survive a page load
        self.owner = o
        ip = lan_ip()
        lan = None
        if LAN and ip:
            lan = f"https://{HOSTNAME}.local:{TLS_PORT}" if TLS else f"http://{ip}:{PORT}"
        me = {**self.me(), "lan": lan, "tls": TLS, "caurl": f"http://{ip}:{PORT}/ca.pem" if TLS and ip else None, "local": self.is_local()}
        html = (WEB / "index.html").read_text().replace("/*ME*/", "window.ME=" + json.dumps(me).replace("</", "<\\/") + ";")
        return self.send(200, html, "text/html; charset=utf-8")

    # ---------- GET
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self.page()
            if u.path == "/sw.js":
                return self.send(200, (WEB / "sw.js").read_bytes(), "text/javascript; charset=utf-8", {"Service-Worker-Allowed": "/"})
            if u.path in ("/manifest.webmanifest", "/offline.html"):
                ctype = "application/manifest+json" if u.path.endswith("webmanifest") else "text/html; charset=utf-8"
                return self.send(200, (WEB / u.path[1:]).read_bytes(), ctype)
            if u.path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico"):  # iOS and browsers ask for these at the root when the page's link is not used
                return self.send(200, (WEB / "icons" / ("favicon.png" if u.path == "/favicon.ico" else "apple-touch-icon.png")).read_bytes(), "image/png")
            if u.path.startswith("/icons/") and re.match(r"^[A-Za-z0-9_\-]+\.png$", u.path[7:]):
                return self.send(200, (WEB / "icons" / u.path[7:]).read_bytes(), "image/png")
            if u.path == "/ca.pem":  # public part of the local certificate authority, to trust on your phone
                f = ROOT / "certs/ca.pem"
                if not f.exists():
                    return self.send(404, {"error": "HTTPS is not set up. Run ./setup_https.sh"})
                return self.send(200, f.read_bytes(), "application/x-x509-ca-cert", {"Content-Disposition": 'attachment; filename="unplugged.ai-local-CA.pem"'})
            if u.path.startswith("/static/") and re.match(r"^[A-Za-z0-9_\-]+\.(js|css)$", u.path[8:]):
                f = WEB / u.path[8:]
                return self.send(200, f.read_bytes(), "text/javascript; charset=utf-8" if f.suffix == ".js" else "text/css; charset=utf-8")
            if not self.need_login():
                return
            o = self.owner
            if u.path == "/api/me":
                return self.send(200, self.me())
            if u.path == "/api/console":
                return self.send(200, logbus.since(int(q.get("since", 0)), o["uid"]))
            if u.path == "/api/chat/status":
                return self.send(200, chat.status())
            if u.path == "/api/memory":
                return self.send(200, {"items": chat.mem_load(o)})
            if u.path == "/api/library":
                return self.send(200, {"items": library.list_docs(o), "vision": chat.vision_model(), "embed": library.EMBED_MODEL})
            if u.path == "/api/chat/list":
                return self.send(200, chat.list_chats(o))
            if u.path == "/api/chat/get":
                return self.send(200, chat.load(o, q.get("id")))
            if u.path == "/api/active":
                return self.send(200, {"music": [k for k, j in jobs.items() if j.get("status") == "running" and j.get("owner") == o["uid"]],
                                       "img": [k for k, j in imgedit.jobs.items() if j.get("status") in ("running", "queued") and j.get("owner") == o["uid"]]})
            if u.path == "/api/img/loras":
                return self.send(200, {"loras": imgedit.lora_list(o)})
            if u.path == "/api/img/status":
                return self.send(200, imgedit.status())
            if u.path == "/api/img/history":
                return self.send(200, imgedit.history(o))
            if u.path == "/api/img/job":
                j = imgedit.job_for(o, q.get("id"))
                return self.send(200, {k: v for k, v in j.items() if k != "owner"} if j else {"status": "error", "message": "unknown job"})
            if u.path.startswith("/img/"):
                path = imgedit.image_path(u.path[5:])
                extra = {"Content-Disposition": f'attachment; filename="{path.name}"'} if q.get("download") else None
                return self.send(200, path.read_bytes(), "image/png" if path.suffix == ".png" else "image/jpeg", extra)
            if u.path == "/api/samples":
                return self.send(200, list_samples(o))
            if u.path == "/api/job":
                j = jobs.get(q.get("id"))
                return self.send(200, {k: v for k, v in j.items() if k != "owner"} if j and j.get("owner") == o["uid"] else {"status": "error", "message": "unknown job", "results": []})
            if u.path == "/audio":
                path = resolve(q["id"], o)
                extra = {"Content-Disposition": f'attachment; filename="{path.stem}.wav"'} if q.get("download") else {}
                return self.send_audio(path, extra)
            if u.path == "/api/info":
                return self.send(200, {"music_model": "surround (ACE-Step 1.5)", "music_ready": surround.ready()})
            return self.send(404, {"error": "not found"})
        except (KeyError, ValueError, FileNotFoundError) as e:
            return self.send(400, {"error": str(e)})

    # ---------- POST
    def do_POST(self):
        path = urlparse(self.path).path
        if not self.same_origin():
            return self.send(403, {"error": "cross-site request blocked"})
        if path.startswith("/api/auth/"):
            return self.auth_post(path)
        if not self.need_login():
            return
        o = self.owner
        if path == "/api/me/settings":
            try:
                auth.settings_put(o, self.body_json())
                return self.send(200, {"ok": True})
            except Exception as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/img/edit":
            try:
                body = self.body_json()
                body["owner"] = o
                return self.send(200, {"job": imgedit.start_edit(body)})
            except Exception as e:
                return self.send(400, {"error": f"{type(e).__name__}: {e}"})
        if path == "/api/img/lora/upload":
            try:
                q = parse_qs(urlparse(self.path).query)
                name = imgedit.lora_save_stream(o, q.get("name", [""])[0], int(self.headers.get("Content-Length", 0)), self.rfile)
                return self.send(200, {"name": name, "loras": imgedit.lora_list(o)})
            except Exception as e:
                return self.send(400, {"error": f"{type(e).__name__}: {e}"})
        if path == "/api/img/lora/set":
            try:
                b = self.body_json()
                imgedit.lora_set(o, b.get("name"), b.get("active"), b.get("scale"))
                return self.send(200, {"loras": imgedit.lora_list(o)})
            except Exception as e:
                return self.send(400, {"error": f"{type(e).__name__}: {e}"})
        if path == "/api/img/cancel":
            imgedit.cancel(o, parse_qs(urlparse(self.path).query).get("id", [""])[0])
            return self.send(200, {"ok": True})
        if path.startswith("/api/chat/") or path in ("/api/memory", "/api/library", "/api/library/search"):
            return self.chat_post(path)
        if path == "/api/music/prompt":
            try:
                b = self.body_json()
                text = (b.get("prompt") or "").strip()
                if not text:
                    return self.send(400, {"error": "Describe the music you want first."})
                plan = chat.plan_music(b.get("model") or "gpt-oss:20b", text, bool(b.get("instrumental")))
                return self.send(200, {"plan": plan})  # review first: nothing is generated until /api/music/make
            except Exception as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/music/field":
            try:
                b = self.body_json()
                if b.get("field") not in ("caption", "lyrics", "idea"):
                    return self.send(400, {"error": "unknown field"})
                return self.send(200, {"text": chat.write_field(b.get("model") or "gpt-oss:20b", b["field"], b.get("prompt", ""), str(b.get("caption", "")), str(b.get("lyrics", "")), bool(b.get("instrumental")))})
            except Exception as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/music/random":
            try:
                return self.send(200, {"plan": chat.random_music(self.body_json().get("model") or "gpt-oss:20b")})
            except Exception as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/music/cancel":
            j = jobs.get(parse_qs(urlparse(self.path).query).get("id", [""])[0])
            if j and j.get("owner") == o["uid"] and j.get("status") == "running":
                j["cancel"] = True
                surround.cancel(next(k for k, x in jobs.items() if x is j))
            return self.send(200, {"ok": True})
        if path == "/api/music/make":
            try:
                b = self.body_json()
                return self.send(200, {"job": start_music(o, bool(b.get("incognito")), b.get("caption"), b.get("lyrics", ""), b.get("length", "medium"))})
            except Exception as e:
                return self.send(400, {"error": str(e)})
        return self.send(404, {"error": "not found"})

    def send_audio(self, path, extra):
        """Serves a WAV with Range support (needed for seeking, and by Safari/iPhone)."""
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes=") and "-" in rng:
            a, _, b = rng[6:].partition("-")
            try:
                start = int(a) if a else max(0, size - int(b))
                end = min(int(b), size - 1) if a and b else size - 1
                code = 206
            except ValueError:
                start, end, code = 0, size - 1, 200
        if start > end or start >= size:
            return self.send(416, b"", "audio/wav", {"Content-Range": f"bytes */{size}"})
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)
        hdr = {"Accept-Ranges": "bytes", **extra}
        if code == 206:
            hdr["Content-Range"] = f"bytes {start}-{end}/{size}"
        return self.send(code, data, "audio/wav", hdr)

    def auth_post(self, path):
        try:
            if path == "/api/auth/login":
                b = self.body_json()
                s = auth.login(b.get("name"), b.get("password"))
                return self.send(200, {"ok": True}, cookies=[auth.cookie_header(s)])
            if path == "/api/auth/register":
                if not self.is_local():
                    raise auth.AuthError("Accounts can only be created on the Mac itself. Create it there, then sign in here.")
                b = self.body_json()
                s, first = auth.register(b.get("name"), b.get("password"))
                if first:
                    claim_legacy(s["uid"])
                return self.send(200, {"ok": True}, cookies=[auth.cookie_header(s)])
            if path == "/api/auth/guest":
                if not self.is_local():
                    raise auth.AuthError("Guest mode is only available on the Mac itself. Sign in with an account.")
                return self.send(200, {"ok": True}, cookies=[auth.cookie_header(auth.guest())])
            if not self.need_login():
                return
            if path == "/api/auth/logout":
                chat.end_incognito(self.owner)
                auth.logout(self.owner)
                return self.send(200, {"ok": True}, cookies=[auth.clear_cookie_header()])
            if path == "/api/auth/password":
                b = self.body_json()
                auth.change_password(self.owner, b.get("old"), b.get("new"))
                return self.send(200, {"ok": True})
            return self.send(404, {"error": "not found"})
        except auth.AuthError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            return self.send(400, {"error": f"{type(e).__name__}: {e}"})

    def chat_post(self, path):
        o = self.owner
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        try:
            body = self.body_json()
            if path == "/api/chat/new":
                return self.send(200, chat.new_chat(o, body.get("model"), bool(body.get("incognito"))))
            if path == "/api/library":
                import base64 as b64
                name = Path(str(body.get("name") or "file")).name[:120] or "file"
                data = b64.b64decode(str(body.get("data") or "").split(",", 1)[-1])
                if len(data) > chat.MAX_FILE_BYTES:
                    raise ValueError("That file is larger than 25 MB.")
                library.add(o, name, data)
                return self.send(200, {"items": library.list_docs(o)})
            if path == "/api/library/search":
                return self.send(200, {"hits": library.search(o, str(body.get("query", "")))})
            if path == "/api/memory":
                it = chat.mem_add(o, body.get("text", ""), "manual")
                return self.send(200, {"items": chat.mem_load(o), "added": bool(it)})
            if path == "/api/chat/rename":
                chat.rename(o, body["id"], body["title"])
                return self.send(200, {"ok": True})
            if path == "/api/chat/end-incognito":
                chat.end_incognito(o)
                return self.send(200, {"ok": True})
            if path == "/api/chat/stop":
                chat.load(o, q.get("id", ""))
                chat.cancel_flags[q.get("id", "")] = True
                return self.send(200, {"ok": True})
            if path == "/api/chat/send":
                chat.load(o, body["id"])
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

                def write(ev):
                    try:
                        self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                        self.wfile.flush()
                    except OSError:
                        chat.cancel_flags[body["id"]] = True  # browser went away: stop generating

                chat.stream_turn(body, write, o)
                return
            return self.send(404, {"error": "not found"})
        except Exception as e:
            return self.send(400, {"error": f"{type(e).__name__}: {e}"})

    # ---------- DELETE
    def do_DELETE(self):
        if not self.same_origin():
            return self.send(403, {"error": "cross-site request blocked"})
        if not self.need_login():
            return
        o = self.owner
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/library":
                library.delete(o, q.get("id", ""))
                return self.send(200, {"items": library.list_docs(o)})
            if u.path == "/api/memory":
                chat.mem_clear(o) if q.get("all") else chat.mem_delete(o, q.get("id"))
                return self.send(200, {"items": chat.mem_load(o)})
            if u.path == "/api/chat/item":
                chat.delete(o, q.get("id"))
                return self.send(200, {"ok": True})
            if u.path == "/api/img/lora":
                imgedit.lora_delete(o, q.get("name", ""))
                return self.send(200, {"loras": imgedit.lora_list(o)})
            if u.path == "/api/img/item":
                imgedit.delete(o, q.get("id", ""))
                return self.send(200, {"ok": True})
            if not q.get("id", "").startswith("mine/"):
                return self.send(400, {"error": "only your own generated samples can be deleted"})
            p = resolve(q["id"], o)
            p.unlink()
            p.with_suffix(".json").unlink(missing_ok=True)
            return self.send(200, {"ok": True})
        except (KeyError, ValueError, FileNotFoundError) as e:
            return self.send(400, {"error": str(e)})


PORT = int(os.environ.get("JACOBAI_PORT", 8000))
TLS_PORT = int(os.environ.get("JACOBAI_TLS_PORT", 8443))
CACHEABLE = {"/", "/api/chat/list", "/api/chat/get", "/api/img/history", "/api/samples"}
CERT, KEY = ROOT / "certs/server.pem", ROOT / "certs/server.key"
TLS = CERT.exists() and KEY.exists()
HOSTNAME = (os.popen("scutil --get LocalHostName 2>/dev/null").read().strip() or socket.gethostname().split(".")[0])


class TLSHandler(Handler):
    tls = True
LAN = os.environ.get("JACOBAI_LAN", "1") == "1"  # also reachable from your phone on the same Wi-Fi (sign-in required)

def serve():
    host = "0.0.0.0" if LAN else "127.0.0.1"
    servers = [ThreadingHTTPServer((host, PORT), Handler)]
    msg = f"unplugged.ai running at http://127.0.0.1:{PORT}"
    ip = lan_ip()
    if LAN and ip:
        msg += f"  and on your network at http://{ip}:{PORT}"
    if TLS:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        s = ThreadingHTTPServer((host, TLS_PORT), TLSHandler)
        s.socket = ctx.wrap_socket(s.socket, server_side=True)
        servers.append(s)
        msg += f"  |  secure (for the iPhone app): https://{HOSTNAME}.local:{TLS_PORT}"
    try:   # "localhost" resolves to ::1 first in some browsers; listen there too so it never says not found
        class V6Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        servers.append(V6Server(("::1", PORT), Handler))
    except OSError:
        pass
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(msg + "  (Ctrl+C to stop)", flush=True)
    logbus.log("system", f"unplugged.ai started: music model surround {'ready' if surround.ready() else 'not installed'}, image model {'ready' if imgedit.status()['ready'] else 'not installed'}")
    servers[0].serve_forever()


if __name__ == "__main__":
    serve()
