#!/usr/bin/env bash
# Run the Streamlit app using the MLP project .venv (create it with setup_mlp_venv.sh first).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "No .venv found. Run:  bash scripts/setup_mlp_venv.sh" >&2
  exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate
exec streamlit run app.py "$@"
