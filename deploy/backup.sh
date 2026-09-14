#!/usr/bin/env sh
# Nightly Postgres backup for Attest Cloud. Usage: deploy/backup.sh [dest-dir]  (cron: 0 3 * * *)
set -eu
DEST="${1:-./backups}"; mkdir -p "$DEST"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f "$(dirname "$0")/docker-compose.yml" exec -T db pg_dump -U attest -Fc attest > "$DEST/attest-$STAMP.dump"
find "$DEST" -name 'attest-*.dump' -mtime +30 -delete
echo "backup written: $DEST/attest-$STAMP.dump"
