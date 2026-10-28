"""Shared config: tokenizer and model settings for the piano + electric guitar model."""
from pathlib import Path

from miditok import REMI, TokenizerConfig

ROOT = Path(__file__).parent
TOKENIZER_PATH = ROOT / "tokenizer.json"

PIANO = [0, 4]      # acoustic piano, electric piano
GUITAR = [27, 29]   # electric guitar clean, electric guitar driven
SEQ_LEN = 1024
BPE_VOCAB = 6000


def base_config() -> TokenizerConfig:
    return TokenizerConfig(
        pitch_range=(21, 109),
        beat_res={(0, 4): 8, (4, 12): 4},
        num_velocities=16,
        special_tokens=["PAD", "BOS", "EOS"],
        use_programs=True,
        one_token_stream_for_programs=True,
        use_tempos=True,
        use_time_signatures=True,
        programs=PIANO + GUITAR,
    )


def make_tokenizer() -> REMI:
    """Load the saved tokenizer (with learned BPE) if present, else a fresh untrained one."""
    if TOKENIZER_PATH.exists():
        return REMI(params=TOKENIZER_PATH)
    return REMI(base_config())
