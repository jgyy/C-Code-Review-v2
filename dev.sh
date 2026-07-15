#!/usr/bin/env bash
# Spin up the C-Code-Review-v2 backend (FastAPI/uvicorn) and frontend (Next.js)
# dev servers in a single tmux session so you don't have to remember the
# commands or juggle multiple terminals.
#
# Usage:
#   ./dev.sh          # start both servers in a tmux session named "c-code-review"
#   ./dev.sh stop      # kill the tmux session
#
# Backend:  http://localhost:8000
# Frontend: http://localhost:3000
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="c-code-review"

if [[ "${1:-}" == "stop" ]]; then
  tmux kill-session -t "$SESSION" 2>/dev/null && echo "Stopped $SESSION" || echo "$SESSION is not running"
  exit 0
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required. Install it (e.g. 'sudo pacman -S tmux') and re-run." >&2
  exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already running. Attach with: tmux attach -t $SESSION"
  exit 0
fi

# --- Backend setup -----------------------------------------------------
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating backend virtualenv..."
  PYBIN="$(command -v python3.12 || command -v python3.11 || command -v python3.13 || command -v python3)"
  (cd "$BACKEND_DIR" && "$PYBIN" -m venv .venv)
fi

echo "Installing backend dependencies..."
if command -v uv >/dev/null 2>&1; then
  (cd "$BACKEND_DIR" && uv pip install --python .venv/bin/python -q -r requirements.txt)
else
  (cd "$BACKEND_DIR" && .venv/bin/python -m pip install -q -r requirements.txt)
fi

if [[ ! -f "$BACKEND_DIR/.env" && -f "$BACKEND_DIR/.env.example" ]]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  echo "Created backend/.env from .env.example — fill in your API keys/secrets before this will work."
fi

# --- Frontend setup ------------------------------------------------------
FRONTEND_DIR="$ROOT_DIR/frontend"

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found. Enabling via corepack..."
  corepack enable && corepack prepare pnpm@latest --activate
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies (pnpm install)..."
  (cd "$FRONTEND_DIR" && pnpm install)
fi

if [[ ! -f "$FRONTEND_DIR/.env.local" && -f "$FRONTEND_DIR/.env.local.example" ]]; then
  cp "$FRONTEND_DIR/.env.local.example" "$FRONTEND_DIR/.env.local"
  echo "Created frontend/.env.local from .env.local.example."
fi

# --- Launch tmux session ---------------------------------------------
tmux new-session -d -s "$SESSION" -n backend bash -c \
  "cd '$BACKEND_DIR' && ./.venv/bin/python -m uvicorn main:app --reload --port 8000; exec bash"

tmux new-window -t "$SESSION" -n frontend bash -c \
  "cd '$FRONTEND_DIR' && pnpm dev; exec bash"

tmux select-window -t "$SESSION:backend"

echo "Started tmux session '$SESSION' with windows: backend (http://localhost:8000), frontend (http://localhost:3000)"
echo "Attach with:  tmux attach -t $SESSION"
echo "Stop with:    ./dev.sh stop"
