"""Stage 1: pretrain a GPT on general piano + electric guitar MIDI, within a wall-clock budget.

python train.py --minutes 235 --out ckpt/base
Resumable: re-running continues from ckpt/base/state.pt.
"""
import argparse
import math
import time
import zlib
from pathlib import Path

import numpy as np
import torch
from transformers import GPT2Config, GPT2LMHeadModel

from common import ROOT, SEQ_LEN, make_tokenizer

DATA = ROOT / "data"


def load(groups):
    ws, ss = [], []
    for g in groups:
        d = np.load(DATA / f"tok_{g}.npz")
        keys = d["keys"]
        ws.append(d["windows"])
        ss.append(np.array([zlib.crc32(str(keys[i]).encode()) for i in d["song"]], dtype=np.int64))
    return np.concatenate(ws), np.concatenate(ss)


def build_model(tok):
    cfg = GPT2Config(
        vocab_size=len(tok), n_positions=SEQ_LEN, n_embd=512, n_layer=10, n_head=8,
        bos_token_id=tok["BOS_None"], eos_token_id=tok["EOS_None"], pad_token_id=tok["PAD_None"],
    )
    return GPT2LMHeadModel(cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ckpt/base")
    ap.add_argument("--minutes", type=float, default=235)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--groups", nargs="+", default=["base_lakh", "base_maestro"])
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--init", default=None, help="continue from this checkpoint (domain-adaptive training)")
    ap.add_argument("--val-mod", type=int, default=40, help="hold out songs whose hash %% val_mod == 0")
    args = ap.parse_args()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = make_tokenizer()
    pad = tok["PAD_None"]
    windows, songs = load(args.groups)
    is_val = songs % args.val_mod == 0  # whole songs held out, so no leakage
    data = torch.from_numpy(windows.astype(np.int64))
    train, val = data[~torch.from_numpy(is_val)], data[torch.from_numpy(is_val)][:640]
    print(f"device={device} train_windows={len(train)} val_windows={len(val)}", flush=True)

    out = Path(ROOT / args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.pt"
    model = (GPT2LMHeadModel.from_pretrained(ROOT / args.init) if args.init else build_model(tok)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.05, betas=(0.9, 0.95))
    step, elapsed = 0, 0.0
    if state_path.exists():
        st = torch.load(state_path, map_location=device)
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        step, elapsed = st["step"], st["elapsed"]
        print(f"resumed at step {step}, {elapsed / 60:.1f} min", flush=True)
    print(f"params: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M", flush=True)

    budget = args.minutes * 60
    warmup = 300

    def lr_at(step, frac):
        if step < warmup:
            return args.lr * (step + 1) / warmup
        return args.lr * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * min(frac, 1.0))))

    def loss_on(x):
        x = x.to(device)
        return model(input_ids=x, labels=x.masked_fill(x == pad, -100)).loss

    @torch.no_grad()
    def evaluate():
        model.eval()
        ls = [loss_on(val[i : i + args.batch]).item() for i in range(0, len(val) - args.batch + 1, args.batch)]
        model.train()
        return sum(ls) / len(ls)

    def save():
        model.save_pretrained(out)
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "elapsed": elapsed}, state_path)

    g = torch.Generator().manual_seed(step)
    model.train()
    t_last_save = time.time()
    t0 = time.time() - elapsed
    run_start = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed >= budget or (args.max_steps and step >= args.max_steps):
            break
        for gp in opt.param_groups:
            gp["lr"] = lr_at(step, elapsed / budget)
        for _ in range(args.accum):
            idx = torch.randint(0, len(train), (args.batch,), generator=g)
            loss = loss_on(train[idx])
            (loss / args.accum).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        if step % 50 == 0:
            print(f"step {step} loss {loss.item():.3f} lr {opt.param_groups[0]['lr']:.2e} elapsed {elapsed / 60:.1f}m", flush=True)
        if step % 500 == 0:
            print(f"  val loss {evaluate():.3f}", flush=True)
        if time.time() - t_last_save > 600:
            save()
            t_last_save = time.time()
    print(f"final val loss {evaluate():.3f} after {step} steps", flush=True)
    save()
    (out / "DONE").write_text("ok")
    print("base training done", flush=True)


if __name__ == "__main__":
    main()
