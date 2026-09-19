#!/usr/bin/env bash
# One-command Attest Cloud on a fresh Ubuntu/Debian host.
#
#   curl -fsSL https://raw.githubusercontent.com/dev-prathap/ATTEST/main/deploy/bootstrap.sh | \
#     ATTEST_DOMAIN=attestlayer.dev ATTEST_ACME_EMAIL=you@example.com bash
#
# Point api.$ATTEST_DOMAIN and app.$ATTEST_DOMAIN at this host's IP first (A records).
set -euo pipefail

: "${ATTEST_DOMAIN:?set ATTEST_DOMAIN (e.g. attestlayer.dev)}"
: "${ATTEST_ACME_EMAIL:?set ATTEST_ACME_EMAIL (for Let's Encrypt)}"
REPO="${ATTEST_REPO:-https://github.com/dev-prathap/ATTEST}"
DIR="${ATTEST_DIR:-/opt/attest}"

say() { printf "\n\033[1m▸ %s\033[0m\n" "$*"; }

say "packages"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
command -v git >/dev/null || (apt-get update -qq && apt-get install -y -qq git)

say "source → $DIR"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone --depth 1 "$REPO" "$DIR"; fi
cd "$DIR/deploy"

say "secrets"
gen() { openssl rand -hex 24; }
if [ ! -f .env ]; then
  cat > .env <<ENV
ATTEST_DOMAIN=$ATTEST_DOMAIN
ATTEST_ACME_EMAIL=$ATTEST_ACME_EMAIL
PG_PASSWORD=$(gen)
ATTEST_CLOUD_BOOTSTRAP_TOKEN=$(gen)
ATTEST_SIGNING_KEY=$(gen)
ATTEST_CORS_ORIGINS=https://app.$ATTEST_DOMAIN
# optional: SLACK_SIGNING_SECRET, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_TEAM, STRIPE_PRICE_PRO,
#           OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_REDIRECT_URI, ATTEST_SESSION_SECRET, SENTRY_DSN
ENV
  chmod 600 .env
  echo "wrote $DIR/deploy/.env (generated secrets)"
else
  echo ".env exists — keeping it"
fi
set -a; . ./.env; set +a

say "build and start"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

say "wait for health"
for _ in $(seq 1 60); do
  if docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8400/healthz')" 2>/dev/null; then
    break
  fi
  sleep 3
done

say "cron: nightly backup, daily checkpoint"
install -m 755 backup.sh /usr/local/bin/attest-backup
cat > /usr/local/bin/attest-checkpoint <<'CRON'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/attest/deploy && set -a && . ./.env && set +a
key="${ATTEST_ADMIN_KEY:-}"
[ -n "$key" ] || { echo "set ATTEST_ADMIN_KEY in /opt/attest/deploy/.env to enable checkpoints"; exit 0; }
curl -fsS -X POST "https://api.$ATTEST_DOMAIN/v1/ledger/checkpoint" -H "Authorization: Bearer $key" >/dev/null
CRON
chmod 755 /usr/local/bin/attest-checkpoint
( crontab -l 2>/dev/null | grep -v attest- ; \
  echo "0 3 * * * /usr/local/bin/attest-backup /var/backups/attest >/dev/null 2>&1" ; \
  echo "30 3 * * * /usr/local/bin/attest-checkpoint >/dev/null 2>&1" ) | crontab -

say "first org"
echo "Create it with the bootstrap token from $DIR/deploy/.env:"
cat <<CMD

  curl -X POST https://api.$ATTEST_DOMAIN/v1/orgs \\
       -H "X-Bootstrap-Token: \$ATTEST_CLOUD_BOOTSTRAP_TOKEN" -H "Content-Type: application/json" \\
       -d '{"name": "Acme", "domain": "acme.com"}'

Then open https://app.$ATTEST_DOMAIN → Settings → paste the admin key it returned.
Add ATTEST_ADMIN_KEY=<that key> to $DIR/deploy/.env so the nightly checkpoint runs.
CMD
