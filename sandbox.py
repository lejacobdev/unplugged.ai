"""Runs Python code the model writes, in a locked-down process: no network, writes only to a fresh work folder,
cannot read the rest of your home folder (chats, accounts, documents), time and size limited.
Uses macOS sandbox-exec and the separate .venv-code environment (numpy, pandas, matplotlib, scipy, sympy, openpyxl, python-docx, python-pptx, fpdf2, Pillow)."""
import os
import re
import resource
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"
RUNS.mkdir(exist_ok=True)
PY = ROOT / ".venv-code" / "bin" / "python"
TIMEOUT = 30
MAX_OUT = 8000
MAX_FILE = 25 * 1024 * 1024
MAX_FILES = 20
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def available():
    return PY.exists() and Path("/usr/bin/sandbox-exec").exists()


def _profile(work):
    home = str(Path.home())
    pyhome = str(Path(os.path.realpath(PY)).parent.parent)
    venv = str(ROOT / ".venv-code")
    q = lambda p: '"' + str(p).replace('"', '') + '"'
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath {q(work)}) (literal "/dev/null") (literal "/dev/dtracehelper"))
(deny file-read* (subpath {q(home)}))
(allow file-read-metadata (subpath {q(home)}))
(allow file-read* (subpath {q(venv)}) (subpath {q(pyhome)}) (subpath {q(work)}))
"""


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT, TIMEOUT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


def _dir(owner):
    d = RUNS / owner["uid"]
    d.mkdir(exist_ok=True)
    return d


def run(owner, code):
    """Returns {id, ok, stdout, stderr, files:[{name,size,image}], seconds}."""
    if not available():
        raise RuntimeError("The code sandbox is not set up. Run setup_extras.sh (see the README).")
    rid = uuid.uuid4().hex[:10]
    work = (_dir(owner) / rid).resolve()
    work.mkdir()
    (work / "main.py").write_text(code)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "TMPDIR": str(work), "MPLCONFIGDIR": str(work / ".mpl"), "MPLBACKEND": "Agg",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "LANG": "en_US.UTF-8"}
    t0 = time.time()
    try:
        p = subprocess.run(["/usr/bin/sandbox-exec", "-p", _profile(work), str(PY), "-I", "main.py"], cwd=work, env=env, capture_output=True,
                           timeout=TIMEOUT + 5, preexec_fn=_limits)
        out, err, ok = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"), p.returncode == 0
        if p.returncode in (-24, -9, -signal_xcpu()):
            err += f"\nStopped: the code ran longer than {TIMEOUT} seconds."
    except subprocess.TimeoutExpired as e:
        out, err, ok = (e.stdout or b"").decode("utf-8", "replace"), (e.stderr or b"").decode("utf-8", "replace") + f"\nStopped: the code ran longer than {TIMEOUT} seconds.", False
    files = []
    for f in sorted(work.iterdir()):
        if f.is_file() and f.name != "main.py" and not f.name.startswith(".") and f.stat().st_size <= MAX_FILE:
            files.append({"name": f.name, "size": f.stat().st_size, "image": f.suffix.lower() in IMG_EXT})
    for extra in work.iterdir():
        if extra.name == ".mpl":
            shutil.rmtree(extra, ignore_errors=True)
    cut = lambda t: t if len(t) <= MAX_OUT else t[:MAX_OUT // 2] + "\n... (cut) ...\n" + t[-MAX_OUT // 2:]
    return {"id": rid, "ok": ok, "stdout": cut(out), "stderr": cut(err), "files": files[:MAX_FILES], "seconds": round(time.time() - t0, 1)}


def signal_xcpu():
    import signal
    return int(signal.SIGXCPU)


def make_document(owner, fmt, title, markdown):
    """Converts Markdown into a downloadable file (docx, pdf, pptx, xlsx, csv, md). Returns {id, files}."""
    if fmt not in ("docx", "pdf", "pptx", "xlsx", "csv", "md"):
        raise ValueError("Format must be one of docx, pdf, pptx, xlsx, csv, md.")
    if not PY.exists():
        raise RuntimeError("The document tools are not set up. See the README (extras).")
    rid = uuid.uuid4().hex[:10]
    work = (_dir(owner) / rid).resolve()
    work.mkdir()
    name = (re.sub(r"[^\w .-]+", "", title or "document").strip()[:60] or "document") + "." + fmt
    src = work / ".src.md"
    src.write_text(markdown)
    p = subprocess.run([str(PY), "-I", str(ROOT / "exportdoc.py"), fmt, str(src), str(work / name), title or ""], capture_output=True, timeout=60)
    src.unlink(missing_ok=True)
    if p.returncode != 0 or not (work / name).exists():
        raise RuntimeError("Could not make the file: " + p.stderr.decode("utf-8", "replace")[-300:])
    return {"id": rid, "name": name, "files": [{"name": name, "size": (work / name).stat().st_size, "image": False}]}


def file_path(owner, rid, name):
    """Path of a file a run produced, or None. Only inside this owner's own run folder."""
    if not re.match(r"^[a-f0-9]{10}$", rid or "") or not name or "/" in name or name.startswith("."):
        return None
    f = _dir(owner) / rid / name
    return f if f.is_file() else None


def purge_owner(owner):
    shutil.rmtree(RUNS / owner["uid"], ignore_errors=True)
