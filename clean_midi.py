"""Clean raw MIDI into piano + electric-guitar-only files, sorted into training groups.

Groups written under data/clean/:
  base_lakh/, base_maestro/   general pretraining data
  mine_core/                  exact versions of the songs in songs.md
  mine_style/                 other songs by artists you like
Each file is named  <artist>__<title>__<n>.mid  so splits can be made per song.
"""
import re
import sys
from multiprocessing import Pool
from pathlib import Path

from symusic import Score

ROOT = Path(__file__).parent
LAKH = ROOT / "data/lakh/clean_midi"
MAESTRO = ROOT / "data/base_midi"
OUT = ROOT / "data/clean"

# program remap: piano family -> 0 / 4 (electric piano); electric guitar -> 27 clean / 29 driven
PROGRAM_MAP = {0: 0, 1: 0, 2: 0, 3: 0, 4: 4, 5: 4, 26: 27, 27: 27, 28: 27, 29: 29, 30: 29}

CORE = {  # artist folder in Lakh -> regexes matching title (lowercase, no punctuation)
    "Dire Straits": [r"brothers in arms", r"telegraph road"],
    "Pink Floyd": [r"comfortably numb", r"wish you were here"],
    "Roger Waters": [r"tide is turning"],
    "Prince": [r"purple rain"],
    "Bryan Adams": [r"^heaven"],
    "The Police": [r"every breath you take"],
    "Sting": [r"russians", r"every breath you take"],
    "Bonnie Tyler": [r"total eclipse of (my|the) heart"],
    "Phil Collins": [r"another day in paradise", r"in the air tonight"],
    "Chris Isaak": [r"wicked game"],
    "U2": [r"with or without you", r"i still havent found"],
    "R.E.M.": [r"losing my religion"],
    "Oasis": [r"dont look back in anger"],
    "Radiohead": [r"karma police"],
    "Billy Joel": [r"piano man"],
    "John Lennon": [r"^imagine"],
    "George Michael": [r"dont let the sun go down on me"],
    "Elton John": [r"dont let the sun go down on me"],
    "The Mamas & The Papas": [r"california dreamin"],
}
STYLE_ARTISTS = [
    "Dire Straits", "Pink Floyd", "Roger Waters", "Prince", "Bryan Adams", "The Police", "Sting",
    "Bonnie Tyler", "Phil Collins", "Chris Isaak", "U2", "R.E.M.", "Oasis", "Radiohead",
    "Billy Joel", "John Lennon", "George Michael", "Elton John", "Eric Clapton", "Mark Knopfler",
    "Genesis", "Peter Gabriel", "Supertramp", "Eagles", "Journey", "Bruce Springsteen", "Bon Jovi",
    "Santana", "Simon & Garfunkel", "Coldplay", "Queen", "David Bowie", "Fleetwood Mac",
]


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower().replace("'", ""))).strip()


def title_of(path: Path):
    return re.sub(r"\.\d+$", "", path.stem)


def clean(args):
    src, dst = args
    try:
        score = Score(str(src))
        tracks = []
        for t in score.tracks:
            if t.is_drum or t.program not in PROGRAM_MAP or len(t.notes) < 24:
                continue
            t.program = PROGRAM_MAP[t.program]
            tracks.append(t)
        if not tracks or score.end() < score.ticks_per_quarter * 16:
            return 0
        n_notes = sum(len(t.notes) for t in tracks)
        if n_notes < 200:
            return 0
        score.tracks = tracks
        dst.parent.mkdir(parents=True, exist_ok=True)
        score.dump_midi(str(dst))
        return 1
    except Exception:
        return 0


def jobs():
    out = []
    for p in sorted(MAESTRO.rglob("*.mid*")):
        out.append((p, OUT / "base_maestro" / f"maestro__{p.stem}__0.mid"))
    seen_core = set()
    for artist_dir in sorted(LAKH.iterdir()):
        if not artist_dir.is_dir():
            continue
        artist = artist_dir.name
        pats = [re.compile(x) for x in CORE.get(artist, [])]
        for p in sorted(artist_dir.glob("*.mid")):
            title = norm(title_of(p))
            name = f"{artist.replace('/', '-')}__{title_of(p).replace('/', '-')}__{p.stem[len(title_of(p)):].strip('.') or '0'}.mid"
            if any(r.search(title) for r in pats):
                group = "mine_core"
                seen_core.add(p)
            elif artist in STYLE_ARTISTS:
                group = "mine_style"
            else:
                group = "base_lakh"
            out.append((p, OUT / group / name))
    return out


if __name__ == "__main__":
    js = jobs()
    if len(sys.argv) > 1 and sys.argv[1] == "--list-core":
        for s, d in js:
            if d.parent.name == "mine_core":
                print(d.name)
        sys.exit()
    with Pool() as pool:
        ok = pool.map(clean, js, chunksize=64)
    counts = {}
    for (s, d), o in zip(js, ok):
        if o:
            counts[d.parent.name] = counts.get(d.parent.name, 0) + 1
    print("kept files per group:", counts)
