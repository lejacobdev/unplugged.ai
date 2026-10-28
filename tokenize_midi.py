"""Tokenize a folder of MIDI files into training windows (.npz).

Piano and guitar tracks are kept; drums and other instruments are dropped.
--augment N adds pitch-transposed copies (-N..+N semitones) to stretch a small dataset.
"""
import argparse
import random
from pathlib import Path

import numpy as np
from symusic import Score
from tqdm import tqdm

from common import SEQ_LEN, make_tokenizer


def windows(ids, seq_len, stride):
    if len(ids) <= seq_len:
        return [ids]
    return [ids[i : i + seq_len] for i in range(0, len(ids) - seq_len + stride, stride)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--augment", type=int, default=0)
    ap.add_argument("--stride", type=int, default=SEQ_LEN // 2)
    args = ap.parse_args()

    tok = make_tokenizer()
    files = sorted(p for p in Path(args.src).rglob("*") if p.suffix.lower() in (".mid", ".midi"))
    random.Random(0).shuffle(files)
    if args.max_files:
        files = files[: args.max_files]

    shifts = [0] + [s for k in range(1, args.augment + 1) for s in (k, -k)]
    out, bad = [], 0
    for f in tqdm(files, desc="tokenizing"):
        try:
            score = Score(str(f))
        except Exception:
            bad += 1
            continue
        for shift in shifts:
            try:
                s = score.shift_pitch(shift) if shift else score
                seq = tok(s)
                seq = seq[0] if isinstance(seq, list) else seq
                ids = [tok["BOS_None"]] + list(seq.ids) + [tok["EOS_None"]]
            except Exception:
                bad += 1
                continue
            out.extend(windows(ids, SEQ_LEN, args.stride))

    lens = np.array([len(w) for w in out])
    arr = np.full((len(out), SEQ_LEN), tok["PAD_None"], dtype=np.int16)
    for i, w in enumerate(out):
        arr[i, : len(w)] = w
    np.savez_compressed(args.out, windows=arr, lens=lens)
    print(f"{len(files)} files ({bad} skipped) -> {len(out)} windows, vocab {len(tok)}")


if __name__ == "__main__":
    main()
