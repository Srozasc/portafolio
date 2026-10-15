#!/usr/bin/env bash
# t5-finish-ownership.sh
# Final ownership + systemd enable for T5.
# Run on the EC2 instance via SSH:
#   scp -i ~/.ssh/portafolio-api-key.pem scripts/aws/t5-finish-ownership.sh ec2-user@32.189.197.242:/tmp/
#   ssh -i ~/.ssh/portafolio-api-key.pem ec2-user@32.189.197.242 'sudo bash /tmp/t5-finish-ownership.sh'

set -euo pipefail

echo "=== [1/3] Recursive chown on .venv (so portafolio user can run uvicorn) ==="
chown -R portafolio:portafolio /opt/portafolio/apps/api/.venv
echo "  done"

echo ""
echo "=== [2/3] Recursive chown on backend/data/scripts (writable for portafolio) ==="
chown -R portafolio:portafolio /opt/portafolio/apps/api/backend
chown -R portafolio:portafolio /opt/portafolio/apps/api/data
chown -R portafolio:portafolio /opt/portafolio/apps/api/scripts
echo "  done"

echo ""
echo "=== [3/3] Enable systemd unit (will start on boot, not yet started) ==="
systemctl enable portafolio.service
systemctl is-enabled portafolio.service

echo ""
echo "=== Final state ==="
echo "venv owner: $(stat -c '%U:%G' /opt/portafolio/apps/api/.venv)"
echo ".env owner: $(stat -c '%U:%G' /opt/portafolio/apps/api/.env)"
echo "data owner: $(stat -c '%U:%G' /opt/portafolio/apps/api/data)"
echo "scripts:    $(stat -c '%U:%G' /opt/portafolio/apps/api/scripts)"
echo "service:    $(systemctl is-enabled portafolio.service 2>&1)"
