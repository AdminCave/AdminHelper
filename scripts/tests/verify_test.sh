#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# verify_test.sh — hermetic test for scripts/dev/verify.sh.
#
# verify.sh's whole job is to turn a component name into the right run.sh call
# with the right environment resolved. So it is checked against a FAKE run.sh in
# a throwaway checkout: what arrives there — layer, flags, AH_ARGS, cwd — is
# exactly what this wrapper is responsible for. No real suite runs, nothing is
# installed, and the developer's own tree is never used as the target.
#
# Run: bash scripts/tests/verify_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_ARGS AH_ONLY AH_STRICT AH_OUT_DIR AH_TEST_DB AH_DEVENV

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
VERIFY="$REPO_ROOT/scripts/dev/verify.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v python3 >/dev/null 2>&1 \
  || { echo "SKIP: python3 not available — the JSON assertions cannot run"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# mk_tree <dir> <marker> — a checkout whose run.sh only records how it was called
mk_tree() {
  local dir="$1" marker="$2"
  mkdir -p "$dir/scripts/tests" "$dir/.crabbox-out"
  cat > "$dir/scripts/tests/run.sh" <<EOF
#!/usr/bin/env bash
{
  echo "marker=$marker"
  echo "args=\$*"
  echo "ah_args=\${AH_ARGS-<unset>}"
  echo "devenv_marker=\${FIXTURE_DEVENV-<unset>}"
  echo "cwd=\$PWD"
} > "$dir/called.txt"
out="\${AH_OUT_DIR:-$dir/.crabbox-out}"
mkdir -p "\$out"
if [ -n "\${FIXTURE_TRUNCATE:-}" ]; then
  printf '{\n  "layer": "%s"' "\$1" > "\$out/last-\$1.json"
elif [ -z "\${FIXTURE_NO_ARTIFACT:-}" ]; then
  printf '{\n  "layer": "%s",\n  "test_skips": []\n}\n' "\$1" > "\$out/last-\$1.json"
fi
exit "\${FIXTURE_RC:-0}"
EOF
  chmod +x "$dir/scripts/tests/run.sh"
}

A="$WORK/treeA"; mk_tree "$A" "A"
B="$WORK/treeB"; mk_tree "$B" "B"
printf 'export FIXTURE_DEVENV=sourced\n' > "$A/.devenv.sh"

run_v() { OUT=$(bash "$VERIFY" "$@" 2>&1); rc=$?; }
called() { grep -m1 "^$1=" "$A/called.txt" 2>/dev/null | cut -d= -f2-; }
rm -f "$A/called.txt" "$B/called.txt"

# ══ argument handling ═════════════════════════════════════════════════════════
echo "── arguments ──"
run_v --tree "$A"
[ $rc -eq 2 ] && grep -q "needs a component" <<<"$OUT" && ok "no component -> exit 2" || bad "bare call: rc=$rc"

run_v server web --tree "$A"
[ $rc -eq 2 ] && grep -q "unexpected argument: web" <<<"$OUT" && ok "second component -> exit 2" || bad "two components: rc=$rc"

run_v server --bogus --tree "$A"
[ $rc -eq 2 ] && grep -q "unknown flag: --bogus" <<<"$OUT" && ok "unknown flag -> exit 2" || bad "unknown flag: rc=$rc"

run_v server --tree
[ $rc -eq 2 ] && grep -q "needs a path" <<<"$OUT" && ok "--tree without a path -> exit 2" || bad "bare --tree: rc=$rc"

run_v server --tree "$WORK/nowhere"
[ $rc -eq 2 ] && grep -q "no such tree" <<<"$OUT" && ok "missing tree -> exit 2" || bad "missing tree: rc=$rc"

mkdir -p "$WORK/notacheckout"
run_v server --tree "$WORK/notacheckout"
[ $rc -eq 2 ] && grep -q "not an AdminHelper checkout" <<<"$OUT" \
  && ok "a directory without run.sh -> exit 2" || bad "not-a-checkout: rc=$rc"

# Without --tree the wrapper must target ITS OWN checkout. Proven without running
# a suite: the real run.sh rejects an unknown component before any step starts.
run_v nixkomponente
[ $rc -eq 2 ] && grep -q "unknown AH_ONLY key: 'nixkomponente'" <<<"$OUT" \
  && ok "no --tree targets the wrapper's own checkout" || bad "default tree: rc=$rc out=$OUT"

# ══ what reaches run.sh ═══════════════════════════════════════════════════════
echo "── the call verify.sh builds ──"
run_v scripts --tree "$A"
[ "$(called marker)" = "A" ] && ok "--tree runs the target tree's run.sh" || bad "marker=$(called marker)"
[ "$(called args)" = "quick --only scripts" ] \
  && ok "component -> quick --only <component> (lint AND unit, not unit alone)" || bad "args=$(called args)"
[ "$(called cwd)" = "$A" ] && ok "the suite runs with the tree as cwd" || bad "cwd=$(called cwd)"
[ "$(called devenv_marker)" = "sourced" ] && ok "the tree's .devenv.sh is sourced" || bad "devenv: $(called devenv_marker)"

# A checkout without a .devenv.sh is normal (a crabbox box has none) and must not
# be an error — treeB deliberately has no devenv file.
run_v scripts --tree "$B"
[ $rc -eq 0 ] && grep -q "^marker=B" "$B/called.txt" \
  && ok "a tree without .devenv.sh is not an error" || bad "no-devenv tree: rc=$rc out=$OUT"
grep -q "warning" <<<"$OUT" && bad "a missing devenv file warned" || ok "a missing devenv file is silent"

run_v scripts --strict --tree "$A"
[ "$(called args)" = "quick --only scripts --strict" ] && ok "--strict is forwarded" || bad "args=$(called args)"

run_v all --tree "$A"
[ "$(called args)" = "quick" ] && ok "'all' means the whole quick layer" || bad "args=$(called args)"
python3 -c "
import json
d=json.load(open('$A/.crabbox-out/last-verify.json'))
assert d['layer']=='quick' and d['component']=='all', d
" 2>/dev/null && ok "'all' reads the quick-layer artifact too" || bad "all-layer artifact"

run_v server --tree "$A" -- tests/test_auth.py -k lifecycle
[ "$(called ah_args)" = "tests/test_auth.py -k lifecycle" ] \
  && ok "-- args reach the suite as AH_ARGS" || bad "ah_args=$(called ah_args)"
run_v server --tree "$A"
[ -z "$(called ah_args)" ] && ok "no -- args means an empty AH_ARGS" || bad "ah_args=$(called ah_args)"

# AH_DEVENV overrides which file is sourced — that is how a box without a devenv
# file, or a test like this one, stays in control of the environment.
printf 'export FIXTURE_DEVENV=override\n' > "$WORK/other-devenv.sh"
OUT=$(AH_DEVENV="$WORK/other-devenv.sh" bash "$VERIFY" scripts --tree "$A" 2>&1)
[ "$(called devenv_marker)" = "override" ] && ok "AH_DEVENV overrides the devenv file" || bad "devenv: $(called devenv_marker)"

# ══ exit code and artifact ════════════════════════════════════════════════════
echo "── exit code and last-verify.json ──"
OUT=$(FIXTURE_RC=3 bash "$VERIFY" scripts --tree "$A" 2>&1); rc=$?
[ $rc -eq 3 ] && ok "the suite's exit code is passed through" || bad "rc=$rc (expected 3)"

run_v scripts --tree "$A" -- tests/x.py
ART="$A/.crabbox-out/last-verify.json"
[ -f "$ART" ] && ok "last-verify.json is written next to the run artifact" || bad "no $ART"
python3 -c "
import json
d=json.load(open('$ART'))
assert d['component']=='scripts', d
assert d['args']=='tests/x.py', d
assert d['tree']=='$A', d
assert d['layer']=='quick', d
" 2>/dev/null && ok "artifact: valid JSON with component, args, tree" || bad "artifact content: $(cat "$ART")"

# ══ the artifact may only ever describe THIS run ══════════════════════════════
echo "── stale evidence ──"
# A run that writes nothing must not leave the previous run's record behind,
# relabelled with the new component name.
run_v scripts --tree "$A"                       # produces a good artifact
[ -f "$ART" ] || bad "precondition: no artifact to go stale"
OUT=$(FIXTURE_NO_ARTIFACT=1 bash "$VERIFY" server --tree "$A" 2>&1); rc=$?
[ ! -f "$ART" ] && ok "a run without its own artifact removes the stale one" \
  || bad "stale artifact survived: $(python3 -c "import json;print(json.load(open('$ART'))['component'])" 2>/dev/null)"

# The wrapper must not stamp a component name onto an older run's record when
# run.sh refuses before writing anything. Only the REAL run.sh validates keys, so
# this case uses it — with AH_OUT_DIR redirected, so the checkout stays untouched.
REAL_OUT="$WORK/real-out"; mkdir -p "$REAL_OUT"
printf '{"component": "from-an-older-run"}\n' > "$REAL_OUT/last-verify.json"
printf '{\n  "layer": "quick",\n  "test_skips": []\n}\n' > "$REAL_OUT/last-quick.json"
OUT=$(AH_OUT_DIR="$REAL_OUT" bash "$VERIFY" nixkomponente 2>&1); rc=$?
[ $rc -eq 2 ] && [ ! -f "$REAL_OUT/last-verify.json" ] \
  && ok "a refused run leaves no artifact, not an older one" \
  || bad "refused run: rc=$rc, artifact: $(cat "$REAL_OUT/last-verify.json" 2>/dev/null)"

# A truncated source (an aborted run, a full disk) must be refused, not patched
# into invalid JSON. The FIXTURE writes the broken file — laying it down here
# beforehand would prove nothing, since verify.sh removes it before the run.
OUT=$(FIXTURE_TRUNCATE=1 bash "$VERIFY" scripts --tree "$A" 2>&1)
[ ! -f "$ART" ] && grep -q "no complete run artifact" <<<"$OUT" \
  && ok "a truncated source is refused, not patched" || bad "truncated source: $OUT"

# Control characters in the args must not break the artifact either.
run_v scripts --tree "$A" -- "$(printf 'tests/x.py\t-k\tfoo')"
python3 -c "import json;json.load(open('$ART'))" 2>/dev/null \
  && ok "a tab in the args keeps the artifact valid JSON" || bad "invalid JSON from a tab in args"

# A run that never produced an artifact must not fabricate one.
rm -f "$A/.crabbox-out/last-quick.json" "$ART"
cat > "$A/scripts/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 2
EOF
chmod +x "$A/scripts/tests/run.sh"
OUT=$(bash "$VERIFY" scripts --tree "$A" 2>&1); rc=$?
[ ! -f "$ART" ] && grep -q "not written" <<<"$OUT" \
  && ok "no run artifact -> no invented last-verify.json" || bad "artifact invented: rc=$rc out=$OUT"

echo ""
echo "verify_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
