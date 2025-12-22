#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[run_dispatcher.sh] $*"
}

# ------------------------------------------------------------
# Guard: Prevent multiple outbound dispatchers
# ------------------------------------------------------------
if pgrep -f "src.app.dispatchers.outbound_dispatcher" > /dev/null; then
  echo "[run_dispatcher.sh] ERROR: outbound_dispatcher already running."
  echo "[run_dispatcher.sh] Use: pkill -f src.app.dispatchers.outbound_dispatcher"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"
log "Repo root: $REPO_ROOT"

if [[ ! -d ".venv" ]]; then
  log "Creating virtualenv: .venv"
  python3 -m venv .venv
else
  log "Virtualenv exists: .venv"
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"
log "Activated venv: $(python --version)"

REQ_FILE="requirements.txt"
REQ_HASH_FILE=".requirements.sha256"

CURRENT_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
PREV_HASH=""
if [[ -f "$REQ_HASH_FILE" ]]; then
  PREV_HASH="$(cat "$REQ_HASH_FILE" || true)"
fi

if [[ "$CURRENT_HASH" != "$PREV_HASH" ]]; then
  log "requirements.txt changed or first install detected"
  log "Installing dependencies..."
  pip install -r "$REQ_FILE"
  echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
  log "Dependencies installed and hash updated"
else
  log "requirements.txt unchanged. Skipping dependency install."
fi

ENV_FILE=".env"
if [[ -f "$ENV_FILE" ]]; then
  log "Found env file: $ENV_FILE"
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
  log "Loaded and exported environment variables from $ENV_FILE"
else
  log "WARNING: .env not found. Continuing without it."
fi

# Validate Twilio creds for outbound sending
if [[ -z "${TWILIO_ACCOUNT_SID:-}" ]]; then
  log "ERROR: TWILIO_ACCOUNT_SID is not set."
  exit 1
fi
if [[ -z "${TWILIO_AUTH_TOKEN:-}" ]]; then
  log "ERROR: TWILIO_AUTH_TOKEN is not set."
  exit 1
fi
if [[ -z "${TWILIO_WHATSAPP_FROM:-}" ]]; then
  log "ERROR: TWILIO_WHATSAPP_FROM is not set. Example: whatsapp:+14155238886"
  exit 1
fi

if command -v redis-cli >/dev/null 2>&1; then
  if redis-cli ping >/dev/null 2>&1; then
    log "Redis ping OK"
  else
    log "WARNING: Redis ping failed. Make sure Redis is running on localhost:6379"
  fi
else
  log "WARNING: redis-cli not found. Skipping Redis health check."
fi

log "Starting Outbound Dispatcher"
python -m src.app.dispatchers.outbound_dispatcher
