#!/usr/bin/env bash
# Smoke checks. Sourced by run.sh, which provides $COMPOSE (the compose command
# array prefix); not meant to be executed directly.

API=http://localhost:18000
SPA=http://localhost:18080
BOOT_TIMEOUT=180   # seconds, overall budget for services to become ready
SETTLE_SECONDS=10  # grace period before re-checking for crash loops

pass() { echo "PASS: $*"; }

# Print the message and abort the whole run (run.sh's EXIT trap dumps logs).
fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# Print "<service> <state> <health> <exitcode>" per container, one per line
# ("-" when the service has no healthcheck, so `read` never sees an empty field).
_service_states() {
    "${COMPOSE[@]}" ps -a --format json |
        jq -r '[.Service, .State, (if (.Health // "") == "" then "-" else .Health end), (.ExitCode | tostring)] | join(" ")'
}

# Succeeds when every service is running (and healthy where a healthcheck is
# defined), with the s3-init one-shot exited 0. Prints the first offender.
_services_ready() {
    local states service state health exit_code
    states=$(_service_states) || return 1
    [ -n "$states" ] || { echo "no services found"; return 1; }
    while read -r service state health exit_code; do
        if [ "$service" = s3-init ]; then
            [ "$state" = exited ] && [ "$exit_code" = 0 ] || { echo "$service: $state (exit $exit_code)"; return 1; }
            continue
        fi
        [ "$state" = running ] || { echo "$service: $state"; return 1; }
        if [ "$health" != - ] && [ "$health" != healthy ]; then
            echo "$service: $health"
            return 1
        fi
    done <<<"$states"
}

check_boot() {
    local deadline=$((SECONDS + BOOT_TIMEOUT)) offender body code

    # (a) every service running/healthy, s3-init exited 0
    until offender=$(_services_ready); do
        [ "$SECONDS" -lt "$deadline" ] || fail "services not ready within ${BOOT_TIMEOUT}s ($offender)"
        sleep 2
    done
    pass "all services running and healthy, s3-init exited 0"

    # (b) a crash-looping container can look "running" at any single instant, so
    # wait, then require no restarting state and zero worker restarts.
    sleep "$SETTLE_SECONDS"
    offender=$(_services_ready) || fail "service unstable after ${SETTLE_SECONDS}s settle ($offender)"
    if _service_states | grep -q ' restarting '; then
        fail "a service is restarting"
    fi
    local worker_id restarts
    worker_id=$("${COMPOSE[@]}" ps -q worker)
    [ -n "$worker_id" ] || fail "worker container not found"
    restarts=$(docker inspect -f '{{.RestartCount}}' "$worker_id")
    [ "$restarts" = 0 ] || fail "worker restarted $restarts time(s)"
    pass "no restarts after ${SETTLE_SECONDS}s settle (worker RestartCount 0)"

    # (c) API liveness
    curl -fsS --max-time 10 "$API/healthz/" >/dev/null || fail "GET $API/healthz/ failed"
    pass "api /healthz/ returns 200"

    # (d) SPA liveness
    curl -fsS --max-time 10 "$SPA/healthz" >/dev/null || fail "GET $SPA/healthz failed"
    pass "spa /healthz returns 200"

    # (e) SPA serves the Angular shell
    body=$(curl -fsS --max-time 10 "$SPA/") || fail "GET $SPA/ failed"
    case "$body" in *"<app-root"*) ;; *) fail "$SPA/ does not contain <app-root" ;; esac
    pass "spa / serves the Angular index"

    # (f) nginx proxies /api/ to the backend
    code=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "$SPA/api/projects/") || fail "GET $SPA/api/projects/ failed"
    [ "$code" = 200 ] || fail "GET $SPA/api/projects/ returned $code"
    pass "spa proxies /api/projects/ to the api (200)"

    # (g) the worker is actually consuming from the broker
    local ping
    ping=$("${COMPOSE[@]}" exec -T worker celery -A inspectre inspect ping --timeout 10 2>&1) ||
        fail "celery inspect ping failed: $ping"
    case "$ping" in *pong*) ;; *) fail "celery inspect ping did not return pong: $ping" ;; esac
    pass "worker answers celery inspect ping"
}

run_checks() {
    check_boot
}
