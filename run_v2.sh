#!/bin/bash
# v2: specialize harder on your taste.
#  1. rank the general songs by similarity to your songs, build the domain set
#  2. continue pretraining the base model on that domain set (all parameters)
#  3. LoRA fine-tune on your exact songs
#  4. generate samples with the copy-check
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore PYTORCH_ENABLE_MPS_FALLBACK=1
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a logs/run_v2.log; }

[ -f data/tok_dapt.npz ] || { log "stage 1: ranking songs by similarity to your taste"; python rank_songs.py >> logs/rank.log 2>&1 || { log "RANK FAILED"; exit 1; }; }
[ -f ckpt/dapt/DONE ] || { log "stage 2: domain training (${DAPT_MIN:-120} min)"; python train.py --init ckpt/base --groups dapt --val-mod 8 --lr 1.5e-4 --minutes "${DAPT_MIN:-120}" --out ckpt/dapt >> logs/train_dapt.log 2>&1 || { log "DAPT FAILED"; exit 1; }; }
[ -f ckpt/final_v2/DONE ] || { log "stage 3: LoRA on your songs (${LORA_MIN:-40} min)"; python finetune_lora.py --base ckpt/dapt --out ckpt/final_v2 --adapter-dir ckpt/lora_v2 --minutes "${LORA_MIN:-40}" --lr 1e-3 --rank 64 --core-weight 8 --eval-every 75 >> logs/finetune_v2.log 2>&1 || { log "LORA FAILED"; exit 1; }; }
log "stage 4: generating samples"
python generate.py --ckpt ckpt/final_v2 --out out_v2 --n 10 --need-both --max-tries 80 > out_v2_report.txt 2>&1
touch V2_DONE
log "V2 DONE"
