#!/usr/bin/env bash
# Installs surround, the music model of unplugged.ai: ACE-Step 1.5 (MIT licence) in vendor/ACE-Step-1.5.
# Needs uv (https://docs.astral.sh/uv/) and about 11 GB of disk; the weights download on first use of the model below.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "Install uv first: brew install uv"; exit 1; }
[ -d vendor/ACE-Step-1.5 ] || git clone --depth 1 https://github.com/ACE-Step/ACE-Step-1.5.git vendor/ACE-Step-1.5
(cd vendor/ACE-Step-1.5 && uv sync)
echo "Downloading the model weights (about 10 GB)..."
(cd vendor/ACE-Step-1.5 && uv run python - <<'PY'
from pathlib import Path
from acestep.model_downloader import ensure_main_model
import os
print(ensure_main_model(Path("checkpoints").resolve()))
PY
) || echo "If the download step failed, the first song will download the weights automatically."
echo "Done. Start the app with ./start.sh"
