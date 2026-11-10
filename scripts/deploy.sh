#!/usr/bin/env bash
#
# deploy.sh: put one release of one tool live, prove that it is serving, and
# roll back by itself when it isn't.
#
#     deploy.sh <tool> <artifact.tar.gz>
#
# Layout on the target machine:
#
#     $DEPLOY_ROOT/<tool>/releases/<version>/   one directory per release, with its own .venv
#     $DEPLOY_ROOT/<tool>/current               symlink to the live release, switched atomically
#     $DEPLOY_ROOT/<tool>/deploys.log           one line per attempt: when, which version, outcome
#
# Settings (environment):
#
#     HEALTH_URL       endpoint that answers {"status": "ok", "version": "..."}   (required)
#     DEPLOY_ROOT      where tools live                       (default /opt/tools)
#     RESTART_CMD      how the service is (re)started         (default sudo systemctl restart tool-<tool>)
#     HEALTH_RETRIES   attempts before the release counts as broken   (default 30)
#     HEALTH_DELAY     seconds between attempts               (default 1)
#     KEEP_RELEASES    older releases to keep, besides the live one and the rollback target (default 3)
#     INSTALL_DEPS     1 = build the release's .venv from requirements.txt (default 1)
#
# Exit codes:
#
#     0   the new release is live and healthy
#     1   the new release failed; the previous release is live and healthy again
#     2   the first release of this tool failed; there is nothing to roll back to
#     3   the new release failed and so did the rollback: the tool is down
#     64  usage error, nothing was touched
#     75  another deploy of this tool is running, nothing was touched

set -euo pipefail

log() { printf '[deploy] %s\n' "$*"; }
usage() { echo "deploy.sh: $*" >&2; exit 64; }

[ $# -eq 2 ] || usage "expected <tool> <artifact.tar.gz>"
tool=$1 artifact=$2

# The tool name ends up in paths and in the restart command. Plain names only,
# and never one that starts with "-": ssh, rsync and systemctl would read that
# as an option instead of a name.
[[ $tool =~ ^[a-z0-9][a-z0-9-]*$ ]] || usage "invalid tool name: $tool"
[ -f "$artifact" ] || usage "artifact not found: $artifact"
[ -n "${HEALTH_URL:-}" ] || usage "HEALTH_URL is required"

root=${DEPLOY_ROOT:-/opt/tools}
restart_cmd=${RESTART_CMD:-"sudo systemctl restart tool-$tool"}
retries=${HEALTH_RETRIES:-30}
delay=${HEALTH_DELAY:-1}
keep=${KEEP_RELEASES:-3}
install=${INSTALL_DEPS:-1}

base="$root/$tool"
releases="$base/releases"
current="$base/current"
mkdir -p "$releases"

# One deploy per tool at a time. mkdir is atomic, so it works as a lock on
# every platform without extra tools.
lock="$base/.deploy.lock"
mkdir "$lock" 2>/dev/null || { echo "deploy.sh: another deploy of $tool is running ($lock)" >&2; exit 75; }
staging=""
# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() {
    if [ -n "$staging" ]; then rm -rf "$staging"; fi
    rmdir "$lock"
}
trap cleanup EXIT

record() { printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >> "$base/deploys.log"; }

# The version the health endpoint reports right now, or nothing.
serving() {
    python3 - "$HEALTH_URL" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        body = json.load(response)
    print(body.get("version", "") if body.get("status") == "ok" else "")
except Exception:
    print("")
PY
}

# Wait until the endpoint reports exactly this version. A service that is
# "active" but still runs the old code is not a successful deploy.
wait_for() {
    local want=$1 got="" attempt
    for ((attempt = 1; attempt <= retries; attempt++)); do
        got=$(serving)
        if [ "$got" = "$want" ]; then
            log "health check passed: serving $want"
            return 0
        fi
        sleep "$delay"
    done
    log "health check gave up after $retries attempts (serving '${got:-nothing}', wanted '$want')"
    return 1
}

# Point 'current' at a release with one rename(2): there is never a moment
# without a 'current', and never a half-switched one.
switch_to() {
    # Chained with &&: go_live runs inside an `if`, where `set -e` does not apply.
    ln -sfn "releases/$1" "$base/current.next" &&
        python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$base/current.next" "$current" &&
        log "current -> releases/$1"
}

restart() {
    log "restarting: $restart_cmd"
    TOOL=$tool DEPLOY_ROOT=$root bash -c "$restart_cmd"
}

# The health endpoint is the judge, not the exit code of the restart command:
# a restart that "fails" while the right version serves is fine, and a restart
# that "succeeds" while the old code keeps serving is not.
go_live() {
    switch_to "$1" || return 1
    restart || log "restart command exited non-zero; letting the health check decide"
    wait_for "$1"
}

# Keep the live release, the rollback target and the newest $keep others.
prune() {
    local dir name count=0
    # Release names are validated versions, so parsing ls is safe here.
    # shellcheck disable=SC2012
    while IFS= read -r dir; do
        name=$(basename "$dir")
        if [ "$name" = "$version" ] || [ "$name" = "$previous" ]; then continue; fi
        count=$((count + 1))
        if [ "$count" -gt "$keep" ]; then
            rm -rf "$dir"
            log "pruned old release $name"
        fi
    done < <(ls -1dt "$releases"/*/ 2>/dev/null)
}

# 1. Unpack next to the releases (same filesystem, so the move below is a rename)
#    and read the version that the build stamped into the artifact.
staging=$(mktemp -d "$releases/.incoming.XXXXXX")
tar -xzf "$artifact" -C "$staging"
[ -f "$staging/VERSION" ] || usage "artifact has no VERSION file"
version=$(tr -d '[:space:]' < "$staging/VERSION")
[[ $version =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || usage "invalid version in artifact: $version"

previous=""
if [ -L "$current" ]; then previous=$(basename "$(readlink "$current")"); fi

if [ "$previous" = "$version" ]; then
    log "$tool $version is already live; checking its health only"
    if wait_for "$version"; then exit 0; else exit 1; fi
fi

release="$releases/$version"
rm -rf "$release"
mv "$staging" "$release"
staging=""

# 2. Dependencies. Every release gets its own virtualenv, so a rollback needs
#    no reinstall. Failing here changes nothing: the live release is untouched.
if [ "$install" = 1 ] && [ -f "$release/requirements.txt" ]; then
    log "installing dependencies for $version"
    python3 -m venv "$release/.venv"
    "$release/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$release/requirements.txt"
fi

# 3. Switch, restart, verify.
log "deploying $tool $version (live now: ${previous:-nothing})"
if go_live "$version"; then
    record "$version" ok
    prune
    log "$tool $version is live"
    exit 0
fi
record "$version" failed

# 4. Roll back.
if [ -z "$previous" ]; then
    log "first deploy of $tool failed; there is nothing to roll back to"
    exit 2
fi
log "rolling back to $previous"
if go_live "$previous"; then
    record "$previous" rolled-back
    log "rolled back: $tool $previous is live again"
    exit 1
fi
record "$previous" rollback-failed
log "ROLLBACK FAILED: $tool is down and needs a person"
exit 3
