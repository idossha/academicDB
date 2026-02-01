#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

# Ensure uv is on PATH in cron environments.
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

# Configure your papers directory via PAPERS_DIR env var.
PAPERS_DIR="${PAPERS_DIR:-$ROOT_DIR/papers}"

uv run ingest_papers.py "$PAPERS_DIR" --recursive > /dev/null
