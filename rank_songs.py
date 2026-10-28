"""Rank the general Lakh songs by how close they are to YOUR taste, then build the domain training set.

Method (cross-entropy difference selection): a song is "like yours" if the fine-tuned model predicts it
much better than the general base model does. Keeps the top fraction plus all of your artists' songs.
Output: data/tok_dapt.npz
"""
import argparse
import json
import time

import numpy as np
import torch
import torch.nn.functional as F
from transformers import GPT2LMHeadModel

from common import ROOT, make_tokenizer


def window_losses(model, windows, pad, device, bs=8):
    out = []
    for i in range(0, len(windows), bs):
        chunk = windows[i : i + bs]
        n = len(chunk)
        if n < bs:  # keep tensor shapes fixed (MPS recompiles on new shapes)
            chunk = np.concatenate([chunk, np.repeat(chunk[:1], bs - n, axis=0)])
        x = torch.from_numpy(chunk.astype(np.int64)).to(device)
        with torch.no_grad():
            logits = model(input_ids=x).logits[:, :-1]
        tgt = x[:, 1:]
        ce = F.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt.reshape(-1), reduction="none").view(bs, -1)
        mask = (tgt != pad).float()
        out += ((ce * mask).sum(1) / mask.sum(1).clamp(min=1)).cpu().tolist()[:n]
        if (i // bs) % 200 == 0:
            print(f"  {i}/{len(windows)}", flush=True)
    return np.array(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=float, default=0.4)
    ap.add_argument("--base", default="ckpt/base")
    ap.add_argument("--tuned", default="ckpt/final_strong")
    args = ap.parse_args()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = make_tokenizer()
    pad = tok["PAD_None"]
    d = np.load(ROOT / "data/tok_base_lakh.npz")
    W, S, keys = d["windows"], d["song"], d["keys"]

    by = {}
    for i, s in enumerate(S):
        by.setdefault(int(s), []).append(i)
    pick = []
    for s, idx in by.items():
        mid = idx[len(idx) // 2]
        if (W[mid] != pad).sum() >= 600:
            pick.append((s, mid))
    sample = W[[m for _, m in pick]]
    print(f"scoring {len(pick)} songs", flush=True)

    t0 = time.time()
    losses = {}
    for name in (args.base, args.tuned):
        model = GPT2LMHeadModel.from_pretrained(ROOT / name).to(device).eval()
        losses[name] = window_losses(model, sample, pad, device)
        print(f"{name}: mean loss {losses[name].mean():.3f} ({(time.time() - t0) / 60:.1f} min)", flush=True)
        del model
    score = losses[args.base] - losses[args.tuned]  # bigger = fine-tuning helped more = more like your taste
    order = np.argsort(-score)
    n_keep = int(len(order) * args.keep)
    keep_songs = {pick[i][0] for i in order[:n_keep]}
    json.dump({str(keys[pick[i][0]]): float(score[i]) for i in order[:40]}, open(ROOT / "data/top_similar.json", "w"), indent=1)
    print("most similar to your taste:", [str(keys[pick[i][0]]) for i in order[:12]], flush=True)

    sel = np.array([i for i, s in enumerate(S) if int(s) in keep_songs])
    ws, ss, ks = [W[sel]], [S[sel]], [list(keys)]
    offset = len(keys)
    all_keys = list(keys)
    for g in ("mine_style", "mine_core"):
        e = np.load(ROOT / f"data/tok_{g}.npz")
        ws.append(e["windows"])
        ss.append(e["song"] + len(all_keys))
        all_keys += list(e["keys"])
    np.savez_compressed(
        ROOT / "data/tok_dapt.npz",
        windows=np.concatenate(ws), song=np.concatenate(ss), keys=np.array(all_keys),
    )
    print(f"dapt set: {sum(len(w) for w in ws)} windows ({len(sel)} from {n_keep} general songs)", flush=True)


if __name__ == "__main__":
    main()
