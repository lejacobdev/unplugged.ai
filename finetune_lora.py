"""Stage 2: LoRA fine-tune the base model on YOUR songs (mine_core upweighted) + similar artists.

python finetune_lora.py --base ckpt/base --out ckpt/final --minutes 40
Keeps the adapter with the best held-out loss, merges it into the base weights, saves ckpt/final.
"""
import argparse
import math
import time
import zlib
from pathlib import Path

import numpy as np
import torch
from peft import LoraConfig, get_peft_model
from transformers import GPT2LMHeadModel

from common import ROOT, make_tokenizer
from train import load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="ckpt/base")
    ap.add_argument("--out", default="ckpt/final")
    ap.add_argument("--minutes", type=float, default=40)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--core-weight", type=float, default=4.0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--eval-every", type=int, default=100)
    ap.add_argument("--adapter-dir", default="ckpt/lora_best")
    args = ap.parse_args()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = make_tokenizer()
    pad = tok["PAD_None"]

    cw, cs = load(["mine_core"])
    sw, ss = load(["mine_style"])
    windows = np.concatenate([cw, sw])
    songs = np.concatenate([cs, ss])
    weight = np.concatenate([np.full(len(cw), args.core_weight), np.ones(len(sw))])
    # hold out whole songs for validation: ~12% of songs, core and style alike
    is_val = (songs % 8) == 0
    data = torch.from_numpy(windows.astype(np.int64))
    tr_idx = np.where(~is_val)[0]
    va_idx = np.where(is_val)[0]
    val = data[va_idx][:320]
    train, p = data[tr_idx], torch.from_numpy(weight[tr_idx]).float()
    print(f"train windows {len(train)} (core share ~{p[: (~is_val[: len(cw)]).sum()].sum() / p.sum():.0%}), val windows {len(val)}", flush=True)

    model = GPT2LMHeadModel.from_pretrained(ROOT / args.base)
    base_val = None
    cfg = LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.1,
        target_modules=["c_attn", "c_proj", "c_fc"], fan_in_fan_out=True, task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, cfg).to(device)
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([q for q in model.parameters() if q.requires_grad], lr=args.lr, weight_decay=0.01)

    def loss_on(x):
        x = x.to(device)
        return model(input_ids=x, labels=x.masked_fill(x == pad, -100)).loss

    @torch.no_grad()
    def evaluate():
        model.eval()
        ls = [loss_on(val[i : i + args.batch]).item() for i in range(0, len(val) - args.batch + 1, args.batch)]
        model.train()
        return sum(ls) / len(ls)

    budget = args.minutes * 60
    out = ROOT / args.out
    adapter_dir = ROOT / args.adapter_dir
    base_val = evaluate()
    print(f"base-model val loss on held-out songs: {base_val:.3f}", flush=True)
    best, best_step = base_val, 0
    g = torch.Generator().manual_seed(0)
    t0, step = time.time(), 0
    model.train()
    while time.time() - t0 < budget and not (args.max_steps and step >= args.max_steps):
        frac = (time.time() - t0) / budget
        lr = args.lr * min(1.0, (step + 1) / 30) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(frac, 1))))
        for gp in opt.param_groups:
            gp["lr"] = lr
        for _ in range(args.accum):
            idx = torch.multinomial(p, args.batch, replacement=True, generator=g)
            loss = loss_on(train[idx])
            (loss / args.accum).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        if step % 25 == 0:
            print(f"step {step} loss {loss.item():.3f} lr {lr:.2e} {(time.time() - t0) / 60:.1f}m", flush=True)
        if step % args.eval_every == 0:
            v = evaluate()
            tag = ""
            if v < best:
                best, best_step = v, step
                model.save_pretrained(adapter_dir)
                tag = "  <- best"
            print(f"  val loss {v:.3f}{tag}", flush=True)
    v = evaluate()
    if v < best:
        best, best_step = v, step
        model.save_pretrained(adapter_dir)
    print(f"best val {best:.3f} at step {best_step} (base was {base_val:.3f})", flush=True)

    if best_step == 0:
        print("LoRA did not beat the base model on held-out songs; saving base as final", flush=True)
        GPT2LMHeadModel.from_pretrained(ROOT / args.base).save_pretrained(out)
    else:
        from peft import PeftModel

        merged = PeftModel.from_pretrained(GPT2LMHeadModel.from_pretrained(ROOT / args.base), adapter_dir).merge_and_unload()
        merged.save_pretrained(out)
    (out / "DONE").write_text(f"base_val={base_val:.4f} best_val={best:.4f} step={best_step}")
    print("finetune done", flush=True)


if __name__ == "__main__":
    main()
