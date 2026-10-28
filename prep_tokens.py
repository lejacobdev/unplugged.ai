"""Train the BPE tokenizer on the cleaned MIDI, then tokenize every group into windows.

Output: data/tok_<group>.npz with arrays  windows [N, SEQ_LEN], song [N] (song key ids), keys (names)
Pitch-transposition augmentation is applied at tokenization time (SHIFTS below).
"""
import random
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from symusic import Score

import common
from common import BPE_VOCAB, SEQ_LEN, TOKENIZER_PATH, make_tokenizer

CLEAN = common.ROOT / "data/clean"
DATA = common.ROOT / "data"
SHIFTS = {
    "base_lakh": [0],
    "base_maestro": [0],
    "mine_core": list(range(-4, 5)),
    "mine_style": [-2, 0, 2],
}
_tok = None


def song_key(path: Path) -> str:
    parts = path.stem.split("__")
    return f"{parts[0]}__{'_'.join(parts[1:-1])}"


def train_bpe():
    if TOKENIZER_PATH.exists():
        print("tokenizer already trained")
        return
    rnd = random.Random(0)
    files = []
    for g in CLEAN.iterdir():
        fs = sorted(g.glob("*.mid"))
        rnd.shuffle(fs)
        files += fs[: 1500 if g.name.startswith("base") else len(fs)]
    tok = make_tokenizer()
    tok.train(vocab_size=BPE_VOCAB, model="BPE", files_paths=files)
    tok.save(TOKENIZER_PATH)
    print("BPE trained, vocab", len(tok))


def _init():
    global _tok
    _tok = make_tokenizer()


def _work(args):
    path, shifts = args
    out = []
    try:
        score = Score(str(path))
    except Exception:
        return out
    for sh in shifts:
        try:
            s = score.shift_pitch(sh) if sh else score
            seq = _tok(s)
            seq = seq[0] if isinstance(seq, list) else seq
            ids = [_tok["BOS_None"]] + list(seq.ids) + [_tok["EOS_None"]]
        except Exception:
            continue
        stride = SEQ_LEN // 2
        if len(ids) <= SEQ_LEN:
            out.append(ids)
        else:
            out += [ids[i : i + SEQ_LEN] for i in range(0, len(ids) - SEQ_LEN + stride, stride)]
    return [(str(path), w) for w in out]


def tokenize_group(group: str):
    dst = DATA / f"tok_{group}.npz"
    if dst.exists():
        print("exists", dst)
        return
    files = sorted((CLEAN / group).glob("*.mid"))
    with Pool(initializer=_init) as pool:
        res = pool.map(_work, [(f, SHIFTS[group]) for f in files], chunksize=16)
    flat = [x for r in res for x in r]
    pad = make_tokenizer()["PAD_None"]
    keys = sorted({song_key(Path(p)) for p, _ in flat})
    kid = {k: i for i, k in enumerate(keys)}
    arr = np.full((len(flat), SEQ_LEN), pad, dtype=np.int16)
    song = np.zeros(len(flat), dtype=np.int32)
    for i, (p, w) in enumerate(flat):
        arr[i, : len(w)] = w
        song[i] = kid[song_key(Path(p))]
    np.savez_compressed(dst, windows=arr, song=song, keys=np.array(keys))
    print(f"{group}: {len(files)} files -> {len(flat)} windows ({len(flat) * SEQ_LEN / 1e6:.1f}M tokens max)")


if __name__ == "__main__":
    train_bpe()
    for g in sys.argv[1:] or SHIFTS:
        tokenize_group(g)
