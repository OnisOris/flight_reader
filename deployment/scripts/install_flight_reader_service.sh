#!/usr/bin/env bash
set -euo pipefail

# Installer for a systemd service that ensures Docker DB is up
# and runs the Flight Reader API (frun) on Ubuntu 22.04+

REPO_DIR=${1:-$(pwd)}
SERVICE_NAME=flight-reader.service
COMPOSE_FILE="$REPO_DIR/deployment/docker-compose.yaml"

# Resolve target user (original user if executed via sudo)
RUN_USER=${SUDO_USER:-$(id -un)}
RUN_HOME=$(eval echo ~"$RUN_USER")

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

# Ensure systemd directory exists
UNIT_PATH=/etc/systemd/system/$SERVICE_NAME

echo "Installing $SERVICE_NAME for user=$RUN_USER repo=$REPO_DIR"

sudo tee "$UNIT_PATH" >/dev/null <<UNIT
[Unit]
Description=Flight Reader API (FastAPI) + Docker PostGIS
After=network-online.target docker.service
Wants=network-online.target docker.service
Requires=docker.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/usr/bin/docker compose -f $COMPOSE_FILE up -d
ExecStart=/bin/bash -lc \
  'cd "$REPO_DIR" && . .venv/bin/activate && uv run frun'

Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT

echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo "Service status (tail):"
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

echo "Done. Logs: journalctl -u $SERVICE_NAME -f"
