#!/usr/bin/env bash
set -euo pipefail

# Directory discovery
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_DIR="${REPO_ROOT}/apps/api"

echo "=== [1/5] Pulling latest code ==="
cd "${REPO_ROOT}"
git pull --ff-only

echo "=== [2/5] Preparing Python virtual environment ==="
cd "${API_DIR}"
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment at ${API_DIR}/.venv..."
    python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

echo "=== [3/5] Installing/updating dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [4/5] Re-indexing vector store ==="
python scripts/reindex.py --force

echo "=== [5/5] Restarting systemd service ==="
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet portafolio.service 2>/dev/null; then
    sudo systemctl restart portafolio.service
    echo "portafolio.service restarted successfully."
else
    echo "Notice: portafolio.service is not active or systemctl not available. Skipping service restart."
    echo "To start manually: uvicorn backend.main:app --host 0.0.0.0 --port 8000"
fi

echo "=== Deployment completed successfully ==="
