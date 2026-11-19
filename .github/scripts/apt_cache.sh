#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# apt_cache.sh — the apt steps of the CI jobs that keep their archives in a cache (R-1602).
#   apt_cache.sh key <dir> <prefix> <pkg…>  reads the package index (apt-get update) and prints
#       <prefix>-<hash>, the hash taken over what `--print-uris` lists for the packages: URL,
#       file name, size and checksum of every archive the runner lacks. Run it before the cache
#       is restored into <dir>, so the list is the whole package set and the key changes exactly
#       when one of the archives does.
#   apt_cache.sh install <dir> <pkg…>  keeps only the archives in <dir> whose SHA256 the index
#       names (apt_archives_verify.sh), downloads the rest into <dir>, then installs.
# A mirror that crawls outlasts an attempt; what the attempt fetched stays in <dir> for the
# cache to save, so the next run only fetches the rest. A mirror ahead of the index answers 404
# for a superseded version (PR #591): after a failed attempt the index is read again.
# Ownership of <dir> is left to the job: a step killed by its limit never reaches a chown here.
# APT_CACHE_ATTEMPTS and APT_CACHE_SECONDS (3, 180) and RETRY_PAUSE are for the tests.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
attempts=${APT_CACHE_ATTEMPTS:-3} seconds=${APT_CACHE_SECONDS:-180}
usage="usage: apt_cache.sh key <dir> <prefix> <pkg…> | install <dir> <pkg…>"
[ $# -ge 3 ] || { echo "$usage" >&2; exit 2; }
cmd=$1 dir=$2
shift 2
opts=(-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o "Dir::Cache::Archives=$dir")

case $cmd in
key)
    prefix=$1
    shift
    [ $# -ge 1 ] || { echo "$usage" >&2; exit 2; }
    mkdir -p "$dir/partial"
    bash "$here/retry.sh" "$attempts" "$seconds" sudo apt-get "${opts[@]}" update -qq >&2
    uris=$(sudo apt-get "${opts[@]}" install -y -qq --no-install-recommends --print-uris "$@")
    sum=$(printf '%s\n' "$uris" | { grep "^'" || true; } | LC_ALL=C sort | sha256sum)
    echo "$prefix-${sum:0:16}"
    ;;
install)
    mkdir -p "$dir/partial"
    bash "$here/apt_archives_verify.sh" "$dir"
    rc=0
    for ((i = 1; i <= attempts; i++)); do
        rc=0
        bash "$here/retry.sh" 1 "$seconds" sudo apt-get "${opts[@]}" install -y -qq \
            --no-install-recommends --download-only "$@" || rc=$?
        [ "$rc" -eq 0 ] && break
        echo "apt_cache.sh: download attempt $i/$attempts ended with $rc" >&2
        if [ "$i" -lt "$attempts" ]; then
            bash "$here/retry.sh" 1 "$seconds" sudo apt-get "${opts[@]}" update -qq >&2 || true
        fi
    done
    [ "$rc" -eq 0 ] || exit "$rc"
    # A kill above never hits dpkg: the install reads the downloaded archives only.
    sudo apt-get "${opts[@]}" install -y -qq --no-install-recommends "$@"
    sudo apt-get "${opts[@]}" autoclean
    ;;
*)
    echo "$usage" >&2
    exit 2
    ;;
esac
