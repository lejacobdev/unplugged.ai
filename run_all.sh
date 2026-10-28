#!/bin/bash
# Unattended end-to-end run: pretrain -> LoRA fine-tune on your songs -> generate samples.
# Safe to re-run: finished stages are skipped, base training resumes from its last checkpoint.
cd "$(dirname "$0")"
source .venv/bin/activate
mkdir -p logs ckpt out
export PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore PYTORCH_ENABLE_MPS_FALLBACK=1

BASE_MIN=${BASE_MIN:-230}
LORA_MIN=${LORA_MIN:-45}
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a logs/run_all.log; }

[ -d data/clean/mine_core ] || { log "cleaning MIDI"; python clean_midi.py >> logs/clean.log 2>&1; }
log "tokenizing (skips finished groups)"
python prep_tokens.py >> logs/prep.log 2>&1 || { log "TOKENIZE FAILED"; exit 1; }

if [ ! -f ckpt/base/DONE ]; then
  log "stage 1: base pretraining ($BASE_MIN min)"
  python train.py --out ckpt/base --minutes "$BASE_MIN" >> logs/train_base.log 2>&1 || { log "BASE TRAINING FAILED"; exit 1; }
fi

if [ ! -f ckpt/final/DONE ]; then
  log "stage 2: LoRA fine-tune on your songs ($LORA_MIN min)"
  python finetune_lora.py --base ckpt/base --out ckpt/final --minutes "$LORA_MIN" >> logs/finetune.log 2>&1 \
    || { log "LORA FAILED, falling back to base model as final"; cp -r ckpt/base ckpt/final; echo fallback > ckpt/final/DONE; }
fi

log "stage 3: generating samples"
python generate.py --ckpt ckpt/final --out out --n 12 --tokens 900 > out/generation_report.txt 2>&1
log "ALL DONE"
touch ALL_DONE
