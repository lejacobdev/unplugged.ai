"""Local dashboard for the piano + guitar MIDI model.

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

import torch
from symusic import Score
from transformers import GPT2LMHeadModel

import auth
import chat
import imgedit
import logbus
from common import ROOT, make_tokenizer

# The general model (trained on piano + electric guitar MIDI for everyone). Point UNPLUGGED_MUSIC_CKPT at a personal fine-tune to use that instead.
CKPT = Path(os.environ.get("UNPLUGGED_MUSIC_CKPT", "")) if os.environ.get("UNPLUGGED_MUSIC_CKPT") else ROOT / "ckpt/base"
FEATURED = ROOT / "out"
MINE = ROOT / "dashboard_samples"
WEB = ROOT / "web"
PIANO, GUITAR = {0, 4}, {27, 29}
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
MINE.mkdir(exist_ok=True)

tok = make_tokenizer()
model = GPT2LMHeadModel.from_pretrained(CKPT).eval()
SPECIAL = {tok["BOS_None"], tok["EOS_None"], tok["PAD_None"]}
gen_lock = threading.Lock()
jobs = {}


def _meta(p: Path):
    mp = p.with_suffix(".json")
    try:
        return json.loads(mp.read_text()) if mp.exists() else {}
    except Exception:
        return {}


def resolve(sample_id: str, owner=None) -> Path:
    kind, _, name = sample_id.partition("/")
    if kind not in ("featured", "mine") or not NAME_RE.match(name):
        raise ValueError("bad sample id")
    p = (FEATURED if kind == "featured" else MINE) / f"{name}.mid"
    if not p.exists() or (kind == "mine" and owner is not None and _meta(p).get("owner") != owner["uid"]):
        raise FileNotFoundError(sample_id)
    return p


def part_of(program):
    return "piano" if program in PIANO else "guitar" if program in GUITAR else "other"


def describe(path: Path):
    sc = Score(str(path)).to("second")
    counts = {"piano": 0, "guitar": 0}
    for t in sc.tracks:
        counts[part_of(t.program)] = counts.get(part_of(t.program), 0) + len(t.notes)
    return {"duration": round(sc.end(), 1), "piano": counts["piano"], "guitar": counts["guitar"]}


def list_samples(owner):
    out = []
    for kind, folder in (("mine", MINE), ("featured", FEATURED)):
        for p in sorted(folder.glob("*.mid"), key=lambda q: q.stat().st_mtime, reverse=True):
            if p.stem.endswith(("_piano", "_guitar")):
                continue
            meta = _meta(p)
            if kind == "mine" and meta.get("owner") != owner["uid"]:
                continue
            meta.pop("owner", None)
            try:
                info = describe(p)
            except Exception:
                continue
            out.append({"id": f"{kind}/{p.stem}", "name": p.stem, "kind": kind, "created": p.stat().st_mtime, **info, **meta})
    return out


def notes_json(path: Path):
    sc = Score(str(path)).to("second")
    tracks = {}
    for t in sc.tracks:
        part = part_of(t.program)
        d = tracks.setdefault(part, {"name": part, "program": t.program, "notes": []})
        d["notes"] += [[round(n.time, 3), round(n.duration, 3), n.pitch, n.velocity] for n in t.notes]
    for d in tracks.values():
        d["notes"].sort()
    return {"duration": sc.end(), "tracks": list(tracks.values())}


def midi_part(path: Path, part: str) -> bytes:
    if part == "both":
        return path.read_bytes()
    want = PIANO if part == "piano" else GUITAR
    sc = Score(str(path))
    sc.tracks = [t for t in sc.tracks if t.program in want]
    return bytes(sc.dumps_midi())


def run_job(job_id, p):
    job = jobs[job_id]
    try:
        bos = [tok["BOS_None"]]
        starts = []
        for pp in (p.get("prompt_paths") or ([p["prompt_path"]] if p.get("prompt_path") else [])):
            seq = tok(Score(str(pp)))
            seq = seq[0] if isinstance(seq, list) else seq
            starts.append(bos + list(seq.ids)[: int(p["prompt_tokens"])])
        if not starts and p.get("continue_id"):
            seq = tok(Score(str(resolve(p["continue_id"], p["owner"]))))
            seq = seq[0] if isinstance(seq, list) else seq
            starts.append(bos + list(seq.ids)[: int(p["prompt_tokens"])])
        starts = starts or [bos]
        start = starts[0]
        want = int(p["count"])
        tries = 0
        rep = max(float(p["rep"]), 1.05)  # below this the model tends to loop on one token
        n_tok = int(p["tokens"])
        min_total, min_each = max(30, int(n_tok * 0.12)), max(12, int(n_tok * 0.05))
        stuck = 0
        with gen_lock:
            while len(job["results"]) < want and tries < want * 8:
                tries += 1
                # a reference that keeps failing is swapped for another by the same artist; after four tries the piece is written without one
                start = starts[(tries - 1) % len(starts)] if (tries <= 4 or not p.get("prompt_paths")) else bos
                if start is bos and p.get("prompt_paths") and not job.get("note"):
                    job["note"] = "Could not follow that style closely, so this is a general piece."
                job["message"] = f"Composing sample {len(job['results']) + 1} of {want}…"
                logbus.log("music", owner=p["owner"]["uid"], text=f"composing sample {len(job['results']) + 1}/{want}: up to {int(p['tokens'])} tokens, creativity {p['temp']}, variety {rep:.2f}" + (f", continuing {p['continue_id']}" if p.get("continue_id") else ""))
                if p.get("seed") not in (None, ""):
                    torch.manual_seed(int(p["seed"]) + tries - 1)
                with torch.no_grad():
                    y = model.generate(
                        torch.tensor([start]), do_sample=True, temperature=float(p["temp"]),
                        top_p=float(p["top_p"]), repetition_penalty=rep,
                        max_new_tokens=max(50, min(int(p["tokens"]), 1023 - len(start))), pad_token_id=tok["PAD_None"], eos_token_id=tok["EOS_None"],
                    )
                ids = [t for t in y[0].tolist() if t not in SPECIAL]
                try:
                    score = tok.decode(ids)
                except Exception:
                    continue
                n_p = sum(len(t.notes) for t in score.tracks if t.program in PIANO)
                n_g = sum(len(t.notes) for t in score.tracks if t.program in GUITAR)
                if n_p + n_g < min_total or (p.get("need_both") and min(n_p, n_g) < min_each):
                    stuck += 1
                    logbus.log("music", owner=p["owner"]["uid"], text=f"try {tries}: unusable ({n_p} piano / {n_g} guitar notes, looping or too sparse); raising variety and retrying")
                    rep = min(rep + 0.04, 1.3)  # looping or too sparse: push harder against repetition next try
                    continue
                eph = bool(p.get("ephemeral")) or p["owner"]["kind"] == "guest"
                name = ("tmp_" if eph else "") + time.strftime("gen_%m%d_%H%M%S") + f"_{len(job['results'])}"
                if eph:
                    p["owner"]["temp_files"].add("m:" + name)
                path = MINE / f"{name}.mid"
                score.dump_midi(str(path))
                meta = {k: p[k] for k in ("temp", "top_p", "rep", "tokens")}
                meta["continued_from"] = p.get("continue_id") or None
                meta["owner"] = p["owner"]["uid"]
                path.with_suffix(".json").write_text(json.dumps(meta))
                job["results"].append(f"mine/{name}")
                logbus.log("music", owner=p["owner"]["uid"], text=f"saved {name}.mid: {n_p} piano notes, {n_g} guitar notes")
        job["status"] = "done"
        job["message"] = ("Done" + (". " + job["note"] if job.get("note") else "")) if job["results"] else ("No usable samples. The model kept looping or wrote too little, even after raising Variety automatically. " + ("Try a longer Length, or untick 'Require both'." if p.get("need_both") else "Try a longer Length and Creativity near 0.95."))
    except Exception as e:
        job["status"] = "error"
        job["message"] = f"{type(e).__name__}: {e}"


# ---------- chat tools (the LLM can call these)
# ---------- "in the style of ...": seed a new piece with the opening of a real piece by that artist from the local training library
_style_index = None


def _norm(t):
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", t.lower().replace("&", " and ").replace("-", " "))).strip()


def _build_style_index():
    global _style_index
    idx = []
    for group in ("base_lakh", "mine_style", "mine_core"):
        d = ROOT / "data/clean" / group
        if d.exists():
            for f in d.glob("*__*__*.mid"):
                artist, title, _ = f.stem.split("__", 2) if f.stem.count("__") >= 2 else (f.stem, "", "")
                idx.append((_norm(artist), _norm(title), artist, title, f))
    _style_index = idx


_FILLER = set("in the style of like a an some something song piece music tune track sounding that sounds similar to by from with and for me make create write compose give please".split())


def find_style_reference(style):
    """Returns (path, artist, title) of a library piece matching the requested artist/song, or None.
    The artist (or song) name must make up at least half of what was asked, so unknown names are not matched by accident."""
    if not style:
        return None
    if _style_index is None:
        _build_style_index()
    words = [w for w in _norm(style).split() if w not in _FILLER]
    if not words:
        return None
    q = " " + " ".join(words) + " "
    def covers(name):
        n = name.split()
        return len(name) >= 3 and " " + name + " " in q and len(n) / len(words) >= 0.5
    by_title = [e for e in _style_index if len(e[1]) >= 4 and " " + e[1] + " " in q and (not e[0] or " " + e[0] + " " in q)]
    by_artist = [e for e in _style_index if covers(e[0])]
    hit = by_title or by_artist
    if not hit:
        return None
    e = random.choice(hit)
    return e[4], e[2], e[3]


def style_candidates(style, n=5):
    """Up to n library pieces matching the request that contain both piano and guitar (so the continuation can too)."""
    first = find_style_reference(style)
    if not first:
        return []
    words = [w for w in _norm(style).split() if w not in _FILLER]
    q = " " + " ".join(words) + " "
    pool = [e for e in _style_index if e[0] == _norm(first[1])] or [e for e in _style_index if e[4] == first[0]]
    random.shuffle(pool)
    out = []
    for e in pool[:40]:
        try:
            sc = Score(str(e[4]))
            progs = {t.program for t in sc.tracks if len(t.notes) > 10}
            if progs & PIANO and progs & GUITAR:
                out.append((e[4], e[2], e[3]))
        except Exception:
            continue
        if len(out) >= n:
            break
    return out or [first]


def start_music(owner, ephemeral, style="", length="medium", creativity="balanced", count=1, cont=None):
    """Starts a background generation job. Returns (job id, reference or None)."""
    tokens = {"short": 500, "medium": 800, "long": 1000}.get(length, 800)
    temp, rep = {"safe": (0.9, 1.15), "balanced": (0.95, 1.12), "wild": (1.1, 1.12)}.get(creativity, (0.95, 1.12))
    try:
        if cont:
            resolve(cont, owner)
    except Exception:
        cont = None
    style = (style or "").strip()
    cands = style_candidates(style) if style and not cont else []
    ref = cands[0] if cands else None
    count = max(1, min(int(count or 1), 4))
    p = {"owner": owner, "ephemeral": bool(ephemeral), "count": count, "tokens": tokens, "temp": temp, "top_p": 0.95, "rep": rep, "need_both": True,
         "prompt_tokens": 96 if ref else 64, "continue_id": cont, "prompt_path": str(ref[0]) if ref else None, "prompt_paths": [str(c[0]) for c in cands]}
    jid = uuid.uuid4().hex[:8]
    jobs[jid] = {"status": "running", "owner": owner["uid"], "message": "Starting the music model…", "results": [], "count": count, "started": time.time()}
    threading.Thread(target=run_job, args=(jid, p), daemon=True).start()
    return jid, ref


def tool_generate_music(args, chat_obj, owner):
    style = (args.get("style") or "").strip()
    jid, ref = start_music(owner, chat_obj.get("incognito"), style, args.get("length", "medium"), args.get("creativity", "balanced"), 1, args.get("continue_from") or None)
    if ref:
        how = f"It is seeded with the opening of a real piece by {ref[1]} from the local library ({ref[2]}) and then continues as new music. Say it is inspired by {ref[1]}, not a copy."
    elif style:
        how = f"There is nothing by '{style}' in the local music library, so this is a general piano + guitar piece, not in that style. Tell the user this honestly."
    else:
        how = ""
    return ("Started composing one new piece. It appears in this chat as a player with a piano roll when it is ready (about 30 to 90 seconds). " + how +
            " Tell the user briefly that it is being made. Do not describe the music yet, you have not heard it."), {"kind": "music_job", "job": jid}


def tool_edit_picture(args, chat_obj, owner):
    if not imgedit.status()["ready"]:
        return "The offline image model is not installed yet. Tell the user to run setup_image_model.sh (see the Pictures tab).", None
    name = next((m["images"][-1] for m in reversed(chat_obj["messages"]) if m.get("images")), None)
    if not name:
        return "No picture is attached to this chat. Ask the user to drag a picture into the chat (or use the paperclip).", None
    import base64 as b64
    data = "data:image/png;base64," + b64.b64encode(imgedit.image_path(name).read_bytes()).decode()
    # the user's own words go to FLUX unchanged: the language model neither rewrites nor reviews the request
    said = next((m["content"].strip() for m in reversed(chat_obj["messages"]) if m["role"] == "user"), "")
    instruction = said if said and said != "(picture attached)" else args.get("instruction", "")
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
    return json.dumps([{"id": s["id"], "seconds": s["duration"], "piano_notes": s["piano"], "guitar_notes": s["guitar"]} for s in items][:20]), None


chat.TOOL_IMPL.update({"generate_music": tool_generate_music, "edit_picture": tool_edit_picture, "list_music": tool_list_music})


def purge_guest(owner):
    """A guest session ended: delete everything it created."""
    chat.purge_owner(owner)
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
            if u.path == "/api/notes":
                return self.send(200, notes_json(resolve(q["id"], o)))
            if u.path == "/api/job":
                j = jobs.get(q.get("id"))
                return self.send(200, {k: v for k, v in j.items() if k != "owner"} if j and j.get("owner") == o["uid"] else {"status": "error", "message": "unknown job", "results": []})
            if u.path == "/midi":
                path, part = resolve(q["id"], o), q.get("part", "both")
                fname = f"{path.stem}_{part}.mid" if part != "both" else f"{path.stem}.mid"
                return self.send(200, midi_part(path, part), "audio/midi", {"Content-Disposition": f'attachment; filename="{fname}"'})
            if u.path == "/api/info":
                return self.send(200, {"model": CKPT.name, "params_m": round(sum(p.numel() for p in model.parameters()) / 1e6, 1)})
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
        if path.startswith("/api/chat/"):
            return self.chat_post(path)
        if path == "/api/music/prompt":
            try:
                b = self.body_json()
                text = (b.get("prompt") or "").strip()
                if not text:
                    return self.send(400, {"error": "Describe the music you want first."})
                plan = chat.plan_music(b.get("model") or "gpt-oss:20b", text)
                jid, ref = start_music(o, False, plan["style"], plan["length"], plan["creativity"], plan["count"])
                return self.send(200, {"job": jid, "plan": plan, "reference": {"artist": ref[1], "title": ref[2]} if ref else None})
            except Exception as e:
                return self.send(400, {"error": str(e)})
        if path != "/api/generate":
            return self.send(404, {"error": "not found"})
        try:
            p = self.body_json()
            defaults = {"count": 1, "tokens": 1000, "temp": 0.95, "top_p": 0.95, "rep": 1.12, "need_both": True, "prompt_tokens": 64}
            p = {**defaults, **p}
            p["count"] = max(1, min(int(p["count"]), 6))
            p["tokens"] = max(200, min(int(p["tokens"]), 1000))
            if p.get("continue_id"):
                resolve(p["continue_id"], o)
        except Exception as e:
            return self.send(400, {"error": str(e)})
        p["owner"] = o
        jid = uuid.uuid4().hex[:8]
        jobs[jid] = {"status": "running", "owner": o["uid"], "message": "Starting…", "results": [], "count": p["count"]}
        threading.Thread(target=run_job, args=(jid, p), daemon=True).start()
        return self.send(200, {"job": jid})

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
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(msg + "  (Ctrl+C to stop)", flush=True)
    logbus.log("system", f"unplugged.ai started: music model {CKPT.name} on CPU, image model {'ready' if imgedit.status()['ready'] else 'not installed'}")
    servers[0].serve_forever()


if __name__ == "__main__":
    serve()
