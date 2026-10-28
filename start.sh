#!/bin/bash
# Starts unplugged.ai. Open http://127.0.0.1:8000 (or the addresses it prints for your phone).
cd "$(dirname "$0")"
export PYTORCH_ENABLE_MPS_FALLBACK=1
exec caffeinate -is .venv/bin/python server.py
