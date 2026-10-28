"""Offline image editing with FLUX.1 Kontext [dev] (via mflux / Apple MLX), used by the dashboard.

The model is quantized to 8-bit once and stored in models/kontext-q8 (see setup_image_model.sh).
Edits then run entirely from that local folder with Hugging Face access switched off.
KONTEXT_STUB=1 swaps in a fake generator so the dashboard flow can be tested without the weights.
"""
import base64
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import shutil

from PIL import Image, ImageOps

import logbus

ROOT = Path(__file__).parent
DIR = ROOT / "image_edits"
MODEL_DIR = ROOT / "models/kontext-q8"
BIN = ROOT / ".venv-img/bin/mflux-generate-kontext"
STUB = os.environ.get("KONTEXT_STUB") == "1"
DIR.mkdir(exist_ok=True)
LORA_DIR = ROOT / "loras"
LORA_DIR.mkdir(exist_ok=True)
LORA_RE = re.compile(r"^[A-Za-z0-9_\-. ]{1,100}\.safetensors$")

PRESERVE = (" Keep the exact same subject, identity, face, pose, framing, camera angle, lighting, colors and "
            "background. Change only what is described, and keep the result photorealistic.")
STEPS = {"standard": 28, "high": 40, "maximum": 60}
jobs: dict = {}
procs: dict = {}
lock = threading.Lock()
FILE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(png|jpg)$")
ID_RE = re.compile(r"^[A-Za-z0-9]+$")


def status():
    ready = STUB or (MODEL_DIR.exists() and any(MODEL_DIR.rglob("*.safetensors")))
    return {"ready": bool(ready), "stub": STUB, "installed_tool": BIN.exists() or STUB}


def _prepare(data_url: str, max_side: int):
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    w, h = img.size
    s = max_side / max(w, h)
    nw, nh = max(256, round(w * s / 16) * 16), max(256, round(h * s / 16) * 16)
    return img.resize((nw, nh), Image.LANCZOS), nw, nh


STUB_CODE = """
import sys, time
from PIL import Image, ImageEnhance
src, out, steps = sys.argv[1], sys.argv[2], int(sys.argv[3])
for i in range(1, steps + 1):
    time.sleep(0.15); print(f"{i}/{steps}", file=sys.stderr, flush=True)
im = ImageEnhance.Color(Image.open(src)).enhance(1.6); im.save(out)
"""


def _run(job_id, p, in_png, w, h):
    job = jobs[job_id]
    L = lambda text: logbus.log("img", text, job.get("owner"))
    try:
        with lock:
            job["status"] = "running"
            for k, seed in enumerate(job["seeds"]):
                job["variation"] = k + 1
                job["step"] = 0
                out = DIR / f"{job_id}_{k}.png"
                if STUB:
                    cmd = [sys.executable, "-c", STUB_CODE, str(in_png), str(out), str(job["steps"])]
                else:
                    cmd = [str(BIN), "--model", str(MODEL_DIR), "--base-model", "dev-kontext",
                           "--image-path", str(in_png), "--prompt", job["full_prompt"], "--steps", str(job["steps"]),
                           "--guidance", str(p["guidance"]), "--seed", str(seed), "--width", str(w), "--height", str(h),
                           "--output", str(out)]
                    for lp, ls in p.get("loras", []):
                        cmd += ["--lora", lp, str(ls)]
                steps_dir = DIR / f"{job_id}_steps_{k}"
                if p.get("live_preview", True) and not STUB:
                    steps_dir.mkdir(exist_ok=True)
                    cmd += ["--stepwise-image-output-dir", str(steps_dir)]
                if p.get("low_ram", True) and not STUB:
                    cmd += ["--low-ram"]
                env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
                L(f"--- variation {k + 1}/{len(job['seeds'])}  seed {seed}  {w}x{h}  {job['steps']} steps  guidance {p['guidance']}")
                L(f"prompt: {job['full_prompt']}")
                if p.get("loras"):
                    L("LoRAs: " + ", ".join(f"{os.path.basename(a)} x{b}" for a, b in p["loras"]))
                L("starting the image model (loading ~12 GB from disk, fully offline)...")
                t_var = time.time()
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
                procs[job_id] = proc
                stop_watch = threading.Event()

                def watch(steps_dir=steps_dir):
                    seen = None
                    while not stop_watch.is_set():
                        try:
                            pngs = sorted(steps_dir.glob("*step*of*.png"), key=lambda q: q.stat().st_mtime)
                            if pngs and pngs[-1].name != seen and pngs[-1].stat().st_size > 0:
                                seen = pngs[-1].name
                                tmp = DIR / f"{job_id}_preview.tmp.png"
                                shutil.copyfile(pngs[-1], tmp)
                                os.replace(tmp, DIR / f"{job_id}_preview.png")
                                job["preview"] = f"{job_id}_preview.png"
                                job["preview_n"] = len(pngs)
                                L(f"preview updated: {pngs[-1].name}")
                        except Exception:
                            pass
                        stop_watch.wait(1.0)

                threading.Thread(target=watch, daemon=True).start()
                buf, tail, last_logged = b"", [], -1
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        break
                    if ch in (b"\r", b"\n"):
                        line = buf.decode(errors="ignore").strip()
                        buf = b""
                        if line:
                            line = re.sub(r"INFO: (Image saved|Metadata embedded).*$", "", line).strip()
                            if not line:
                                continue
                            tail = (tail + [line])[-12:]
                            is_bar = "it/s]" in line or "s/it]" in line
                            for a, b in re.findall(r"\b(\d+)/(\d+)\b", line):
                                if int(b) == job["steps"]:
                                    job["step"] = int(a)
                            if not is_bar or job["step"] != last_logged:
                                last_logged = job["step"] if is_bar else last_logged
                                L(re.sub(r"\s+", " ", line) if is_bar else line)
                    else:
                        buf += ch
                proc.wait()
                stop_watch.set()
                L(f"variation {k + 1} finished in {(time.time() - t_var) / 60:.1f} min (exit code {proc.returncode})")
                if steps_dir.exists():
                    shutil.rmtree(steps_dir, ignore_errors=True)
                if job.get("cancelled"):
                    job["status"], job["message"] = "cancelled", "Cancelled"
                    return
                if proc.returncode != 0 or not out.exists():
                    job["status"] = "error"
                    job["message"] = "The image model failed:\n" + "\n".join(tail[-6:])
                    return
                job["results"].append(out.name)
                job["elapsed_per"] = (time.time() - job["started"]) / (k + 1)
            job["status"], job["message"] = "done", "Done"
            meta = {k: job[k] for k in ("prompt", "full_prompt", "steps", "seeds", "results", "input", "size", "created")}
            meta["guidance"] = p["guidance"]
            meta["owner"] = job["owner"]
            if not job["ephemeral"]:
                (DIR / f"{job_id}.json").write_text(json.dumps(meta))
    except Exception as e:
        job["status"], job["message"] = "error", f"{type(e).__name__}: {e}"


def start_edit(p: dict):
    st = status()
    if not st["ready"]:
        raise ValueError("The image model isn't installed yet. Run setup_image_model.sh first.")
    prompt = (p.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Write what you want changed first.")
    img, w, h = _prepare(p["image"], max(512, min(int(p.get("max_side", 1024)), 1536)))
    owner = p["owner"]
    ephemeral = bool(p.get("ephemeral")) or owner["kind"] == "guest"
    job_id = ("t" if ephemeral else "") + uuid.uuid4().hex[:10]
    in_png = DIR / f"{job_id}_input.png"
    img.save(in_png)
    n = max(1, min(int(p.get("variations", 1)), 4))
    seed0 = int(p["seed"]) if str(p.get("seed", "")).strip() else int(time.time()) % 1_000_000
    p["guidance"] = max(1.0, min(float(p.get("guidance", 2.5)), 6.0))
    use = [l for l in lora_list(owner) if l["active"]]
    if use:
        r = _reg(owner)
        for l in use:
            r[l["name"]]["last_used"] = time.time()
        _save_reg(owner, r)
    p["loras"] = [(str(_ldir(owner) / l["name"]), l["scale"]) for l in use]
    jobs[job_id] = {
        "status": "queued", "owner": owner["uid"], "ephemeral": ephemeral, "message": "", "step": 0, "variation": 0, "variations": n,
        "steps": STEPS.get(p.get("quality", "high"), 40), "seeds": [seed0 + i for i in range(n)],
        "prompt": prompt, "full_prompt": prompt + (PRESERVE if p.get("preserve", True) else ""),
        "results": [], "preview": None, "preview_n": 0, "input": in_png.name, "size": [w, h], "created": time.time(), "started": time.time(),
    }
    if ephemeral:
        owner["temp_files"].add(job_id)
    threading.Thread(target=_run, args=(job_id, p, in_png, w, h), daemon=True).start()
    return job_id


def history(owner):
    out = []
    for f in sorted(DIR.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        try:
            m = json.loads(f.read_text())
            if m.get("owner") != owner["uid"]:
                continue
            m["id"] = f.stem
            out.append(m)
        except Exception:
            pass
    for jid, j in jobs.items():  # guest / incognito edits are never written to disk history
        if j.get("ephemeral") and j.get("owner") == owner["uid"] and j.get("status") == "done":
            m = {k: j[k] for k in ("prompt", "full_prompt", "steps", "seeds", "results", "input", "size", "created")}
            m["id"] = jid
            out.append(m)
    return sorted(out, key=lambda m: m["created"], reverse=True)


def job_for(owner, job_id):
    j = jobs.get(job_id)
    return j if j and j.get("owner") == owner["uid"] else None


def cancel(owner, job_id):
    job = job_for(owner, job_id)
    if job:
        job["cancelled"] = True
        pr = procs.get(job_id)
        if pr and pr.poll() is None:
            pr.terminate()


def delete(owner, job_id):
    if not ID_RE.match(job_id):
        raise ValueError("bad id")
    meta = DIR / f"{job_id}.json"
    ok = False
    if meta.exists():
        try:
            ok = json.loads(meta.read_text()).get("owner") == owner["uid"]
        except Exception:
            ok = False
    elif job_for(owner, job_id):
        ok = True
    if not ok:
        raise ValueError("not your picture")
    for f in DIR.glob(f"{job_id}*"):
        f.unlink()


def purge_owner(owner):
    for jid in list(owner.get("temp_files", [])):
        pr = procs.get(jid)
        if pr and pr.poll() is None:
            pr.terminate()
        for f in DIR.glob(f"{jid}*"):
            f.unlink(missing_ok=True)
        jobs.pop(jid, None)
    for f in DIR.glob(f"tchat_*"):
        pass  # chat uploads are removed by chat.purge_owner
    import shutil as _sh
    _sh.rmtree(LORA_DIR / f"tmp_{owner['uid']}", ignore_errors=True)


def sweep_temp():
    """Server start: remove leftovers of guest/incognito sessions from a previous run."""
    for f in list(DIR.glob("t*")) + list(DIR.glob("tchat_*")):
        if f.is_file():
            f.unlink(missing_ok=True)
    import shutil as _sh
    for d in LORA_DIR.glob("tmp_*"):
        _sh.rmtree(d, ignore_errors=True)


def image_path(name):
    if not FILE_RE.match(name) or not (DIR / name).exists():
        raise FileNotFoundError(name)
    return DIR / name


# ---------- LoRAs (extra style/subject adapters for the image model), stored per account
def _ldir(owner):
    d = LORA_DIR / (f"tmp_{owner['uid']}" if owner["kind"] == "guest" else owner["uid"])
    d.mkdir(exist_ok=True)
    return d


def _reg(owner):
    try:
        return json.loads((_ldir(owner) / "registry.json").read_text())
    except Exception:
        return {}


def _save_reg(owner, r):
    (_ldir(owner) / "registry.json").write_text(json.dumps(r))


def lora_list(owner):
    r = _reg(owner)
    out = []
    for f in _ldir(owner).glob("*.safetensors"):
        m = r.get(f.name, {})
        out.append({"name": f.name, "mb": round(f.stat().st_size / 1e6, 1), "active": bool(m.get("active")),
                    "scale": m.get("scale", 1.0), "last_used": m.get("last_used", 0)})
    return sorted(out, key=lambda x: (-x["last_used"], x["name"]))


def lora_save_stream(owner, name, length, rfile):
    name = os.path.basename(name or "").strip()
    if not LORA_RE.match(name):
        raise ValueError("Use a .safetensors file (letters, numbers, - _ . and spaces in the name).")
    d = _ldir(owner)
    tmp = d / (name + ".part")
    left = length
    with open(tmp, "wb") as f:
        while left > 0:
            chunk = rfile.read(min(1 << 20, left))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    if left:
        tmp.unlink(missing_ok=True)
        raise ValueError("Upload was cut off, try again.")
    os.replace(tmp, d / name)
    r = _reg(owner)
    r.setdefault(name, {"active": True, "scale": 1.0, "last_used": time.time()})
    _save_reg(owner, r)
    logbus.log("img", f"LoRA uploaded: {name} ({(d / name).stat().st_size / 1e6:.0f} MB)", owner["uid"])
    return name


def lora_set(owner, name, active=None, scale=None):
    if not LORA_RE.match(name or "") or not (_ldir(owner) / name).exists():
        raise ValueError("unknown LoRA")
    r = _reg(owner)
    m = r.setdefault(name, {"active": False, "scale": 1.0, "last_used": 0})
    if active is not None:
        m["active"] = bool(active)
    if scale is not None:
        m["scale"] = max(0.0, min(float(scale), 2.0))
    _save_reg(owner, r)


def lora_delete(owner, name):
    if not LORA_RE.match(name or ""):
        raise ValueError("bad name")
    (_ldir(owner) / name).unlink(missing_ok=True)
    r = _reg(owner)
    r.pop(name, None)
    _save_reg(owner, r)


# ---------- automatic quality choice (used when the user doesn't say which quality they want)
def image_kind(path):
    """'photo' for real-world pictures, 'graphic' for cartoons, flat art, logos and renders with few colors."""
    im = Image.open(path).convert("RGB")
    im.thumbnail((256, 256))
    px = list(im.getdata())
    colors = len({(r >> 3, g >> 3, b >> 3) for r, g, b in px})
    w, h = im.size
    data = im.load()
    flat = total = 0
    for y in range(0, h - 1, 2):
        for x in range(0, w - 1, 2):
            a, b = data[x, y], data[x + 1, y]
            d = abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
            total += 1
            flat += d < 6
    flat_ratio = flat / max(total, 1)
    return "graphic" if colors < 700 or flat_ratio > 0.72 else "photo", colors, round(flat_ratio, 2)


COMPLEX_RE = re.compile(r"background|replace|style|relight|lighting|face|portrait|skin|hair|expression|older|younger|season|weather|"
                        r"reflection|shadow|realistic|multiple|every|all the|transform|turn (it|him|her|them) into|\band\b.*\band\b")


def auto_quality(path, instruction):
    kind, colors, flat = image_kind(path)
    words = len(instruction.split())
    complex_task = words > 18 or bool(COMPLEX_RE.search(instruction.lower()))
    if kind == "photo":
        q, size = ("maximum", 1280) if complex_task else ("high", 1024)
    else:
        q, size = ("standard", 1024) if complex_task else ("standard", 768)
    why = f"{'photo' if kind == 'photo' else 'cartoon/graphic'} ({colors} colors), {'complex' if complex_task else 'simple'} task"
    return q, size, why
