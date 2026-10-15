#!/usr/bin/env bash
# t5-bootstrap-runner.sh — runs on EC2 via SSM send-command
# Does the initial bootstrap that bootstrap.sh itself can't do (it expects the repo already cloned).

set -euo pipefail

echo "=== [1/6] Install git (not in minimal AMI) ==="
if command -v git >/dev/null 2>&1; then
    echo "git already installed: $(git --version)"
else
    dnf install -y git >/dev/null
    echo "git installed: $(git --version)"
fi

echo ""
echo "=== [2/6] Clone repo to /opt/portafolio (branch dev) ==="
if [ -d /opt/portafolio/.git ]; then
    echo "Repo already cloned at /opt/portafolio"
else
    git clone https://github.com/Srozasc/portafolio.git /opt/portafolio
    echo "clone OK"
fi
cd /opt/portafolio
git checkout dev
git log --oneline -3

echo ""
echo "=== [3/6] Run amazon-linux-bootstrap.sh (idempotent) ==="
chmod +x scripts/aws/amazon-linux-bootstrap.sh
bash scripts/aws/amazon-linux-bootstrap.sh

echo ""
echo "=== [4/6] Verify environment ==="
echo "User portafolio exists: $(id portafolio 2>/dev/null && echo YES || echo NO)"
echo "Repo at /opt/portafolio: $([ -d /opt/portafolio/.git ] && echo YES || echo NO)"
echo "Venv at /opt/portafolio/apps/api/.venv: $([ -d /opt/portafolio/apps/api/.venv ] && echo YES || echo NO)"
echo "Systemd unit installed: $([ -f /etc/systemd/system/portafolio.service ] && echo YES || echo NO)"
echo ".env exists: $([ -f /opt/portafolio/apps/api/.env ] && echo YES || echo NO)"

echo ""
echo "=== [5/6] Enable systemd unit (NOT start yet — needs .env with real keys) ==="
systemctl daemon-reload
systemctl enable portafolio.service
echo "portafolio.service enabled (will start on next manual command or reboot)"

echo ""
echo "=== [6/6] Done. Bootstrap ready. Next: user must populate /opt/portafolio/apps/api/.env ==="
echo "After .env is populated:"
echo "  sudo -u portafolio bash -c 'cd /opt/portafolio/apps/api && .venv/bin/python scripts/ingest_repo.py --all'"
echo "  sudo systemctl start portafolio.service"
echo "  curl -sS http://127.0.0.1:8000/api/health"
