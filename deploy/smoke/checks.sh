#!/usr/bin/env bash
# Smoke checks. Sourced by run.sh, which provides $COMPOSE (the compose command
# array prefix); not meant to be executed directly.

API=http://localhost:18000
SPA=http://localhost:18080
BOOT_TIMEOUT=180   # seconds, overall budget for services to become ready
SETTLE_SECONDS=10  # grace period before re-checking for crash loops
UPLOAD_TIMEOUT=60  # seconds to wait for the worker to process an upload
SMOKE_HOST=inspectre-smoke.test  # non-default ALLOWED_HOSTS entry (smoke.env), sent as the Host header
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fixtures"

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
        jq -rs 'flatten | .[] | [.Service, .State, (if (.Health // "") == "" then "-" else .Health end), (.ExitCode | tostring)] | join(" ")'
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
    # wait, then require no restarting state. The worker has no restart policy (a
    # crash shows as exited, caught above), so its RestartCount check is a backstop.
    sleep "$SETTLE_SECONDS"
    offender=$(_services_ready) || fail "service unstable after ${SETTLE_SECONDS}s settle ($offender)"
    if _service_states | grep -q ' restarting '; then
        fail "a service is restarting"
    fi
    local worker_id restarts
    worker_id=$("${COMPOSE[@]}" ps -q worker)
    [ -n "$worker_id" ] || fail "worker container not found"
    local entry
    entry=$(docker inspect -f '{{.Path}}' "$worker_id")
    [ "$entry" = celery ] || fail "worker entrypoint is '$entry', expected bare 'celery' (tini must be bypassed)"
    restarts=$(docker inspect -f '{{.RestartCount}}' "$worker_id")
    [ "$restarts" = 0 ] || fail "worker restarted $restarts time(s)"
    pass "no restarts after ${SETTLE_SECONDS}s settle (worker RestartCount 0)"

    # (c) API liveness
    curl -fsS --max-time 10 -H "Host: $SMOKE_HOST" "$API/healthz/" >/dev/null || fail "GET $API/healthz/ failed"
    pass "api /healthz/ returns 200"

    # (d) SPA liveness
    curl -fsS --max-time 10 -H "Host: $SMOKE_HOST" "$SPA/healthz" >/dev/null || fail "GET $SPA/healthz failed"
    pass "spa /healthz returns 200"

    # (e) SPA serves the Angular shell
    body=$(curl -fsS --max-time 10 -H "Host: $SMOKE_HOST" "$SPA/") || fail "GET $SPA/ failed"
    case "$body" in *"<app-root"*) ;; *) fail "$SPA/ does not contain <app-root" ;; esac
    pass "spa / serves the Angular index"

    # (f) nginx proxies /api/ to the backend
    code=$(curl -sS --max-time 10 -H "Host: $SMOKE_HOST" -o /dev/null -w '%{http_code}' "$SPA/api/projects/") || fail "GET $SPA/api/projects/ failed"
    [ "$code" = 200 ] || fail "GET $SPA/api/projects/ returned $code"
    pass "spa proxies /api/projects/ to the api (200)"

    # (g) the worker is actually consuming from the broker
    # `--timeout 10` only bounds reply collection, not broker connect, so wrap the
    # whole probe in `timeout` (run inside the container: portable, kills celery
    # itself). Expiry exits 124, which is just a failed attempt for the retry loop.
    local ping ping_deadline=$((SECONDS + 60))
    until ping=$("${COMPOSE[@]}" exec -T worker timeout 30 celery -A inspectre inspect ping --timeout 10 2>&1) &&
        [[ "$ping" == *pong* ]]; do
        [ "$SECONDS" -lt "$ping_deadline" ] || fail "worker never answered celery inspect ping: $ping"
        sleep 5
    done
    pass "worker answers celery inspect ping"
}

# POST a screenshot as a new test in run $1 (image $2); print the response JSON.
_upload_test() {
    curl -sS --fail-with-body --max-time 30 -H "Host: $SMOKE_HOST" -X POST "$API/tests" \
        -F "run_id=$1" -F "name=Home" -F "browser=Chrome" \
        -F "size=1024" -F "screenshot=@$FIXTURES/$2"
}

# Poll test $1 until status is done (prints the final JSON); fail at once on
# status "failed", or when still not done after UPLOAD_TIMEOUT seconds.
_wait_test_done() {
    local deadline=$((SECONDS + UPLOAD_TIMEOUT)) body status
    while :; do
        body=$(curl -fsS --max-time 10 -H "Host: $SMOKE_HOST" "$API/tests/$1/status") || fail "GET $API/tests/$1/status failed"
        status=$(jq -r .status <<<"$body")
        case "$status" in
            done) echo "$body"; return 0 ;;
            failed) fail "test $1 processing failed (status=failed): $body" ;;
        esac
        [ "$SECONDS" -lt "$deadline" ] || fail "test $1 not done after ${UPLOAD_TIMEOUT}s (status=$status)"
        sleep 1
    done
}

# Create a run in Smoke/Boot; print "<id> <sequential_id>".
_create_run() {
    curl -sS --fail-with-body --max-time 10 -H "Host: $SMOKE_HOST" -X POST "$API/runs" -d project=Smoke -d suite=Boot | jq -r '"\(.id) \(.sequential_id)"'
}

# Full pipeline: api -> S3 -> worker -> ImageMagick diff -> validate verdict.
check_upload_roundtrip() {
    local run_id seq test_id body verdict

    # First submission for a fresh key: nothing to diff against, so a new baseline.
    read -r run_id seq < <(_create_run)
    [ -n "$run_id" ] && [ "$run_id" != null ] || fail "POST /runs returned no run id"
    test_id=$(_upload_test "$run_id" baseline.png | jq -r .id)
    [ -n "$test_id" ] && [ "$test_id" != null ] || fail "POST /tests returned no test id"
    body=$(_wait_test_done "$test_id")
    [ "$(jq -r .is_new_baseline <<<"$body")" = true ] || fail "first upload is not a new baseline: $body"
    pass "baseline upload processed by the worker (is_new_baseline)"

    # Approve it as the baseline (PATCH /tests/:id, docs/api.md), so the next
    # upload for the same key is actually diffed.
    curl -sS --fail-with-body --max-time 10 -H "Host: $SMOKE_HOST" -X PATCH "$API/tests/$test_id" -d "test[baseline]=true" >/dev/null ||
        fail "PATCH $API/tests/$test_id (set baseline) failed"

    # Same key, different image: ImageMagick must run and report a failed diff.
    read -r run_id seq < <(_create_run)
    test_id=$(_upload_test "$run_id" changed.png | jq -r .id)
    [ -n "$test_id" ] && [ "$test_id" != null ] || fail "second POST /tests returned no test id"
    body=$(_wait_test_done "$test_id")
    [ "$(jq -r .pass <<<"$body")" = false ] || fail "changed screenshot unexpectedly passed: $body"
    [ "$(jq -r .is_new_baseline <<<"$body")" = false ] || fail "changed screenshot was not diffed against the baseline: $body"
    pass "changed upload diffed against baseline (pass=false)"

    # The CI-facing verdict for that run must be "failed".
    verdict=$(curl -fsS --max-time 10 -H "Host: $SMOKE_HOST" "$SPA/api/projects/smoke/suites/boot/runs/$seq/validate/" | jq -r .status) ||
        fail "GET run validate failed"
    [ "$verdict" = failed ] || fail "run validate status is '$verdict', expected 'failed'"
    pass "run validate endpoint reports failed"
}

run_checks() {
    check_boot
    check_upload_roundtrip
    local offender
    offender=$(_services_ready) || fail "service not healthy after the upload round trip ($offender)"
    pass "all services still running and healthy after the upload round trip"
}
