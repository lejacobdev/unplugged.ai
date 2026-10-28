# Piano + electric guitar MIDI model

A 35M-parameter GPT trained on MIDI (REMI tokens + 6000-token BPE vocabulary) that writes
piano and electric-guitar parts. Unattended pipeline (`run_all.sh`):

1. **Clean** (`clean_midi.py`): Lakh MIDI "clean" set + MAESTRO, keeping only piano and electric guitar tracks.
2. **Tokenize** (`prep_tokens.py`): BPE tokenizer, 1024-token windows (about 80-90 s of music each).
3. **Pretrain** (`train.py`): about 4 hours on general piano + guitar MIDI (about 95k windows).
4. **LoRA fine-tune** (`finetune_lora.py`): your songs from `songs.md` found in Lakh (`mine_core`, upweighted 4x,
   transposed into 9 keys) plus other songs by your artists (`mine_style`). The best adapter by held-out-song
   loss is merged into the model: `ckpt/final_strong` (lr 1e-3, rank 64, your songs weighted 8x; held-out loss 3.094 vs 3.134 for the base model).
5. **Generate** (`generate.py`): 12 samples in `out/`, with a copy-check against the training songs.

## Results
- `out/sample_NN.mid`: piano + guitar together; `_piano.mid` / `_guitar.mid`: each instrument on its own.
- `out/generation_report.txt`: note counts and the share of 16-token spans copied verbatim from training songs.
- `logs/finetune.log`: base vs fine-tuned loss on songs held out entirely from training.

## Make more
```
source .venv/bin/activate
python generate.py --ckpt ckpt/final_strong --out out2 --n 8 --tokens 900 --temp 0.9
python generate.py --ckpt ckpt/final_strong --prompt some_song.mid --prompt-tokens 64   # continue a MIDI file
```
Lower `--temp` (0.8) = safer/more repetitive; higher (1.1) = wilder.

## Train on more of your songs
Put extra `.mid` files in `data/clean/mine_core/` named `Artist__Title__0.mid` (piano/guitar tracks only,
e.g. from Guitar Pro tabs converted to MIDI), then:
```
rm data/tok_mine_core.npz && python prep_tokens.py mine_core
python finetune_lora.py --base ckpt/base --out ckpt/final_strong2 --minutes 40
```
