#!/bin/bash
# One-time setup for offline picture editing with FLUX.1 Kontext [dev] by Black Forest Labs.
# Downloads the model once (~34 GB), converts it to an 8-bit copy (~12 GB) in models/kontext-q8,
# and from then on the dashboard edits pictures with no internet connection.
cd "$(dirname "$0")"
HF=.venv-img/bin/hf

echo
echo "== FLUX.1 Kontext [dev] setup =="
echo
echo "Step 1. While signed in at huggingface.co, open"
echo "        https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev"
echo "        and click the button to accept the license."
echo "        (It is a non-commercial license. Read it to be sure it covers how you plan to use the results.)"
echo
read -r -p "Press Enter once you have accepted it... "

if ! $HF auth whoami > /dev/null 2>&1; then
  echo
  echo "Step 2. Log in. Create a *read* token at https://huggingface.co/settings/tokens"
  echo "        and paste it when asked (it is stored by Hugging Face's own tool, not by this project)."
  $HF auth login || exit 1
fi

echo
echo "Step 3. Downloading the model and saving an 8-bit copy. This takes a while and needs ~50 GB free."
echo "        It is safe to stop with Ctrl+C and re-run; downloads resume."
.venv-img/bin/mflux-save --model dev-kontext --quantize 8 --path models/kontext-q8 || { echo "Conversion failed."; exit 1; }

echo
echo "Done. The offline model is in models/kontext-q8."
echo "Open the 'Pictures' tab in the dashboard (http://127.0.0.1:8000). No restart needed."
echo "To free ~34 GB you may delete the original download afterwards:  $HF cache ls"
