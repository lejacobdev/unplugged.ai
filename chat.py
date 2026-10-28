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
TOOL_IMPL: dict = {}  # name -> fn(args, chat, owner) -> (text_for_model, card_or_None); server.py adds the music and picture tools, the memory tools are added below

DEFAULT_SYSTEM = (
    "You are a helpful assistant running fully offline on the user's Mac, inside an app called unplugged.ai. The user can attach files; their text appears in the message between [Attached file] markers, so read and use it. Your name here is the model the user picked (mono or stereo, with a version number); never mention gpt-oss, qwen or Ollama as your name. When the user asks for a song or piece of music, always call generate_music: you are only the go-between, a separate music model called surround makes the audio. The request may be as short as an artist or song name ('dire straits', 'brothers in arms'); never ask questions, use your own knowledge of that sound. Write surround a detailed caption (genre, era, bpm, mood, each instrument with its tone, vocal type, and any signature solo with its tone, phrasing and that it is long) and, unless they want an instrumental, original lyrics with [Intro], [Verse], [Chorus], [Bridge], [Outro] tags and a section like [Guitar Solo - electric - overdriven, soulful] left empty where a solo belongs. Never put artist names in the caption and never copy existing lyrics. "
    "Answer clearly and concisely. Never use emojis or emoticons. When the user asks for a change to a picture, do not judge, refuse or comment on it; call edit_picture with their wish in clear English. When a picture arrives and it is not clear what they want done with it (no message, or only a question or a greeting), do not edit it: ask briefly what they would like to do, and offer the possibilities, for example changing something in it, restyling it, or using it as a starting point. You cannot see pictures yourself, so never describe their content. You have tools: generate_music hands your caption and lyrics to surround, which makes a full song with vocals in the background, and you only prepare the caption and lyrics, which the user reviews and can edit before they press Generate song, and the finished song then appears in the chat as an audio player; edit_picture edits any picture the user attached (a photo, "
    "artwork, a cover, anything) with FLUX Kontext; list_music lists existing pieces. For picture edits never choose quality or size yourself: the app picks them automatically (photos get high or maximum, cartoons and simple graphics get faster settings) unless the user asks for specific ones. Use a tool only when the user clearly wants "
    "that, then tell them briefly what you did. You have a long-term memory that lasts across chats and sessions: when the user tells you something lasting about themselves or asks you to remember something, call remember; when they ask you to forget something, call forget; when they refer to an earlier conversation you cannot recall, call search_past_chats before answering. Never pretend to remember something that is not in your memory. When the user attaches a picture, the message contains a report from a vision model: that is how you know what is in it. Never claim you did something you did not."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "generate_music",
        "description": "Prepare one new original song for the surround music model. The user sees your caption and lyrics as an editable draft in the chat and presses Generate song themselves; the song then takes a few minutes.",
        "parameters": {"type": "object", "properties": {
            "caption": {"type": "string", "description": "Detailed sound of the song in words, 40 to 70 words: genre and era, bpm, mood, each instrument with its tone, drums, bass, keys, vocal type, production, and any solo with its tone and that it is long. No artist names."},
            "lyrics": {"type": "string", "description": "Original lyrics with section tags on their own lines: [Intro], [Verse], [Chorus], [Bridge], [Outro], and a solo section such as [Guitar Solo - electric - overdriven, soulful] with nothing under it. Leave empty for an instrumental. About 24 to 40 sung lines."},
            "length": {"type": "string", "enum": ["short", "medium", "long"], "description": "about 1 / 2 / 3 minutes"}},
            "required": ["caption"]}}},
    {"type": "function", "function": {
        "name": "edit_picture",
        "description": "Edit the most recent picture the user attached, following an instruction (e.g. 'make the dog wear a hat'). Keeps everything else the same. Takes several minutes.",
        "parameters": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "What to change, in plain English"},
            "quality": {"type": "string", "enum": ["standard", "high", "maximum"], "description": "Do not set this; the app chooses it automatically unless the user asked"},
            "size": {"type": "integer", "description": "Do not set this; the app chooses it automatically unless the user asked"}},
            "required": ["instruction"]}}},
    {"type": "function", "function": {
        "name": "ask_about_picture",
        "description": "Ask the vision model a specific question about the picture the user attached (what is written on it, how many people, what colour something is, what is in a corner). The picture's general description is already in the message; use this for details.",
        "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "A precise question about the picture"}}, "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "search_documents",
        "description": "Search the user's own document library (files they added) by meaning and return the best matching passages with the document name.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "What to look for, as a short question or key phrases"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Save one lasting fact about the user to long-term memory, kept across all chats and sessions. Use it when the user asks you to remember something, or tells you something durable about themselves (name, work, preferences, projects, people, goals).",
        "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "One short sentence, e.g. 'The user prefers metric units'"}}, "required": ["fact"]}}},
    {"type": "function", "function": {
        "name": "forget",
        "description": "Remove something from long-term memory when the user asks you to forget it.",
        "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "Words describing what to forget"}}, "required": ["fact"]}}},
    {"type": "function", "function": {
        "name": "search_past_chats",
        "description": "Search the user's earlier saved chats by keywords. Use it when the user refers to something from a previous conversation that you do not remember.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "A few keywords"}}, "required": ["query"]}}},
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
    _gmem.pop(owner["uid"], None)
    for c in _mem.pop(owner["uid"], {}).values():
        _drop_images(c)


# ---------- vision: a separate vision model looks at pictures; the chat models read its description
VISION_PREF = ["qwen3-vl:8b", "qwen2.5vl:7b", "gemma3:12b", "llama3.2-vision:11b"]   # first one that is installed is used
_vm_cache = (0.0, None)
DESCRIBE_PROMPT = ("Describe this picture for someone who cannot see it. Say what it shows (people, objects, setting, style), "
                   "then transcribe any text exactly as written, and mention colours, quality problems and anything unusual. Be factual and complete, no opinions.")


def vision_model():
    global _vm_cache
    if time.time() - _vm_cache[0] < 30:
        return _vm_cache[1]
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5) as r:
            have = {m["name"] for m in json.load(r)["models"]}
        found = next((m for m in VISION_PREF if m in have or m + ":latest" in have), None)
    except Exception:
        found = None
    _vm_cache = (time.time(), found)
    return found


def look(image_name, prompt):
    """Asks the vision model about a stored picture. Returns its answer; raises if no vision model is installed."""
    vm = vision_model()
    if not vm:
        raise RuntimeError("No vision model is installed. Run: ollama pull " + VISION_PREF[0])
    im = ImageOps.exif_transpose(Image.open(IMG / image_name)).convert("RGB")
    im.thumbnail((1568, 1568))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=90)
    body = {"model": vm, "stream": False, "keep_alive": "30s", "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1200},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(buf.getvalue()).decode()]}]}
    req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return (json.load(r)["message"].get("content") or "").strip()


def _last_image(chat):
    return next((m["images"][-1] for m in reversed(chat["messages"]) if m.get("images")), None)


def _tool_ask_picture(args, chat, owner):
    name = _last_image(chat)
    if not name:
        return "No picture is attached to this chat.", None
    q = (args.get("question") or "").strip() or DESCRIBE_PROMPT
    try:
        return look(name, q + "\nAnswer from what is visible in the picture only; say so if it cannot be seen."), None
    except Exception as e:
        return f"Could not look at the picture: {e}", None


# ---------- long-term memory (per account; guests keep it in memory only, incognito chats neither read nor write it)
MEMDIR = ROOT / "memory"
MEMDIR.mkdir(exist_ok=True)
MEM_MAX = 300            # facts kept per account (oldest dropped first)
MEM_PROMPT_CHARS = 4500  # how much of it goes into each chat's instructions
_gmem: dict = {}         # guest uid -> [facts]
_memlock = threading.Lock()


def mem_load(owner):
    if owner["kind"] == "guest":
        return _gmem.setdefault(owner["uid"], [])
    p = MEMDIR / f"{owner['uid']}.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _mem_save(owner, items):
    if owner["kind"] == "guest":
        _gmem[owner["uid"]] = items
    else:
        (MEMDIR / f"{owner['uid']}.json").write_text(json.dumps(items))


def _norm(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


def mem_add(owner, text, source="auto"):
    """Adds one fact unless an equivalent one is already stored. Returns the stored fact, or None."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()[:240]
    if len(text) < 4:
        return None
    with _memlock:
        items = mem_load(owner)
        n = _norm(text)
        for it in items:
            m = _norm(it["text"])
            if n == m or (len(n) > 12 and (n in m or m in n)):
                return None
        item = {"id": uuid.uuid4().hex[:8], "text": text, "ts": time.time(), "src": source}
        items = (items + [item])[-MEM_MAX:]
        _mem_save(owner, items)
        return item


def mem_delete(owner, mid=None, match=None):
    with _memlock:
        items = mem_load(owner)
        if match:
            mt = _norm(match)
            keep = [i for i in items if not (mt and (mt in _norm(i["text"]) or _norm(i["text"]) in mt))]
        else:
            keep = [i for i in items if i["id"] != mid]
        _mem_save(owner, keep)
        return len(items) - len(keep)


def mem_clear(owner):
    with _memlock:
        _mem_save(owner, [])


def memory_prompt(owner):
    items = mem_load(owner)
    if not items:
        return ""
    lines, used = [], 0
    for it in reversed(items):  # newest first, so the freshest facts win when it is too long
        if used + len(it["text"]) > MEM_PROMPT_CHARS:
            break
        lines.append("- " + it["text"]); used += len(it["text"]) + 3
    return ("\n\nWhat you remember about the user from earlier chats (use it naturally when it is relevant; do not recite it or mention that you have a memory unless asked):\n"
            + "\n".join(reversed(lines)))


def search_chats(owner, query, limit=5):
    """Keyword search over the user's saved (non-incognito) chats. Returns short snippets."""
    words = [w for w in re.findall(r"\w{3,}", query.lower())][:8]
    if not words:
        return []
    pool = [c for c in _mem.get(owner["uid"], {}).values() if not c.get("incognito")]
    if owner["kind"] == "user":
        for f in _dir(owner).glob("*.json"):
            try:
                pool.append(json.loads(f.read_text()))
            except Exception:
                pass
    hits = []
    for c in pool:
        for m in c.get("messages", []):
            if m.get("role") not in ("user", "assistant") or not m.get("content"):
                continue
            low = m["content"].lower()
            score = sum(low.count(w) > 0 for w in words)
            if score:
                i = min((low.find(w) for w in words if w in low))
                hits.append((score, c.get("updated", 0), c["title"], m["role"], m["content"][max(0, i - 80):i + 220].replace("\n", " ")))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return hits[:limit]


MEMORY_TOOLS = {"remember", "forget"}
LIB_COUNT = lambda owner: 0      # set by server.py: number of searchable documents
LIB_PROMPT = lambda owner: ""    # set by server.py: system prompt line naming them
MEM_SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "string"}}}, "required": ["facts"]}


def extract_memories(owner, model, user_text, reply_text):
    """After a turn: asks the model whether the user said anything worth remembering long-term, and stores it."""
    try:
        existing = "\n".join("- " + i["text"] for i in mem_load(owner)[-60:]) or "(nothing yet)"
        sysmsg = ("You keep a long-term memory about a user. From the latest exchange, extract only durable facts about the USER that will still be useful in future chats: "
                  "their name, job or studies, location, languages, preferences and tastes, tools and projects they work on, people and pets they mention, goals, constraints, corrections to how you should behave. "
                  "Write each as one short third-person sentence starting with 'The user' (for example 'The user is a student learning Spanish'). Never guess the user's gender: avoid he, she, his and her, and use 'their' or rephrase. "
                  "Do not store: one-off questions or tasks, the content of what was asked, anything about the assistant, temporary states, secrets such as passwords or card numbers, or anything already known. "
                  "If there is nothing worth keeping, reply with an empty list. Reply with JSON: {\"facts\": [..]}.\n\nAlready remembered:\n" + existing)
        body = {"model": model, "stream": False, "think": _think_param(model, "off"), "format": MEM_SCHEMA, "options": {"temperature": 0.1, "num_predict": 400},
                "messages": [{"role": "system", "content": sysmsg},
                             {"role": "user", "content": "User said:\n" + user_text[:1500] + "\n\nAssistant replied:\n" + reply_text[:600]}]}
        req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            facts = json.loads(json.load(r)["message"]["content"]).get("facts", [])
        added = [f for f in (mem_add(owner, t) for t in facts[:4] if isinstance(t, str)) if f]
        if added and owner["kind"] != "guest":
            logbus.log("chat", f"memory: saved {len(added)} new fact(s)", owner["uid"])
    except Exception:
        pass


def _tool_remember(args, chat, owner):
    it = mem_add(owner, args.get("fact", ""), "told")
    return ("Saved to memory: " + it["text"] + ". Confirm briefly to the user.") if it else "That is already in memory (or was empty). Tell the user it is already remembered.", None


def _tool_forget(args, chat, owner):
    n = mem_delete(owner, match=args.get("fact", ""))
    return (f"Removed {n} memory item(s). Confirm briefly." if n else "Nothing in memory matched that. Tell the user you had nothing like that stored."), None


def _tool_search_chats(args, chat, owner):
    hits = search_chats(owner, args.get("query", ""))
    if not hits:
        return "No earlier chat mentions that. Say so honestly; do not guess.", None
    return "Matches from earlier chats (most relevant first):\n" + "\n".join(f"- [{t}] {role}: {snip}" for _, _, t, role, snip in hits), None


TOOL_IMPL.update({"ask_about_picture": _tool_ask_picture, "remember": _tool_remember, "forget": _tool_forget, "search_past_chats": _tool_search_chats})


# ---------- ollama helpers
# The app shows its own model names (mono, stereo); the real Ollama names stay hidden. MODEL_VERSION is kept for later upgrades.
MODEL_VERSION = 2
MODEL_FAMILY = {"qwen3:14b": "mono", "gpt-oss:20b": "stereo"}   # mono: simpler and quicker; stereo: stronger reasoning


MODEL_DESC = {"mono": "Fast. Everyday chat, quick questions and simple music requests.",
              "stereo": "Best. Deeper reasoning, long files and detailed music requests."}


def desc_for(name):
    return MODEL_DESC.get(MODEL_FAMILY.get(name), "")


def label_for(name):
    fam = MODEL_FAMILY.get(name)
    return fam if fam else name


def models():
    with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=4) as r:
        out = [{"name": m["name"], "label": label_for(m["name"]), "desc": desc_for(m["name"]), "size": m["size"], "caps": m.get("capabilities", [])} for m in json.load(r)["models"]]
    return sorted(out, key=lambda m: (m["name"] not in MODEL_FAMILY, m["name"] != "gpt-oss:20b", m["name"]))


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


STYLE_HINT = {"concise": "Keep answers short and to the point.", "detailed": "Give thorough, step-by-step answers with examples where useful.",
              "friendly": "Use a warm, casual, encouraging tone."}


def personal_prompt(p):
    """Turns the user's Settings > Personalization into a block appended to the system prompt."""
    if not isinstance(p, dict):
        return ""
    lines = []
    if str(p.get("name", "")).strip():
        lines.append(f"The user's name is {str(p['name']).strip()[:60]}.")
    if str(p.get("about", "")).strip():
        lines.append(f"About the user: {str(p['about']).strip()[:200]}.")
    if STYLE_HINT.get(p.get("style")):
        lines.append(STYLE_HINT[p["style"]])
    if str(p.get("instr", "")).strip():
        lines.append("Custom instructions from the user:\n" + str(p["instr"]).strip()[:2000])
    return ("\n\n" + "\n".join(lines)) if lines else ""


def _ollama_messages(chat, system, personal=None, memory=""):
    msgs = [{"role": "system", "content": (system or DEFAULT_SYSTEM) + personal_prompt(personal) + memory}]
    for m in chat["messages"][-MAX_TURNS:]:
        if m["role"] == "user":
            text = m["content"]
            if m.get("images"):
                if m.get("image_desc"):
                    text += ("\n\n[Attached picture. A vision model looked at it and reports:\n" + m["image_desc"] +
                             "\n]\nTreat this report as what you see in the picture and answer from it directly; never say that you cannot see the picture. "
                             "If the report lacks a detail the user asks about (sizes, positions, counts, small text), call ask_about_picture with a precise question before answering. "
                             "If they want the picture changed, call edit_picture with a clear English instruction. If their message does not say what to do with it, ask briefly what they would like and offer ideas (explain it, change something, restyle it).")
                else:
                    text += "\n[The user attached a picture. You cannot see it. Work out from their message what they want. If it clearly asks for a change, call edit_picture right away with a clear English instruction. If it does not say what to do with the picture, ask what they want instead of calling the tool.]"
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
    "caption": {"type": "string"}, "lyrics": {"type": "string"}, "length": {"type": "string", "enum": ["short", "medium", "long"]}},
    "required": ["caption", "lyrics", "length"]}


def plan_music(model, prompt, instrumental=False):
    """Turns a plain-English music request into a caption and lyrics for surround, using the chosen chat model (mono or stereo)."""
    plan = {"caption": prompt[:300], "lyrics": "", "length": "medium"}
    try:
        sysmsg = ("You prepare a request for a song-making model. " + SONG_BRIEF + CAPTION_RULES
                  + ("The song is an instrumental: lyrics is an empty string and the caption says no vocals. " if instrumental else LYRIC_RULES + "The vocal description in the caption must match the lyrics. ")
                  + "length: short (about 1 minute), medium (about 2 minutes) or long (about 3 minutes); long when the style has a long solo or is a slow epic, short only if the user asks for short. Reply with JSON only: caption, lyrics, length.")
        body = {"model": model, "stream": False, "think": _think_param(model, "off"), "format": PLAN_SCHEMA, "options": {"temperature": 0.7, "num_predict": 2500},
                "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": prompt}]}
        req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            got = json.loads(json.load(r)["message"]["content"])
        plan["caption"] = str(got.get("caption", "")).strip()[:500] or plan["caption"]
        plan["lyrics"] = "" if instrumental else str(got.get("lyrics", "")).strip()[:4000]
        plan["length"] = got.get("length") if got.get("length") in ("short", "medium", "long") else "medium"
    except Exception:
        pass  # fall back to the user's own words as the caption, instrumental
    return plan


RANDOM_GENRES = ["dreamy indie folk", "synthwave pop", "soulful blues rock", "lo-fi hip hop", "cinematic orchestral pop", "upbeat funk", "acoustic singer-songwriter", "melodic house", "alternative rock", "smooth jazz ballad",
                 "country road song", "dark trap", "shoegaze", "disco", "reggae", "gospel soul", "punk rock", "bossa nova", "post-rock", "R&B slow jam"]
RANDOM_MOODS = ["nostalgic", "hopeful", "melancholic", "playful", "defiant", "peaceful", "bittersweet", "energetic", "dreamy", "romantic", "mysterious", "triumphant"]
RANDOM_THEMES = ["driving home at night", "a summer that ended too soon", "leaving a small town", "the first snow", "a letter never sent", "dancing in the kitchen", "the city at 4 a.m.",
                 "starting over", "an old friend", "the ocean at dawn", "a long train ride", "finding your own voice", "rain on the window", "a road trip with no map", "coming home"]


def random_music(model):
    """A random song idea (genre, mood, theme chosen here), written out as caption + lyrics by the chosen chat model."""
    import random
    idea = f"A {random.choice(RANDOM_MOODS)} {random.choice(RANDOM_GENRES)} song about {random.choice(RANDOM_THEMES)}"
    plan = plan_music(model, idea + ".")
    plan["idea"] = idea + "."
    return plan


FIELD_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def write_field(model, field, prompt="", caption="", lyrics="", instrumental=False):
    """Writes just one field for the Music tab: the caption or the lyrics. An empty prompt means a random idea (or, if the other field is filled in, something that fits it)."""
    import random
    prompt = (prompt or "").strip()[:500]
    if not prompt and (field == "idea" or not (caption.strip() if field == "lyrics" else lyrics.strip())):
        prompt = f"A {random.choice(RANDOM_MOODS)} {random.choice(RANDOM_GENRES)} song about {random.choice(RANDOM_THEMES)}"
    if field == "idea":
        sysmsg = ("You write a short description of a song for a user to review: one or two sentences with the genre, mood, theme and the sound (instruments, vocals, any solo). "
                  "If the user gives rough words, an artist or a song name, use your knowledge to turn them into a concrete description without naming the artist. Reply with JSON: {\"text\": the description}.")
        user = prompt
    elif field == "caption":
        sysmsg = ("You write the caption for a song-making model. " + SONG_BRIEF + CAPTION_RULES + ("The song is an instrumental: no vocals. " if instrumental else "") + "Reply with JSON: {\"text\": the caption}.")
        user = (prompt or "Write a caption that fits these lyrics.") + (f"\n\nLyrics for context:\n{lyrics[:1500]}" if lyrics.strip() else "")
    else:
        sysmsg = ("You write song lyrics for a song-making model. " + SONG_BRIEF + LYRIC_RULES + "Reply with JSON: {\"text\": the lyrics with tags}.")
        user = (prompt or "Write lyrics that fit this sound.") + (f"\n\nThe sound of the song: {caption[:500]}" if caption.strip() else "")
    body = {"model": model, "stream": False, "think": _think_param(model, "off"), "format": FIELD_SCHEMA, "options": {"temperature": 0.8, "num_predict": 2500},
            "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]}
    req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        text = str(json.loads(json.load(r)["message"]["content"]).get("text", "")).strip()
    if not text:
        raise ValueError("The model returned nothing. Try again.")
    return text[:500] if field in ("caption", "idea") else text[:4000]


SONG_BRIEF = (
    "The request can be very short: only an artist, a song title, a genre or a few words (for example 'dire straits', 'brothers in arms' or 'a song like brothers in arms'). Never ask questions and never say you do not know it. "
    "Use your own knowledge of that artist, song or genre to work out its musical character: era, tempo, mood, instruments, the signature guitar or lead-instrument tone, the vocal style, how the song is built and how long its instrumental or solo sections run. Then write a detailed, concrete result from that. "
    "Describe the sound in words and never put an artist or song name into the caption. The lyrics must be completely original (same mood and kind of theme, different words); never copy or paraphrase existing lyrics. "
    "If the style is known for a solo (guitar, saxophone, piano, synth), give it its own long section and describe its tone in the caption. "
)
CAPTION_RULES = (
    "Caption: one line of comma-separated descriptors, 40 to 70 words, English, no labels. Cover genre and era, tempo with a bpm, mood, each instrument with its tone (for example 'clean Stratocaster-style guitar with a bright, compressed, singing tone'), drums, bass, keys or pads, "
    "the vocal type (or none), the production feel, and, if there is a solo, the instrument, its tone, its phrasing (sustained bends, slow vibrato, delay, reverb) and that it is long (about a minute) and builds to a climax. "
)
LYRIC_RULES = (
    "Lyrics: 24 to 40 sung lines in the language the user wrote in, with section tags on their own lines. Use these tags: [Intro], [Verse], [Pre-Chorus], [Chorus], [Bridge], [Outro], and for solos a tag with the instrument and tone such as [Guitar Solo - electric - overdriven, soulful]. "
    "Tags can carry a short style hint, e.g. [Verse - soft, half-spoken] or [Chorus - anthemic]. Put nothing under an instrumental or solo tag. If the style has a solo, include a [Guitar Solo ...] (or the fitting instrument) section, usually after the second chorus, and let the song fade or resolve in an [Outro]. "
)


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
    lib_n = LIB_COUNT(owner)
    use_memory = bool(body.get("memory", True)) and not quiet   # incognito chats neither read nor write memory
    think = _think_param(model, body.get("think"))
    cards = []
    try:
        lu = next((m for m in reversed(chat["messages"]) if m["role"] == "user"), None)
        if lu and lu.get("images") and not lu.get("image_desc") and vision_model():
            # the chat models cannot see: a vision model describes the new picture once, and its report goes into the message
            write({"type": "tool_start", "name": "look_at_picture", "args": {}})
            hint = lu["content"] if lu["content"] not in ("(picture attached)", "") else ""
            try:
                lu["image_desc"] = look(lu["images"][-1], DESCRIBE_PROMPT + (f"\nThe user wrote this with the picture, so pay attention to what it needs: {hint[:400]}" if hint else ""))
                note = "Looked at the picture"
            except Exception as e:
                lu["image_desc"] = ""
                note = f"Could not look at the picture: {e}"
            save(owner, chat)
            write({"type": "tool_result", "name": "look_at_picture", "text": note, "card": None})
            log("chat", f"vision model looked at the picture ({len(lu.get('image_desc') or '')} characters)")
        has_pic = any(m.get("images") for m in chat["messages"])
        tools_now = [t for t in TOOLS
                     if (use_memory or t["function"]["name"] not in MEMORY_TOOLS)
                     and (t["function"]["name"] != "search_documents" or lib_n)
                     and (t["function"]["name"] != "ask_about_picture" or (has_pic and vision_model()))]
        for _round in range(4):
            req_body = {"model": model, "messages": _ollama_messages(chat, body.get("system"), body.get("personal"), (memory_prompt(owner) if use_memory else "") + LIB_PROMPT(owner)), "stream": True,
                        "keep_alive": "2m", "options": {"temperature": float(body.get("temperature", 0.7)), "num_ctx": 16384}}
            if use_tools:
                req_body["tools"] = tools_now
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
        if use_memory and not cancel_flags.get(chat["id"]):
            u = next((m["content"] for m in reversed(chat["messages"]) if m["role"] == "user"), "")
            a = next((m["content"] for m in reversed(chat["messages"]) if m["role"] == "assistant" and m.get("content")), "")
            if len(u) >= 12 and u != "(picture attached)":
                threading.Thread(target=extract_memories, args=(owner, model, u, a), daemon=True).start()
    except Exception as e:
        write({"type": "error", "message": f"{type(e).__name__}: {e}"})
        log("chat", f"ERROR {type(e).__name__}: {e}")
    finally:
        save(owner, chat)
        if first_turn and chat["title"] == "New chat":
            threading.Thread(target=_auto_title, args=(owner, chat["id"], model, True), daemon=True).start()
