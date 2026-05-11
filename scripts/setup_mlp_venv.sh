#!/usr/bin/env bash
# Create/update the MLP project virtualenv and install requirements.txt (Streamlit + Altair versions pinned there).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt

echo ""
echo "MLP venv is ready. Activate and run the dashboard:"
echo "  source .venv/bin/activate"
echo "  streamlit run app.py"
