#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# schemathesis_determinism.sh — does the Schemathesis gate send the same cases twice?
#
#   bash scripts/tests/schemathesis_determinism.sh [--only <service…>]
#       service: server monitoring ca-issuer (default: all three)
#   bash scripts/tests/schemathesis_determinism.sh --compare <label> <log-a> [<log-b>]
#       only the evaluation of two protocols — what the hermetic test drives
#
# Per service it runs the gate's own step twice — run.sh unit --strict --step
# schemathesis --only <service> — with the pytest plugin schemathesis_curl_log.py,
# which writes every case as a curl command, and compares the two protocols line by
# line. A red gate run is only worth something if it lies in the diff and can be
# replayed: the same tree has to send the same cases.
#
# Prints `<service>: N cases, M differing lines` and exits 0 only if every service ran
# twice, both runs logged the same number of cases > 0 and no line differs. A run that
# failed or did not start, an empty protocol or a missing second run is exit 1 — the
# instrument never reads green when it did not measure. Exit 2: usage.
#
# AH_SCHEMATHESIS_EXAMPLES is left to run.sh, so the gate is measured as it is
# configured. The server suite uses the shared test DB: run it only when no other
# server suite runs on that DB. Sources the checkout's .devenv.sh like verify.sh
# (AH_DEVENV overrides the path); run.sh itself does not. AH_DETERMINISM_RUN_SH replaces
# run.sh — only for the hermetic test, which drives the run path with a fake.

set -uo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
RUN_SH="${AH_DETERMINISM_RUN_SH:-$ROOT/scripts/tests/run.sh}"

usage() { sed -n '/^#   bash/,/^#       only the evaluation/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

# compare <label> <log-a> [<log-b>] — the verdict over two protocols.
compare() {
  local label="$1" a="$2" b="${3-}" na nb diffs
  if [ ! -s "$a" ]; then echo "$label: the first run logged no case"; return 1; fi
  if [ -z "$b" ] || [ ! -e "$b" ]; then echo "$label: no second run to compare"; return 1; fi
  if [ ! -s "$b" ]; then echo "$label: the second run logged no case"; return 1; fi
  # Fail closed: a protocol that cannot be read, or a diff that cannot compare, is red.
  # grep -c '' counts an unterminated last line too, so no non-empty file reads as 0;
  # -a keeps a NUL byte from turning into a line end of its own.
  if ! na=$(grep -ac '' "$a" 2>&1) || ! nb=$(grep -ac '' "$b" 2>&1); then
    echo "$label: a protocol cannot be read"; return 1
  fi
  # -a: a byte that makes diff call the files binary would otherwise hide every line.
  local drc=0
  diff -q -a "$a" "$b" > /dev/null 2>&1 || drc=$?
  if [ "$drc" -gt 1 ]; then echo "$label: the protocols cannot be compared (diff exit $drc)"; return 1; fi
  # tr: a NUL byte must not reach the command substitution, which would drop it with a
  # warning. grep -c prints 0 and exits 1 when nothing differs; only the count is used.
  diffs=$(diff -a "$a" "$b" | tr -d '\000' | grep -c '^[<>]')
  echo "$label: $na cases, $diffs differing lines"
  if [ "$na" -ne "$nb" ]; then echo "$label: the runs logged $na and $nb cases"; return 1; fi
  # diff's own verdict decides as well: files it calls different are never green.
  [ "$diffs" -eq 0 ] && [ "$drc" -eq 0 ]
}

if [ "${1-}" = "--compare" ]; then
  if [ $# -lt 3 ] || [ $# -gt 4 ]; then usage; fi
  compare "$2" "$3" "${4-}"
  exit $?
fi

SERVICES=(server monitoring ca-issuer)
if [ $# -gt 0 ]; then
  if [ "$1" != "--only" ] || [ $# -lt 2 ]; then usage; fi
  shift
  SERVICES=("$@")
  for s in "${SERVICES[@]}"; do
    case "$s" in server|monitoring|ca-issuer) ;; *) echo "unknown service: $s" >&2; usage ;; esac
  done
fi

DEVENV="${AH_DEVENV:-$ROOT/.devenv.sh}"
if [ -f "$DEVENV" ]; then
  set +u   # the devenv is written for an interactive shell, not for nounset
  # shellcheck disable=SC1090
  . "$DEVENV" || echo "  (warning: $DEVENV could not be sourced)" >&2
  set +e -u   # review: ok a devenv's own set -e must not decide how the runs below are judged
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/ah-sth-determinism.XXXXXXXX") || { echo "mktemp failed" >&2; exit 2; }
trap 'rm -rf "$WORK"' EXIT

rc=0
for svc in "${SERVICES[@]}"; do
  for run in 1 2; do
    log="$WORK/$svc.$run.log"; out="$WORK/$svc.$run.out"
    : > "$log"
    # Its own AH_OUT_DIR: the evidence files of the checkout (.ah-out/last-unit.json)
    # must not be overwritten by a measuring run.
    AH_CURL_LOG="$log" AH_OUT_DIR="$WORK/out.$svc.$run" \
      PYTHONPATH="$ROOT/scripts/tests${PYTHONPATH:+:$PYTHONPATH}" \
      PYTEST_ADDOPTS="${PYTEST_ADDOPTS:+$PYTEST_ADDOPTS }-p schemathesis_curl_log" \
      bash "$RUN_SH" unit --strict --step schemathesis --only "$svc" > "$out" 2>&1
    status=$?
    if [ "$status" -ne 0 ]; then
      echo "$svc: run $run failed (run.sh exit $status), last lines:"
      tail -n 15 "$out" | sed 's/^/    /'
      rm -f "$log"   # no protocol, so the comparison below reports the missing run
      break
    fi
  done
  compare "$svc" "$WORK/$svc.1.log" "$WORK/$svc.2.log" || rc=1
done
exit "$rc"
