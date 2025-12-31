#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Worker runner
# - Activates venv
# - Installs deps only if requirements.txt changed
# - Loads .env and EXPORTS all vars (important for MCP stdio)
# - Starts Redis Stream worker (long-running)
# ------------------------------------------------------------

log() {
  echo "[run_worker.sh] $*"
}

# ------------------------------------------------------------
# Guard: Prevent multiple Redis Stream workers
# ------------------------------------------------------------
if pgrep -f "src.app.infra.redis.worker" > /dev/null; then
  echo "[run_worker.sh] ERROR: redis worker already running."
  echo "[run_worker.sh] Use: pkill -f src.app.infra.redis.worker"
  exit 1
fi

# 1) Resolve repo root (directory of this script)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"
log "Repo root: $REPO_ROOT"

# 2) Ensure venv exists
if [[ ! -d ".venv" ]]; then
  log "Creating virtualenv: .venv"
  if command -v python3.13 >/dev/null 2>&1; then
    python3.13 -m venv .venv
  else
    python3 -m venv .venv
  fi
else
  log "Virtualenv exists: .venv"
fi

# 3) Activate venv
# shellcheck disable=SC1091
source ".venv/bin/activate"
log "Activated venv: $(python --version)"

# IMPORTANT: Always use `python -m pip` (not `pip`) to avoid mismatched pip shebangs
# that can point at a different Python (e.g., 3.14) even when `python` is 3.13.
PIP_INFO="$(python -m pip --version || true)"
log "pip module: $PIP_INFO"

if ! echo "$PIP_INFO" | grep -q "python 3\\.13"; then
  log "Detected non-3.13 pip/python mismatch; recreating .venv with python3.13"
  deactivate || true
  rm -rf ".venv"
  if command -v python3.13 >/dev/null 2>&1; then
    python3.13 -m venv .venv
  else
    log "ERROR: python3.13 not found; please install Python 3.13 and rerun."
    exit 1
  fi
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  log "Recreated venv: $(python --version)"
  log "pip module: $(python -m pip --version)"
fi

# 4) Install dependencies only when requirements.txt changes
REQ_FILE="requirements.txt"
REQ_HASH_FILE=".requirements.sha256"

if [[ ! -f "$REQ_FILE" ]]; then
  log "ERROR: requirements.txt not found at repo root"
  exit 1
fi

CURRENT_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
PREV_HASH=""

if [[ -f "$REQ_HASH_FILE" ]]; then
  PREV_HASH="$(cat "$REQ_HASH_FILE" || true)"
fi

if [[ "$CURRENT_HASH" != "$PREV_HASH" ]]; then
  log "requirements.txt changed or first install detected"
  log "Installing dependencies..."
  python -m pip install -r "$REQ_FILE"
  echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
  log "Dependencies installed and hash updated"
else
  log "requirements.txt unchanged. Skipping dependency install."
fi

# 5) Load .env and export variables (CRITICAL for MCP stdio child processes)
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

# 6) Validate required env vars for MCP
if [[ -z "${NOTION_MCP_ACCESS_TOKEN:-}" ]]; then
  log "ERROR: NOTION_MCP_ACCESS_TOKEN is not set (needed for Notion MCP stdio server)."
  log "Fix: add it to .env and rerun."
  exit 1
fi

# 7) Optional: quick Redis check (non-fatal)
if command -v redis-cli >/dev/null 2>&1; then
  if redis-cli ping >/dev/null 2>&1; then
    log "Redis ping OK"
  else
    log "WARNING: Redis ping failed. Make sure Redis is running on localhost:6379"
  fi
else
  log "WARNING: redis-cli not found. Skipping Redis health check."
fi

# 8) Start Redis worker (long-running)
log "Starting Redis Stream worker"
python -m src.app.infra.redis.worker
