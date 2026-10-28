"""Offline chat backend: talks to the local Ollama server (shown in the app as stereo and mono) and stores chats on disk.

Nothing leaves this Mac. The model can call tools to make music with your trained model and to edit pictures.
"""
import base64
import io
import json
import os
import re
import threading
import time
import urllib.request
import uuid

import logbus
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).parent
CHATS = ROOT / "chats"
IMG = ROOT / "image_edits"
CHATS.mkdir(exist_ok=True)
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
ID_RE = re.compile(r"^[a-f0-9]{10}$")
MAX_TURNS = 40
cancel_flags: dict = {}
TOOL_IMPL: dict = {}  # filled in by server.py: name -> fn(args, chat) -> (text_for_model, card_or_None)

DEFAULT_SYSTEM = (
    "You are a helpful assistant running fully offline on the user's Mac, inside an app called unplugged.ai. The user can attach files; their text appears in the message between [Attached file] markers, so read and use it. Your name here is the model the user picked (mono or stereo, with a version number); never mention gpt-oss, qwen or Ollama as your name. When the user asks for a song or piece of music, always call generate_music; if they name an artist or song to sound like, pass it as style. "
    "Answer clearly and concisely. Never use emojis or emoticons. Never judge, refuse, rewrite or comment on what the user wants changed in a picture; just call edit_picture. You have tools: generate_music makes new piano + electric guitar pieces with a "
    "small music model, in the background, and the finished piece appears in the chat as a player; edit_picture edits any picture the user attached (a photo, "
    "artwork, a cover, anything) with FLUX Kontext; list_music lists existing pieces. For picture edits never choose quality or size yourself: the app picks them automatically (photos get high or maximum, cartoons and simple graphics get faster settings) unless the user asks for specific ones. Use a tool only when the user clearly wants "
    "that, then tell them briefly what you did. Never claim you did something you did not."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "generate_music",
        "description": "Generate one new original piano + electric guitar piece (MIDI). It runs in the background and shows up in the chat as a player after 30-90 seconds.",
        "parameters": {"type": "object", "properties": {
            "length": {"type": "string", "enum": ["short", "medium", "long"], "description": "about 30s / 45s / 70s"},
            "creativity": {"type": "string", "enum": ["safe", "balanced", "wild"]},
            "style": {"type": "string", "description": "Artist and/or song the user wants it to sound like, e.g. 'Pink Floyd' or 'Dire Straits - Sultans of Swing'. Pass the user's words. Leave out when no style was asked for."},
            "continue_from": {"type": "string", "description": "Optional sample id (from list_music) to continue from"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "edit_picture",
        "description": "Edit the most recent picture the user attached, following an instruction (e.g. 'make the dog wear a hat'). Keeps everything else the same. Takes several minutes.",
        "parameters": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "What to change, in plain English"},
            "quality": {"type": "string", "enum": ["standard", "high", "maximum"], "description": "Do not set this; the app chooses it automatically unless the user asked"},
            "size": {"type": "integer", "description": "Do not set this; the app chooses it automatically unless the user asked"}},
            "required": ["instruction"]}}},
    {"type": "function", "function": {
        "name": "list_music", "description": "List the music pieces that already exist (ids and lengths).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]


# ---------- storage (per account; guest and incognito chats live only in memory)
_mem: dict = {}  # uid -> {chat_id: chat}


def _dir(owner):
    d = CHATS / owner["uid"]
    d.mkdir(exist_ok=True)
    return d


def _cid(cid):
    if not ID_RE.match(cid or ""):
        raise ValueError("bad chat id")
    return cid


def is_private(owner, chat):
    return owner["kind"] == "guest" or bool(chat.get("incognito"))


def load(owner, cid):
    _cid(cid)
    c = _mem.get(owner["uid"], {}).get(cid)
    if c is not None:
        return c
    p = _dir(owner) / f"{cid}.json"
    if owner["kind"] == "guest" or not p.exists():
        raise FileNotFoundError(cid)
    return json.loads(p.read_text())


def save(owner, chat):
    chat["updated"] = time.time()
    if is_private(owner, chat):
        _mem.setdefault(owner["uid"], {})[chat["id"]] = chat
    else:
        (_dir(owner) / f"{_cid(chat['id'])}.json").write_text(json.dumps(chat))


def new_chat(owner, model=None, incognito=False):
    chat = {"id": uuid.uuid4().hex[:10], "title": "Incognito chat" if incognito else "New chat", "created": time.time(),
            "updated": time.time(), "model": model, "messages": [], **({"incognito": True} if incognito else {})}
    save(owner, chat)
    return chat


def list_chats(owner):
    out = []
    pool = list(_mem.get(owner["uid"], {}).values())
    if owner["kind"] == "user":
        for f in _dir(owner).glob("*.json"):
            try:
                pool.append(json.loads(f.read_text()))
            except Exception:
                pass
    for c in pool:
        if not c.get("incognito"):
            out.append({"id": c["id"], "title": c["title"], "updated": c["updated"], "model": c.get("model"), "n": len(c["messages"])})
    return sorted(out, key=lambda c: c["updated"], reverse=True)


def rename(owner, cid, title):
    c = load(owner, cid)
    c["title"] = title.strip()[:80] or c["title"]
    save(owner, c)


def _drop_images(chat):
    for m in chat.get("messages", []):
        for f in m.get("images", []):
            (IMG / f).unlink(missing_ok=True)


def delete(owner, cid):
    _cid(cid)
    c = _mem.get(owner["uid"], {}).pop(cid, None)
    if c:
        _drop_images(c)
    if owner["kind"] == "user":
        (_dir(owner) / f"{cid}.json").unlink(missing_ok=True)


def end_incognito(owner):
    """Forget this account's incognito chats (called when leaving one, on page load, on sign-out)."""
    for cid, c in list(_mem.get(owner["uid"], {}).items()):
        if c.get("incognito"):
            _mem[owner["uid"]].pop(cid, None)
            _drop_images(c)


def purge_owner(owner):
    for c in _mem.pop(owner["uid"], {}).values():
        _drop_images(c)


# ---------- ollama helpers
# The app shows its own model names. Bump MODEL_VERSION when the models are upgraded; the real Ollama names stay hidden.
MODEL_VERSION = 2
MODEL_FAMILY = {"qwen3:14b": "mono", "gpt-oss:20b": "stereo"}   # mono: simpler and quicker; stereo: stronger reasoning


MODEL_DESC = {"mono": "Fast. Everyday chat, quick questions and simple music requests.",
              "stereo": "Best. Deeper reasoning, long files and detailed music requests."}


def desc_for(name):
    return MODEL_DESC.get(MODEL_FAMILY.get(name), "")


def label_for(name):
    fam = MODEL_FAMILY.get(name)
    return f"{fam} {MODEL_VERSION}" if fam else name


def models():
    with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=4) as r:
        out = [{"name": m["name"], "label": label_for(m["name"]), "desc": desc_for(m["name"]), "size": m["size"], "caps": m.get("capabilities", [])} for m in json.load(r)["models"]]
    return sorted(out, key=lambda m: (m["name"] not in MODEL_FAMILY, m["name"] != "qwen3:14b", m["name"]))


def _training_running():
    import subprocess
    return subprocess.run(["pgrep", "-f", "train.py|finetune_lora.py|mflux"], capture_output=True).returncode == 0


def status():
    try:
        m = models()
        return {"ok": True, "models": m, "training": _training_running()}
    except Exception as e:
        return {"ok": False, "error": f"Can't reach Ollama at {OLLAMA}: {e}", "models": []}


def _think_param(model, level):
    if level in (None, ""):
        return None
    if model.startswith("gpt-oss"):
        return "low" if level == "off" else level
    return level != "off"


def _store_image(chat_id, data_url, private=False):
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    img.thumbnail((2048, 2048))
    name = f"{'t' if private else ''}chat_{chat_id}_{uuid.uuid4().hex[:6]}.png"
    img.save(IMG / name)
    return name


# ---------- files attached to a message: the text is pulled out so the language model can read it
MAX_FILE_CHARS = 40000
MAX_FILES = 6
MAX_FILE_BYTES = 25 * 1024 * 1024
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".py", ".java", ".c", ".h", ".cpp", ".hpp",
            ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sh", ".zsh", ".bash", ".sql", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env", ".log", ".tex", ".bib", ".r",
            ".lua", ".pl", ".scala", ".dart", ".gradle", ".make", ".mk", ".dockerfile", ".gitignore", ".srt", ".vtt", ".rst", ".org", ".abc"}


def _xml_text(xml, para_tags):
    import re as _re
    for t in para_tags:
        xml = xml.replace(t, "\n")
    return _re.sub(r"[ \t]+", " ", _re.sub(r"<[^>]+>", "", xml)).strip()


def extract_text(name, data):
    """Returns (kind, text, note). kind: text | pdf | docx | xlsx | pptx | midi | zip | image | binary."""
    import io as _io
    import html as _html
    import zipfile
    ext = Path(name).suffix.lower()
    try:
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".bmp"):
            return "image", "", "a picture (the language model cannot see pictures; it can edit them with FLUX)"
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(_io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in r.pages[:200]]
            return "pdf", "\n\n".join(f"[page {i + 1}]\n{t}" for i, t in enumerate(pages) if t.strip()), f"{len(r.pages)} pages"
        if ext in (".docx", ".pptx", ".xlsx"):
            z = zipfile.ZipFile(_io.BytesIO(data))
            if ext == ".docx":
                return "docx", _html.unescape(_xml_text(z.read("word/document.xml").decode("utf8", "replace"), ["</w:p>", "<w:br/>", "</w:tr>"])), ""
            if ext == ".pptx":
                slides = sorted(n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
                return "pptx", "\n\n".join(f"[slide {i + 1}]\n" + _html.unescape(_xml_text(z.read(n).decode("utf8", "replace"), ["</a:p>"])) for i, n in enumerate(slides)), f"{len(slides)} slides"
            shared = _html.unescape(_xml_text(z.read("xl/sharedStrings.xml").decode("utf8", "replace"), ["</si>"])) if "xl/sharedStrings.xml" in z.namelist() else ""
            return "xlsx", shared, "text cells only (numbers and formulas are not shown)"
        if ext in (".mid", ".midi"):
            import mido
            m = mido.MidiFile(file=_io.BytesIO(data))
            notes = sum(1 for t in m.tracks for x in t if x.type == "note_on" and x.velocity > 0)
            return "midi", f"MIDI file: {len(m.tracks)} tracks, {notes} notes, about {int(m.length)} seconds.", ""
        if ext == ".zip":
            z = zipfile.ZipFile(_io.BytesIO(data))
            return "zip", "Files inside: " + ", ".join(z.namelist()[:200]), ""
        sample = data[:4096]
        if ext in TEXT_EXT or b"\x00" not in sample:
            txt = data.decode("utf-8", "replace")
            if sum(ch.isprintable() or ch in "\n\r\t" for ch in txt[:4000]) > 0.9 * max(1, len(txt[:4000])):
                return "text", txt, ""
    except Exception as e:
        return "binary", "", f"could not read it ({type(e).__name__})"
    return "binary", "", "a binary file the language model cannot read"


def attach_files(raw_files):
    """raw_files: [{name, data (data URL or base64)}] -> (meta list for the UI, text blocks for the model)."""
    meta, blocks = [], []
    for f in (raw_files or [])[:MAX_FILES]:
        name = Path(str(f.get("name") or "file")).name[:120] or "file"
        data = base64.b64decode(str(f.get("data") or "").split(",", 1)[-1])
        if len(data) > MAX_FILE_BYTES:
            meta.append({"name": name, "size": len(data), "kind": "binary", "note": "too large (25 MB limit)"})
            continue
        kind, text, note = extract_text(name, data)
        cut = len(text) > MAX_FILE_CHARS
        meta.append({"name": name, "size": len(data), "kind": kind, "note": (note + (", shortened to the first %d characters" % MAX_FILE_CHARS if cut else "")).strip(", ")})
        blocks.append({"name": name, "kind": kind, "text": text[:MAX_FILE_CHARS], "note": note})
    return meta, blocks


def _ollama_messages(chat, system):
    msgs = [{"role": "system", "content": system or DEFAULT_SYSTEM}]
    for m in chat["messages"][-MAX_TURNS:]:
        if m["role"] == "user":
            text = m["content"]
            if m.get("images"):
                text += "\n[The user attached a picture. You cannot see it. If their message asks for any change to the picture, call the edit_picture tool right away with a clear English instruction; do not ask for confirmation.]"
            for fb in m.get("file_text") or []:
                if fb["text"]:
                    text += f"\n\n[Attached file: {fb['name']}]\n{fb['text']}\n[End of {fb['name']}]"
                else:
                    text += f"\n\n[Attached file: {fb['name']} - {fb.get('note') or 'no readable text'}. Tell the user you cannot read its contents.]"
            msgs.append({"role": "user", "content": text})
        elif m["role"] == "assistant":
            d = {"role": "assistant", "content": m.get("content", "")}
            if m.get("tool_calls"):
                d["tool_calls"] = m["tool_calls"]
            msgs.append(d)
        elif m["role"] == "tool":
            msgs.append({"role": "tool", "tool_name": m.get("name", ""), "content": m["content"]})
    return msgs


PLAN_SCHEMA = {"type": "object", "properties": {
    "style": {"type": "string"}, "length": {"type": "string", "enum": ["short", "medium", "long"]},
    "creativity": {"type": "string", "enum": ["safe", "balanced", "wild"]}, "count": {"type": "integer"}},
    "required": ["style", "length", "creativity", "count"]}


def plan_music(model, prompt):
    """Turns a plain-English music request into generation settings, using the chosen chat model (mono or stereo)."""
    plan = {"style": prompt[:120], "length": "medium", "creativity": "balanced", "count": 1}
    try:
        body = {"model": model, "stream": False, "think": _think_param(model, "off"), "format": PLAN_SCHEMA, "options": {"temperature": 0.2, "num_predict": 700},
                "messages": [{"role": "system", "content": "You turn a music request into settings. style: only the artist and/or song to sound like, copied from the request in the user's words, or an empty string if none was named. "
                              "length: short (about 30 seconds), medium (about 45 seconds) or long (about 70 seconds); medium unless the user asks for short/long. "
                              "creativity: safe if they want something familiar or traditional, wild if they want experimental or surprising, otherwise balanced. "
                              "count: how many pieces (1 to 4), 1 unless they ask for more. Reply with JSON only."},
                             {"role": "user", "content": prompt}]}
        req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            got = json.loads(json.load(r)["message"]["content"])
        plan["style"] = str(got.get("style", "")).strip()[:120]
        plan["length"] = got.get("length") if got.get("length") in ("short", "medium", "long") else "medium"
        plan["creativity"] = got.get("creativity") if got.get("creativity") in ("safe", "balanced", "wild") else "balanced"
        plan["count"] = max(1, min(int(got.get("count") or 1), 4))
    except Exception:
        pass  # fall back to a plain request with the whole text as the style
    return plan


def _auto_title(owner, chat_id, model, use_llm=True):
    try:
        chat = load(owner, chat_id)
        first = next(m["content"] for m in chat["messages"] if m["role"] == "user")
        chat["title"] = first.strip().replace("\n", " ")[:48] or "New chat"
        save(owner, chat)  # instant fallback
        if not use_llm:
            return
        body = {"model": model, "stream": False, "think": _think_param(model, "low"), "options": {"temperature": 0.3, "num_predict": 400},
                "messages": [{"role": "user", "content": "Write a 3 to 5 word title for a chat that starts with this message. Reply with only the title, no quotes.\n\n" + first[:400]}]}
        req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            t = json.load(r)["message"]["content"].strip().strip('"').splitlines()[0][:60]
        if t:
            chat = load(owner, chat_id)
            chat["title"] = t
            save(owner, chat)
    except Exception:
        pass


# ---------- streaming turn
def stream_turn(body, write, owner):
    """Runs one assistant turn (with up to 4 tool rounds). `write(dict)` sends one event to the browser."""
    chat = load(owner, body["id"])
    quiet = bool(chat.get("incognito"))
    log = (lambda *a: None) if quiet else (lambda src, text: logbus.log(src, text, owner["uid"]))
    model = body.get("model") or chat.get("model") or "gpt-oss:20b"
    chat["model"] = model
    first_turn = not chat["messages"]
    if body.get("regenerate"):
        while chat["messages"] and chat["messages"][-1]["role"] != "user":
            chat["messages"].pop()
    else:
        user = {"role": "user", "content": (body.get("content") or "").strip()}
        if body.get("image"):
            user["images"] = [_store_image(chat["id"], body["image"], is_private(owner, chat))]
        if body.get("files"):
            user["files"], user["file_text"] = attach_files(body["files"])
        if not user["content"] and not user.get("images") and not user.get("files"):
            raise ValueError("empty message")
        user["content"] = user["content"] or ("(picture attached)" if user.get("images") else "(file attached)")
        chat["messages"].append(user)
    save(owner, chat)
    cancel_flags[chat["id"]] = False
    log("chat", f"{model}: new turn in '{chat['title']}' (tools {'on' if body.get('tools', True) else 'off'}, reasoning {body.get('think')})")
    use_tools = bool(body.get("tools", True))
    think = _think_param(model, body.get("think"))
    cards = []
    direct = use_tools and "edit_picture" in TOOL_IMPL and bool(chat["messages"] and chat["messages"][-1].get("role") == "user" and chat["messages"][-1].get("images"))
    try:
        if direct:
            # A picture came with the message: send it straight to the image model with the user's exact words.
            # The language model is not asked to read, judge, rewrite or comment on the request.
            write({"type": "tool_start", "name": "edit_picture", "args": {}})
            try:
                text, card = TOOL_IMPL["edit_picture"]({}, chat, owner)
            except Exception as e:
                text, card = f"Could not start the edit: {type(e).__name__}: {e}", None
            chat["messages"].append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "edit_picture", "arguments": {}}}]})
            chat["messages"].append({"role": "tool", "name": "edit_picture", "content": text, **({"card": card} if card else {})})
            say = (f"Sent straight to FLUX with your exact wording ({card['note']}). The live progress is shown above and the finished picture appears there." if card
                   else text)
            chat["messages"].append({"role": "assistant", "content": say})
            write({"type": "tool_result", "name": "edit_picture", "text": text, "card": card})
            write({"type": "token", "text": say})
            save(owner, chat)
            write({"type": "done"})
            log("chat", "picture sent straight to the image model (language model skipped)")
            return
        for _round in range(4):
            req_body = {"model": model, "messages": _ollama_messages(chat, body.get("system")), "stream": True,
                        "keep_alive": "2m", "options": {"temperature": float(body.get("temperature", 0.7)), "num_ctx": 16384}}
            if use_tools:
                req_body["tools"] = TOOLS
            if think is not None:
                req_body["think"] = think
            req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(req_body).encode(), {"Content-Type": "application/json"})
            content, thinking, calls = "", "", []
            with urllib.request.urlopen(req, timeout=900) as resp:
                for line in resp:
                    if cancel_flags.get(chat["id"]):
                        break
                    if not line.strip():
                        continue
                    msg = json.loads(line).get("message", {})
                    if msg.get("thinking"):
                        thinking += msg["thinking"]
                        write({"type": "thinking", "text": msg["thinking"]})
                    if msg.get("content"):
                        content += msg["content"]
                        write({"type": "token", "text": msg["content"]})
                    if msg.get("tool_calls"):
                        calls += msg["tool_calls"]
            amsg = {"role": "assistant", "content": content}
            if thinking:
                amsg["thinking"] = thinking
            if calls:
                amsg["tool_calls"] = calls
            chat["messages"].append(amsg)
            if cancel_flags.get(chat["id"]) or not calls:
                break
            for call in calls:
                fn = call.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                write({"type": "tool_start", "name": name, "args": args})
                log("chat", f"model called tool {name} {json.dumps(args)[:200]}")
                try:
                    impl = TOOL_IMPL.get(name)
                    text, card = impl(args, chat, owner) if impl else (f"Unknown tool {name}", None)
                except Exception as e:
                    text, card = f"Tool failed: {type(e).__name__}: {e}", None
                chat["messages"].append({"role": "tool", "name": name, "content": text, **({"card": card} if card else {})})
                write({"type": "tool_result", "name": name, "text": text, "card": card})
                log("chat", f"tool {name} returned: {text[:200]}")
                save(owner, chat)
        write({"type": "done"})
        log("chat", f"turn finished ({len(chat['messages'])} messages)")
    except Exception as e:
        write({"type": "error", "message": f"{type(e).__name__}: {e}"})
        log("chat", f"ERROR {type(e).__name__}: {e}")
    finally:
        save(owner, chat)
        if first_turn and chat["title"] == "New chat":
            threading.Thread(target=_auto_title, args=(owner, chat["id"], model, not direct), daemon=True).start()
