#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

# Ensure docker is on PATH in cron environments.
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/academic_${timestamp}.sql"

docker exec -i academic_db_postgres pg_dump -U academic academic > "$backup_file"
