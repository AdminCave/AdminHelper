#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# retry.sh <attempts> <seconds> <command…> — runs the command up to <attempts> times, each
# attempt under `timeout <seconds>`, and stops at the first success. For the downloads of the
# CI jobs: a mirror or CDN that stalls or crawls hangs a download without failing it, so the
# step's own limit used to be the only stop, and it cost the whole job (R-1130, R-1160).
# Exit: 0 on success, else the exit of the last attempt (124 when it ran out of time).
# Only for commands that are safe to run again after a kill — a download, not dpkg.

set -uo pipefail

[ $# -ge 3 ] || { echo "usage: retry.sh <attempts> <seconds> <command…>" >&2; exit 2; }
attempts=$1 seconds=$2 pause=${RETRY_PAUSE:-5}
shift 2

rc=0
for ((i = 1; i <= attempts; i++)); do
    rc=0
    timeout --kill-after=10 "$seconds" "$@" || rc=$?
    [ "$rc" -eq 0 ] && exit 0
    echo "retry.sh: attempt $i/$attempts of '$*' ended with $rc" >&2
    [ "$i" -lt "$attempts" ] && sleep "$pause"
done
exit "$rc"
