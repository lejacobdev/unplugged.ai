"""Your document library: files you add are split into passages, turned into vectors by a small local embedding model
(through Ollama) and searched by meaning. The chat models use it through the search_documents tool.
Everything stays on this Mac. Guests keep their library in memory only (it is deleted with the guest session)."""
import json
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np

import chat
import logbus

ROOT = Path(__file__).parent
LIBDIR = ROOT / "library"
LIBDIR.mkdir(exist_ok=True)
EMBED_MODEL = "nomic-embed-text"
CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
MAX_CHUNKS = 3000
MAX_DOCS = 200
_lock = threading.Lock()
_gdocs: dict = {}    # guest uid -> {doc_id: doc}
_cache: dict = {}    # uid -> (matrix, meta) built from the ready documents


def _dir(owner):
    d = LIBDIR / owner["uid"]
    d.mkdir(exist_ok=True)
    return d


def _docs(owner):
    """All documents of this account, including ones still being indexed."""
    if owner["kind"] == "guest":
        return _gdocs.setdefault(owner["uid"], {})
    out = {}
    for f in _dir(owner).glob("*.json"):
        try:
            d = json.loads(f.read_text())
            out[d["id"]] = d
        except Exception:
            pass
    return out


def _save(owner, doc):
    _cache.pop(owner["uid"], None)
    if owner["kind"] == "guest":
        _gdocs.setdefault(owner["uid"], {})[doc["id"]] = doc
    else:
        (_dir(owner) / f"{doc['id']}.json").write_text(json.dumps(doc))


def embed(texts, prefix):
    """Vectors from the local embedding model. nomic-embed-text wants a task prefix on every text."""
    out = []
    for i in range(0, len(texts), 16):
        batch = [prefix + t for t in texts[i:i + 16]]
        body = {"model": EMBED_MODEL, "input": batch, "truncate": True, "keep_alive": "2m"}
        req = urllib.request.Request(chat.OLLAMA + "/api/embed", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out += json.load(r)["embeddings"]
    return out


def chunk(text):
    """Passages of about CHUNK_CHARS characters, cut at paragraph or sentence ends, with a little overlap."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces = []
    for p in parts:   # very long paragraphs are cut at sentence ends
        while len(p) > CHUNK_CHARS * 1.3:
            cut = max(p.rfind(". ", 0, CHUNK_CHARS), p.rfind("\n", 0, CHUNK_CHARS), p.rfind(" ", 0, CHUNK_CHARS))
            cut = cut + 1 if cut > CHUNK_CHARS // 3 else CHUNK_CHARS
            pieces.append(p[:cut].strip()); p = p[cut:].strip()
        if p:
            pieces.append(p)
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 2 > CHUNK_CHARS:
            chunks.append(cur)
            cur = cur[-CHUNK_OVERLAP:].split(" ", 1)[-1] + "\n\n" + p if CHUNK_OVERLAP else p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur.strip():
        chunks.append(cur)
    return chunks[:MAX_CHUNKS]


def _index(owner, doc, text):
    try:
        chunks = chunk(text)
        if not chunks:
            raise ValueError("no readable text in this file")
        vecs = embed(chunks, "search_document: ")
        doc["chunks"] = [{"t": t, "v": [round(float(x), 5) for x in v]} for t, v in zip(chunks, vecs)]
        doc["status"], doc["n"] = "ready", len(chunks)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "404" in msg or "not found" in msg.lower():
            msg = f"The embedding model is not installed. Run: ollama pull {EMBED_MODEL}"
        doc["status"], doc["error"], doc["chunks"], doc["n"] = "error", msg, [], 0
    _save(owner, doc)
    if owner["kind"] != "guest":
        logbus.log("library", f"{doc['name']}: {doc['status']} ({doc.get('n', 0)} passages)" + (f" - {doc.get('error')}" if doc.get("error") else ""), owner["uid"])


def add(owner, name, data):
    """Adds one file. Returns the document record at once; indexing continues in the background."""
    if len(_docs(owner)) >= MAX_DOCS:
        raise ValueError(f"The library is full ({MAX_DOCS} documents). Delete some first.")
    kind, text, note = chat.extract_text(name, data)
    if not text.strip():
        raise ValueError(f"No readable text in {name} ({note or kind}).")
    doc = {"id": uuid.uuid4().hex[:10], "name": name, "kind": kind, "size": len(data), "added": time.time(), "note": note,
           "chars": len(text), "status": "indexing", "n": 0, "chunks": []}
    _save(owner, doc)
    threading.Thread(target=_index, args=(owner, doc, text), daemon=True).start()
    return public(doc)


def public(d):
    return {k: d.get(k) for k in ("id", "name", "kind", "size", "added", "note", "chars", "status", "n", "error")}


def list_docs(owner):
    return sorted((public(d) for d in _docs(owner).values()), key=lambda d: d["added"], reverse=True)


def count(owner):
    return sum(1 for d in _docs(owner).values() if d.get("status") == "ready")


def delete(owner, doc_id):
    if not re.match(r"^[a-f0-9]{10}$", doc_id or ""):
        raise ValueError("bad document id")
    _cache.pop(owner["uid"], None)
    if owner["kind"] == "guest":
        _gdocs.get(owner["uid"], {}).pop(doc_id, None)
    else:
        (_dir(owner) / f"{doc_id}.json").unlink(missing_ok=True)


def purge_owner(owner):
    _gdocs.pop(owner["uid"], None)
    _cache.pop(owner["uid"], None)


def _matrix(owner):
    hit = _cache.get(owner["uid"])
    if hit:
        return hit
    vecs, meta = [], []
    for d in _docs(owner).values():
        if d.get("status") != "ready":
            continue
        for i, c in enumerate(d["chunks"]):
            vecs.append(c["v"]); meta.append((d["id"], d["name"], i, c["t"]))
    if not vecs:
        _cache[owner["uid"]] = (None, [])
        return _cache[owner["uid"]]
    m = np.asarray(vecs, dtype=np.float32)
    m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    _cache[owner["uid"]] = (m, meta)
    return _cache[owner["uid"]]


def search(owner, query, k=5, per_doc=3):
    """Best passages for a question: [{doc, name, passage, text, score}]."""
    m, meta = _matrix(owner)
    if m is None:
        return []
    q = np.asarray(embed([query[:500]], "search_query: ")[0], dtype=np.float32)
    q /= (np.linalg.norm(q) + 1e-9)
    scores = m @ q
    out, used = [], {}
    for i in np.argsort(-scores):
        did, name, idx, text = meta[i]
        if used.get(did, 0) >= per_doc:
            continue
        used[did] = used.get(did, 0) + 1
        out.append({"doc": did, "name": name, "passage": idx + 1, "text": text, "score": round(float(scores[i]), 3)})
        if len(out) >= k:
            break
    return out


def prompt_block(owner):
    """A line for the system prompt naming the documents the model can search."""
    names = [d["name"] for d in _docs(owner).values() if d.get("status") == "ready"]
    if not names:
        return ""
    shown = ", ".join(names[:25]) + (f" and {len(names) - 25} more" if len(names) > 25 else "")
    return ("\n\nThe user has a library of their own documents that you can search with the search_documents tool: " + shown +
            ". Use the tool whenever the question may be answered by their documents (also when they say 'my notes', 'the file', 'the contract' or similar), "
            "answer only from the passages it returns, and say which document a fact comes from. If the passages do not contain the answer, say so.")
