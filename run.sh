#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# run.sh
# Purpose:
# - Create/activate venv (if missing)
# - Install dependencies ONLY when requirements.txt changes (hash-based)
# - Ensure .env exists (create from .env.example if present)
# - Source .env and EXPORT vars so os.getenv() works (MCP header expansion)
# - Resolve MCP config path from env or default
# - Start FastAPI app (uvicorn)
#
# Usage:
#   ./run.sh
# Optional:
#   PORT=8001 ./run.sh
#   VENV_DIR=.venv ./run.sh
# -----------------------------------------------------------------------------

log() {
  echo "[run.sh] $1"
}

# ------------------------------------------------------------
# Guard: Prevent multiple API servers (uvicorn)
# ------------------------------------------------------------
if pgrep -f "uvicorn.*src.app.main" > /dev/null; then
  echo "[run.sh] ERROR: API server already running."
  echo "[run.sh] Use: pkill -f uvicorn"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PORT="${PORT:-8000}"

ENV_FILE="${ENV_FILE:-.env}"
ENV_EXAMPLE="${ENV_EXAMPLE:-.env.example}"

REQ_FILE="requirements.txt"
REQ_HASH_FILE="$VENV_DIR/.requirements.hash"

DEFAULT_MCP_CONFIG="./mcp_configs/mcp_servers.json"

log "Repo root: $ROOT_DIR"

# 1) Ensure virtualenv exists
if [ ! -d "$VENV_DIR" ]; then
  log "Virtualenv not found. Creating at: $VENV_DIR"
  if command -v python3.13 >/dev/null 2>&1; then
    python3.13 -m venv "$VENV_DIR"
  else
    python3 -m venv "$VENV_DIR"
  fi
else
  log "Virtualenv exists: $VENV_DIR"
fi

# 2) Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
log "Activated venv: $(python -V)"

# IMPORTANT: Always use `python -m pip` (not `pip`) to avoid mismatched pip shebangs.
PIP_INFO="$(python -m pip --version || true)"
log "pip module: $PIP_INFO"

if ! echo "$PIP_INFO" | grep -q "python 3\\.13"; then
  log "Detected non-3.13 pip/python mismatch; recreating $VENV_DIR with python3.13"
  deactivate || true
  rm -rf "$VENV_DIR"
  if command -v python3.13 >/dev/null 2>&1; then
    python3.13 -m venv "$VENV_DIR"
  else
    log "ERROR: python3.13 not found; please install Python 3.13 and rerun."
    exit 1
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  log "Recreated venv: $(python -V)"
  log "pip module: $(python -m pip --version)"
fi

# 3) Install dependencies ONLY if requirements.txt changed (or first install)
if [ ! -f "$REQ_FILE" ]; then
  log "ERROR: requirements.txt not found at repo root"
  exit 1
fi

CURRENT_HASH="$(shasum "$REQ_FILE" | awk '{print $1}')"
STORED_HASH=""

if [ -f "$REQ_HASH_FILE" ]; then
  STORED_HASH="$(cat "$REQ_HASH_FILE" || true)"
fi

if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
  log "requirements.txt changed or first install detected"
  log "Installing dependencies..."
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r "$REQ_FILE"
  echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
  log "Dependencies installed and hash updated"
else
  log "requirements.txt unchanged. Skipping dependency install."
fi

# 4) Ensure .env exists (create from .env.example if missing)
ENV_PATH="$ROOT_DIR/$ENV_FILE"
ENV_EXAMPLE_PATH="$ROOT_DIR/$ENV_EXAMPLE"

if [ ! -f "$ENV_PATH" ]; then
  if [ -f "$ENV_EXAMPLE_PATH" ]; then
    log "No $ENV_FILE found. Creating from $ENV_EXAMPLE"
    cp "$ENV_EXAMPLE_PATH" "$ENV_PATH"
    log "Created $ENV_FILE. Fill in secrets before using MCP/Twilio/LLM."
  else
    log "WARNING: No $ENV_FILE or $ENV_EXAMPLE found. Continuing without env file."
  fi
else
  log "Found env file: $ENV_FILE"
fi

# 5) Source .env and EXPORT variables so Python os.getenv() can read them
#    This is REQUIRED because MCP header expansion uses os.getenv() (not pydantic).
if [ -f "$ENV_PATH" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ENV_PATH"
  set +a
  log "Loaded environment variables from $ENV_FILE"
else
  log "WARNING: Skipping env load. $ENV_FILE not found at $ENV_PATH"
fi

# 6) Resolve MCP config path
# Prefer env var MCP_CONFIG_PATH if present; else fallback default.
MCP_CONFIG_PATH="${MCP_CONFIG_PATH:-$DEFAULT_MCP_CONFIG}"
log "Using MCP config: $MCP_CONFIG_PATH"

if [ ! -f "$MCP_CONFIG_PATH" ]; then
  log "ERROR: MCP config not found at: $MCP_CONFIG_PATH"
  log "Fix by setting MCP_CONFIG_PATH in .env or placing config at $DEFAULT_MCP_CONFIG"
  exit 1
fi

# 7) Start FastAPI app (service mode)
log "Starting FastAPI on port $PORT"
uvicorn src.app.main:app --host 0.0.0.0 --port "$PORT"