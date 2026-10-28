"""Generate new piano + guitar MIDI from a trained checkpoint and check it for copying.

python generate.py --ckpt ckpt/final --out out --n 12 --tokens 900
Writes out/sample_NN.mid (both instruments) plus sample_NN_piano.mid and sample_NN_guitar.mid,
and prints how much of each sample is copied verbatim from the training songs.
Optionally --prompt some.mid continues from the first --prompt-tokens tokens of that file.
"""
import argparse
from pathlib import Path

import numpy as np
import torch
from symusic import Score
from transformers import GPT2LMHeadModel

from common import ROOT, make_tokenizer

NGRAM = 16


def ngram_hashes(ids, n=NGRAM):
    a = np.asarray(ids, dtype=np.int64)
    if len(a) < n:
        return np.zeros(0, dtype=np.int64)
    h = np.zeros(len(a) - n + 1, dtype=np.int64)
    for k in range(n):
        h = h * 1000003 + a[k : len(a) - n + 1 + k]
    return h


def training_hashes(tok):
    pad = tok["PAD_None"]
    hs = []
    for g in ("mine_core", "mine_style"):
        w = np.load(ROOT / f"data/tok_{g}.npz")["windows"].astype(np.int64)
        for row in w:
            hs.append(ngram_hashes(row[row != pad]))
    return np.unique(np.concatenate(hs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="ckpt/final")
    ap.add_argument("--out", default="out")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--tokens", type=int, default=1000)
    ap.add_argument("--rep-penalty", type=float, default=1.12)
    ap.add_argument("--need-both", action="store_true", help="keep only samples with piano AND guitar")
    ap.add_argument("--max-tries", type=int, default=60)
    ap.add_argument("--temp", type=float, default=0.95)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--prompt-tokens", type=int, default=64)
    ap.add_argument("--device", default="cpu")  # cpu avoids slow per-length graph compiles on MPS
    ap.add_argument("--no-copy-check", action="store_true")
    args = ap.parse_args()

    tok = make_tokenizer()
    model = GPT2LMHeadModel.from_pretrained(ROOT / args.ckpt).to(args.device).eval()

    start = [tok["BOS_None"]]
    if args.prompt:
        seq = tok(Score(args.prompt))
        seq = seq[0] if isinstance(seq, list) else seq
        start += list(seq.ids)[: args.prompt_tokens]

    train_h = None if args.no_copy_check else training_hashes(tok)
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    special = {tok["BOS_None"], tok["EOS_None"], tok["PAD_None"]}
    kept, tries = 0, 0
    while kept < args.n and tries < args.max_tries:
        i, tries = kept, tries + 1
        x = torch.tensor([start], device=args.device)
        with torch.no_grad():
            y = model.generate(
                x, do_sample=True, temperature=args.temp, top_p=args.top_p, repetition_penalty=args.rep_penalty,
                max_new_tokens=args.tokens, pad_token_id=tok["PAD_None"], eos_token_id=tok["EOS_None"],
            )
        ids = [t for t in y[0].tolist() if t not in special]
        try:
            score = tok.decode(ids)
        except Exception as e:
            print(f"sample {i}: decode failed ({e})")
            continue
        progs = sorted({t.program for t in score.tracks})
        n_by = {nm: sum(len(t.notes) for t in score.tracks if t.program in w) for nm, w in (("piano", {0, 4}), ("guitar", {27, 29}))}
        if sum(n_by.values()) < 150 or (args.need_both and min(n_by.values()) < 60):
            continue
        kept += 1
        path = out_dir / f"sample_{i:02d}.mid"
        score.dump_midi(str(path))
        for name, want in (("piano", {0, 4}), ("guitar", {27, 29})):
            keep = [t for t in score.tracks if t.program in want]
            if keep:
                sub = Score(score.ticks_per_quarter)
                sub.tempos, sub.time_signatures = score.tempos, score.time_signatures
                sub.tracks = keep
                sub.dump_midi(str(out_dir / f"sample_{i:02d}_{name}.mid"))
        msg = f"wrote {path.name}: programs {progs}, {sum(len(t.notes) for t in score.tracks)} notes"
        if train_h is not None:
            h = ngram_hashes(ids)
            frac = float(np.isin(h, train_h).mean()) if len(h) else 0.0
            msg += f", {frac:.0%} of {NGRAM}-token spans appear verbatim in training songs"
        print(msg, flush=True)


if __name__ == "__main__":
    main()
