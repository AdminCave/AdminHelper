#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# schemathesis_determinism_test.sh — hermetic test for schemathesis_determinism.sh.
#
# The instrument is only worth something if it cannot read green without having
# measured. Two layers: the evaluation over fixture protocols (equal, differing, empty,
# one run only, different counts), and the run path with a fake run.sh that writes a
# protocol and exits as told — a failing run, an empty run and a missing second
# protocol must all be red. No Python, no schemathesis, no database.
#
# Run: bash scripts/tests/schemathesis_determinism_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TOOL="$HERE/schemathesis_determinism.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# expect <rc> <output-substring> <description> -- <command…>
expect() {
  local want="$1" text="$2" what="$3" out rc
  shift 4
  out=$("$@" 2>&1); rc=$?
  if [ "$rc" = "$want" ] && [[ "$out" == *"$text"* ]]; then ok "$what"
  else bad "$what (rc=$rc, want $want; output: $out)"; fi
}

A="$WORK/a.log"; B="$WORK/b.log"; C="$WORK/c.log"; D="$WORK/d.log"; E="$WORK/empty.log"
printf '%s\n' '["t1", "curl -X GET http://x/a"]' '["t1", "curl -X GET http://x/b"]' > "$A"
cp "$A" "$B"
printf '%s\n' '["t1", "curl -X GET http://x/a"]' '["t1", "curl -X GET http://x/c"]' > "$C"
{ cat "$A"; printf '%s\n' '["t1", "curl -X GET http://x/d"]'; } > "$D"
: > "$E"

echo "evaluation over fixture protocols"
expect 0 "svc: 2 cases, 0 differing lines" "equal protocols are green" -- bash "$TOOL" --compare svc "$A" "$B"
expect 1 "svc: 2 cases, 2 differing lines" "one differing case is red, counted on both sides" -- bash "$TOOL" --compare svc "$A" "$C"
expect 1 "the first run logged no case" "an empty first protocol is red" -- bash "$TOOL" --compare svc "$E" "$B"
expect 1 "the second run logged no case" "an empty second protocol is red" -- bash "$TOOL" --compare svc "$A" "$E"
expect 1 "no second run to compare" "a single protocol is red" -- bash "$TOOL" --compare svc "$A"
expect 1 "no second run to compare" "a missing second file is red" -- bash "$TOOL" --compare svc "$A" "$WORK/missing.log"
expect 1 "the runs logged 2 and 3 cases" "different case counts are red" -- bash "$TOOL" --compare svc "$A" "$D"
expect 1 "a protocol cannot be read" "an unreadable protocol is red, not 0 cases" -- bash "$TOOL" --compare svc "$A" "$WORK"
printf '%s' '["t1", "curl -X GET http://x/a"]' > "$WORK/nonl.a"; cp "$WORK/nonl.a" "$WORK/nonl.b"
expect 0 "svc: 1 cases, 0 differing lines" "an unterminated last line still counts as a case" \
  -- bash "$TOOL" --compare svc "$WORK/nonl.a" "$WORK/nonl.b"
printf 'a\000x\nb\n' > "$WORK/nul.a"; printf 'a\000y\nb\n' > "$WORK/nul.b"
expect 1 "svc: 2 cases, 2 differing lines" "protocols with a NUL byte are compared as text, not waved through" \
  -- bash "$TOOL" --compare svc "$WORK/nul.a" "$WORK/nul.b"
expect 2 "" "--compare without protocols is a usage error" -- bash "$TOOL" --compare svc
expect 2 "unknown service" "an unknown service is a usage error" -- bash "$TOOL" --only nope

# A fake run.sh: appends FAKE_LINES lines to $AH_CURL_LOG — the content of a line
# varies with FAKE_VARY and the run number — and exits FAKE_RC. Counts its runs.
FAKE="$WORK/run.sh"
cat > "$FAKE" <<'FAKE_EOF'
#!/usr/bin/env bash
n=$(($(cat "$FAKE_COUNT" 2>/dev/null || echo 0) + 1)); echo "$n" > "$FAKE_COUNT"
printf 'args=%s|addopts=%s|pythonpath=%s|out=%s\n' "$*" "$PYTEST_ADDOPTS" "$PYTHONPATH" "$AH_OUT_DIR" >> "$FAKE_COUNT.calls"
for i in $(seq 1 "${FAKE_LINES:-0}"); do
  if [ "${FAKE_VARY:-0}" = 1 ]; then echo "[\"t\", \"curl $i run$n\"]"; else echo "[\"t\", \"curl $i\"]"; fi >> "$AH_CURL_LOG"
done
[ -n "${FAKE_FAIL_RUN:-}" ] && [ "$n" = "$FAKE_FAIL_RUN" ] && { echo "fake: collection error"; exit 2; }
exit "${FAKE_RC:-0}"
FAKE_EOF
export AH_DETERMINISM_RUN_SH="$FAKE" AH_DEVENV="$WORK/no-devenv"

echo "run path with a fake run.sh"
expect 0 "monitoring: 3 cases, 0 differing lines" "two equal runs are green" \
  -- env FAKE_COUNT="$WORK/count.eq" FAKE_LINES=3 bash "$TOOL" --only monitoring
expect 1 "monitoring: 3 cases, 6 differing lines" "two differing runs are red" \
  -- env FAKE_COUNT="$WORK/count.vary" FAKE_LINES=3 FAKE_VARY=1 bash "$TOOL" --only monitoring
expect 1 "run 1 failed (run.sh exit 2)" "a failing first run is red" \
  -- env FAKE_COUNT="$WORK/count.fail1" FAKE_LINES=3 FAKE_FAIL_RUN=1 bash "$TOOL" --only monitoring
expect 1 "no second run to compare" "a failing second run is red" \
  -- env FAKE_COUNT="$WORK/count.fail2" FAKE_LINES=3 FAKE_FAIL_RUN=2 bash "$TOOL" --only monitoring
expect 1 "the first run logged no case" "a green run.sh that sent no case is red" \
  -- env FAKE_COUNT="$WORK/count.empty" FAKE_LINES=0 bash "$TOOL" --only monitoring
expect 1 "ca-issuer: 2 cases, 4 differing lines" "a run over two services judges each and is red" \
  -- env FAKE_COUNT="$WORK/count.two" FAKE_LINES=2 FAKE_VARY=1 bash "$TOOL" --only server ca-issuer
if [ "$(cat "$WORK/count.two" 2>/dev/null)" = 4 ]; then ok "every listed service ran twice"
else bad "every listed service ran twice (runs: $(cat "$WORK/count.two" 2>/dev/null))"; fi
# What the instrument hands run.sh: the gate step of that one service, the plugin, and an
# output directory of its own — the checkout's .ah-out evidence must stay untouched.
CALL=$(head -n 1 "$WORK/count.eq.calls" 2>/dev/null)
case "$CALL" in
  "args=unit --strict --step schemathesis --only monitoring|"*) ok "run.sh runs the gate step of that service" ;;
  *) bad "run.sh runs the gate step of that service ($CALL)" ;;
esac
case "$CALL" in *"addopts="*"-p schemathesis_curl_log"*) ok "the plugin is loaded" ;; *) bad "the plugin is loaded ($CALL)" ;; esac
case "$CALL" in *"pythonpath=$HERE"*) ok "scripts/tests is on PYTHONPATH" ;; *) bad "scripts/tests is on PYTHONPATH ($CALL)" ;; esac
OUT=${CALL##*|out=}
case "$OUT" in
  ""|*/.ah-out|*/.ah-out/*) bad "a measuring run writes outside the checkout's .ah-out ($OUT)" ;;
  *) ok "a measuring run writes outside the checkout's .ah-out" ;;
esac

if sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$HERE/run.sh" | grep -qw schemathesis_determinism_test; then
  ok "schemathesis_determinism_test is registered in AH_SCRIPT_TESTS_DEFAULT"
else bad "schemathesis_determinism_test missing from AH_SCRIPT_TESTS_DEFAULT"; fi

echo ""
echo "schemathesis_determinism_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
