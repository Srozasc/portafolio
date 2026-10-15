#!/usr/bin/env bash
# amazon-linux-bootstrap.sh
# Idempotent bootstrap for portafolio-api on Amazon Linux 2023.
# Run as root: `sudo bash scripts/aws/amazon-linux-bootstrap.sh`
#
# Environment overrides (optional):
#   REPO_URL     - Git URL (default: https://github.com/Srozasc/portafolio.git)
#   REPO_BRANCH  - Git branch to track (default: dev)
#   APP_USER     - System user for the service (default: portafolio)
#   APP_DIR      - Install path (default: /opt/portafolio)

set -euo pipefail

# ---------- Config ----------
REPO_URL="${REPO_URL:-https://github.com/Srozasc/portafolio.git}"
REPO_BRANCH="${REPO_BRANCH:-dev}"
APP_USER="${APP_USER:-portafolio}"
APP_DIR="${APP_DIR:-/opt/portafolio}"
API_DIR="${APP_DIR}/apps/api"
VENV_DIR="${API_DIR}/.venv"

# ---------- Helpers ----------
log()  { echo "[bootstrap $(date +%H:%M:%S)] $*"; }
fail() { log "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------- Preconditions ----------
[ "$(id -u)" -eq 0 ] || fail "Must run as root. Re-run with: sudo bash $0"

# ---------- 1. System packages ----------
log "Updating system packages..."
dnf update -y >/dev/null
log "Installing runtime dependencies (git, python3, pip, gcc, python3-devel)..."
dnf install -y git python3 python3-pip python3-devel gcc >/dev/null
log "  git:        $(git --version)"
log "  python3:    $(python3 --version)"
log "  pip:        $(python3 -m pip --version)"

# ---------- 2. Dedicated app user ----------
if id "$APP_USER" &>/dev/null; then
    log "User $APP_USER already exists, skipping creation."
else
    log "Creating system user $APP_USER..."
    useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

# ---------- 3. Clone or update repo ----------
if [ -d "$APP_DIR/.git" ]; then
    log "Repo already cloned at $APP_DIR. Skipping clone."
else
    log "Cloning $REPO_URL (branch $REPO_BRANCH) to $APP_DIR..."
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
    log "  clone OK"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---------- 4. Python venv ----------
if [ -d "$VENV_DIR" ]; then
    log "Venv already exists at $VENV_DIR, skipping creation."
else
    log "Creating Python venv at $VENV_DIR..."
    sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
fi

# ---------- 5. Python dependencies ----------
log "Installing Python dependencies from requirements.txt..."
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --upgrade pip --quiet
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -r "$API_DIR/requirements.txt" --quiet
log "  pip install OK"

# ---------- 6. Install systemd unit ----------
UNIT_SRC="$API_DIR/systemd/portafolio.service"
UNIT_DST="/etc/systemd/system/portafolio.service"
[ -f "$UNIT_SRC" ] || fail "Unit file not found at $UNIT_SRC"
cp "$UNIT_SRC" "$UNIT_DST"
log "Installed systemd unit -> $UNIT_DST"

# ---------- 7. .env file ----------
ENV_FILE="$API_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    log ".env already exists at $ENV_FILE. Leaving untouched (preserves production values)."
else
    if [ ! -f "$API_DIR/.env.example" ]; then
        fail ".env.example not found at $API_DIR/.env.example"
    fi
    cp "$API_DIR/.env.example" "$ENV_FILE"
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    log "Created $ENV_FILE from .env.example (mode 0600, owner $APP_USER)."
    log "  >>> WARNING: Fill in production values (LLM keys, ChromaDB path) before starting the service."
fi

# ---------- 8. Reload systemd ----------
systemctl daemon-reload
log "systemd daemon reloaded."

# ---------- 9. Done ----------
log ""
log "============================================================"
log "  Bootstrap complete."
log "============================================================"
log ""
log "Next steps (manual, on the EC2 instance):"
log "  1. Edit $ENV_FILE with production values"
log "  2. Regenerate ChromaDB:"
log "       sudo -u $APP_USER bash -c 'cd $API_DIR && .venv/bin/python scripts/ingest_repo.py --all'"
log "  3. Enable and start the service:"
log "       sudo systemctl enable --now portafolio.service"
log "  4. Verify local health:"
log "       curl -sS http://127.0.0.1:8000/api/health"
log ""
log "Service hardening reminders (T6 in odd/tasks/aws-deploy.md):"
log "  - This bootstrap does NOT install cloudflared. T6 wires the tunnel."
log "  - Inbound ports on the EC2 SG stay closed. External traffic reaches"
log "    the backend only through the Cloudflare Tunnel."
