#!/bin/bash
# Sets up the extra features: code sandbox + document files (.venv-code), speech to text (.venv-voice, Whisper),
# creating pictures from text (Z-Image-Turbo 4-bit, needs the picture environment .venv-img from setup_image_model.sh).
# Needs the internet once (about 8 GB of downloads); afterwards everything runs offline.
#   ./setup_extras.sh            everything
#   ./setup_extras.sh code       only the code sandbox / documents
#   ./setup_extras.sh voice      only speech to text
#   ./setup_extras.sh image      only picture creation
set -e
cd "$(dirname "$0")"
WHAT="${1:-all}"
command -v uv >/dev/null || { echo "Install uv first:  brew install uv"; exit 1; }

if [ "$WHAT" = all ] || [ "$WHAT" = code ]; then
  echo "== Code sandbox and document tools (.venv-code)"
  [ -x .venv-code/bin/python ] || uv venv --python 3.12 .venv-code
  uv pip install --python .venv-code/bin/python numpy pandas scipy sympy matplotlib openpyxl xlsxwriter python-docx python-pptx fpdf2 pillow
fi

if [ "$WHAT" = all ] || [ "$WHAT" = voice ]; then
  echo "== Speech to text (.venv-voice, Whisper large-v3-turbo, about 1.6 GB)"
  command -v ffmpeg >/dev/null || { echo "ffmpeg is needed for audio. Run:  brew install ffmpeg"; exit 1; }
  [ -x .venv-voice/bin/python ] || uv venv --python 3.12 .venv-voice
  uv pip install --python .venv-voice/bin/python mlx-whisper
  .venv-voice/bin/python -c "from huggingface_hub import snapshot_download; print(snapshot_download('mlx-community/whisper-large-v3-turbo'))"
fi

if [ "$WHAT" = all ] || [ "$WHAT" = image ]; then
  echo "== Creating pictures from text (Z-Image-Turbo 4-bit, about 6 GB)"
  [ -x .venv-img/bin/python ] || { echo "Run ./setup_image_model.sh first (it makes .venv-img)."; exit 1; }
  .venv-img/bin/python -c "from huggingface_hub import snapshot_download; print(snapshot_download('filipstrand/Z-Image-Turbo-mflux-4bit'))"
fi
echo "Done. Restart the server:  launchctl kickstart -k gui/\$(id -u)/ai.unplugged.server   (or ./start.sh)"
