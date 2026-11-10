#!/usr/bin/env bash
#
# build_release.sh: package one tool as an immutable release artifact.
#
#     scripts/build_release.sh <tool> <commit-sha> <output-dir>
#
# The artifact holds the tool's runtime files plus a VERSION file with the
# commit it was built from. Tests, virtualenvs and caches stay out. The same
# artifact that passed CI is the one that gets deployed; nothing is rebuilt
# on the server.
#
# Prints the path of the artifact it wrote.

set -euo pipefail

[ $# -eq 3 ] || { echo "usage: build_release.sh <tool> <commit-sha> <output-dir>" >&2; exit 64; }
tool=$1 sha=$2 out=$3

[[ $tool =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "invalid tool name: $tool" >&2; exit 64; }
[[ $sha =~ ^[0-9a-f]{7,40}$ ]] || { echo "invalid commit sha: $sha" >&2; exit 64; }
[ -f "tools/$tool/requirements.txt" ] || { echo "no such tool: tools/$tool" >&2; exit 64; }

version=${sha:0:12}
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

tar -C "tools/$tool" \
    --exclude=tests --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.coverage --exclude=junit.xml --exclude=VERSION \
    -cf - . | tar -C "$stage" -xf -
printf '%s\n' "$version" > "$stage/VERSION"

mkdir -p "$out"
artifact="$out/$tool-$version.tar.gz"
tar -C "$stage" -czf "$artifact" .
echo "$artifact"
