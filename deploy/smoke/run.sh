#!/usr/bin/env bash
# Boot the full stack production-style, run the smoke checks, always tear down.
# Exit code is the result of the checks. Usage: ./deploy/smoke/run.sh (any cwd).
set -euo pipefail

for tool in docker jq openssl curl; do
    command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: required tool '$tool' not found in PATH" >&2; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' (v2 plugin) is not available" >&2; exit 1; }

SMOKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SMOKE_DIR/docker-compose.smoke.yml"
[ -f "$COMPOSE_FILE" ] || { echo "ERROR: compose file not found: $COMPOSE_FILE" >&2; exit 1; }

COMPOSE=(docker compose -p inspectre-smoke -f "$COMPOSE_FILE" --env-file "$SMOKE_DIR/smoke.env")

# shellcheck source=checks.sh
source "$SMOKE_DIR/checks.sh"

cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then
        echo "=== smoke test FAILED (exit $status); container state and logs follow ===" >&2
        "${COMPOSE[@]}" ps -a >&2 || true
        "${COMPOSE[@]}" logs --no-color >&2 || true
    fi
    "${COMPOSE[@]}" down -v --remove-orphans >&2 || true
    exit "$status"
}
trap cleanup EXIT

# Clean slate: remove anything left by an aborted earlier run.
"${COMPOSE[@]}" down -v --remove-orphans

# Throwaway CA + server cert for the TLS-only Valkey (never committed).
CERT_DIR="$SMOKE_DIR/certs"
rm -rf "$CERT_DIR"
mkdir -p "$CERT_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=inspectre-smoke-ca" \
    -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=valkey" \
    -keyout "$CERT_DIR/valkey.key" -out "$CERT_DIR/valkey.csr" 2>/dev/null
openssl x509 -req -in "$CERT_DIR/valkey.csr" -days 1 -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial -out "$CERT_DIR/valkey.crt" \
    -extfile <(printf 'subjectAltName=DNS:valkey') 2>/dev/null
# The valkey container user must be able to read the (throwaway) key.
chmod 644 "$CERT_DIR"/*

"${COMPOSE[@]}" up -d --build --wait --wait-timeout "$BOOT_TIMEOUT"

run_checks
echo "Smoke checks passed."
