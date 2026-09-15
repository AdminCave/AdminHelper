#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# openapi_breaking_test.sh — hermetic test for scripts/dev/openapi-breaking.sh.
#
# A fixture git repo under --root and a fake `oasdiff` in front of PATH: no
# network, no Go toolchain, bash + git + coreutils. The gate's whole value is its
# exit code, so every case asserts that code AND the wording that explains it;
# the fake records its invocation so a case can prove WHICH files were compared —
# "it exited 0" would hold just as well if the script had diffed a file against
# itself.
#
# Run: bash scripts/tests/openapi_breaking_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CHECK="$HERE/../dev/openapi-breaking.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "git not installed — skipping (75)"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A fake oasdiff that answers from the environment instead of doing real work:
#   FAKE_RC  the exit code it reports   FAKE_LOG  where it records its arguments
FAKE="$WORK/fakebin"; mkdir -p "$FAKE"
cat > "$FAKE/oasdiff" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
# Record the CONTENT of the first operand too. Asserting only on the argument
# list would still pass if the script diffed the working tree against itself —
# the exact mistake this test is supposed to rule out.
printf 'base-operand: %s\n' "$(tr -d '\n' < "$2" 2>/dev/null)" >> "$FAKE_LOG"
[ "${FAKE_RC:-0}" = 0 ] || { echo "fake: breaking changes found"; exit "$FAKE_RC"; }
echo "fake: no breaking changes"
EOF
chmod +x "$FAKE/oasdiff"
FAKE_LOG="$WORK/oasdiff.log"; : > "$FAKE_LOG"; export FAKE_LOG

REL="apps/server/tests/openapi.snapshot.json"
SNAP_BASE='{"openapi":"3.1.0","paths":{"/a":{}}}'
SNAP_HEAD='{"openapi":"3.1.0","paths":{"/a":{},"/b":{}}}'

# fixture <dir> <base-has-snapshot: yes|no>
# A git repo whose HEAD may or may not carry the snapshot, with a differing one
# in the working tree — the shape every real invocation sees.
fixture() {
  local d="$1" commit="$2"
  mkdir -p "$d/apps/server/tests"
  git -C "$d" init -q
  git -C "$d" config user.email t@example.com
  git -C "$d" config user.name Test
  if [ "$commit" = yes ]; then printf '%s\n' "$SNAP_BASE" > "$d/$REL"
  else printf 'placeholder\n' > "$d/README"; fi
  git -C "$d" add -A
  git -C "$d" commit -qm base
  printf '%s\n' "$SNAP_HEAD" > "$d/$REL"
}

# run_case <name> <expect-rc> <expect-substring> -- <args...>
# FAKE_RC and PATH come from the caller's environment.
run_case() {
  local name="$1" want_rc="$2" want="$3"; shift 3; [ "$1" = "--" ] && shift
  local out rc=0
  out=$(bash "$CHECK" "$@" 2>&1) || rc=$?
  if [ "$rc" != "$want_rc" ]; then
    bad "$name: rc=$rc (expected $want_rc)"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  if [ -n "$want" ] && ! printf '%s' "$out" | grep -qF -- "$want"; then
    bad "$name: output does not mention '$want'"; printf '%s\n' "$out" | sed 's/^/       /'; return
  fi
  ok "$name"
}

export PATH="$FAKE:$PATH"

# ── oasdiff reports a breaking change -> the gate is red and says so ─────────
REPO="$WORK/r1"; fixture "$REPO" yes
FAKE_RC=1 run_case "breaking oasdiff -> exit 1" 1 "::error::" -- server --base HEAD --root "$REPO"

# The comparison must be base-ref against working tree, not tree against tree.
LAST=$(grep -v '^base-operand:' "$FAKE_LOG" | tail -1)
case "$LAST" in
  *"--fail-on ERR"*"--format text"*) ok "oasdiff called with --fail-on ERR --format text" ;;
  *) bad "unexpected oasdiff arguments: $LAST" ;;
esac
case "$LAST" in
  "breaking "*" $REL "*|"breaking "*" $REL") ok "second operand is the working-tree snapshot" ;;
  *) bad "working-tree snapshot is not the second operand: $LAST" ;;
esac
# And the FIRST operand really carries the base ref's content, not the working
# tree's. Without this the case above passes for `oasdiff breaking $REL $REL`.
if grep -qF "base-operand: $SNAP_BASE" "$FAKE_LOG"; then
  ok "first operand carries the base ref's snapshot"
else
  bad "first operand is not the base ref's snapshot: $(grep '^base-operand:' "$FAKE_LOG" | tail -1)"
fi

# ── oasdiff is happy -> green ────────────────────────────────────────────────
REPO="$WORK/r2"; fixture "$REPO" yes
FAKE_RC=0 run_case "compatible oasdiff -> exit 0" 0 "no breaking changes" -- server --base HEAD --root "$REPO"

# ── no oasdiff on PATH -> 75, never a silent pass ────────────────────────────
REPO="$WORK/r3"; fixture "$REPO" yes
EMPTY="$WORK/emptybin"; mkdir -p "$EMPTY"
OLD_PATH="$PATH"; PATH="$EMPTY:/usr/bin:/bin"
run_case "missing oasdiff -> exit 75 (SKIP)" 75 "not installed" -- server --base HEAD --root "$REPO"
PATH="$OLD_PATH"

# ── base ref carries no snapshot yet -> there is no contract to break ────────
REPO="$WORK/r4"; fixture "$REPO" no
FAKE_RC=1 run_case "absent base snapshot -> exit 0" 0 "nothing to compare" -- server --base HEAD --root "$REPO"

# ── a base snapshot that is not an OpenAPI document is a setup error ─────────
# oasdiff answers "no breaking changes" and exits 0 for an unparsable base, even
# when the revision removed a path — the gate would go green on a broken baseline.
REPO="$WORK/r4b"; fixture "$REPO" yes
git -C "$REPO" rm -q --cached "$REL" >/dev/null
printf 'not json at all\n' > "$REPO/$REL"
git -C "$REPO" add "$REL" && git -C "$REPO" commit -qm garbage
printf '%s\n' "$SNAP_HEAD" > "$REPO/$REL"
FAKE_RC=0 run_case "unparsable base snapshot -> exit 2" 2 "not an OpenAPI document" -- server --base HEAD --root "$REPO"

# ── usage errors ─────────────────────────────────────────────────────────────
REPO="$WORK/r5"; fixture "$REPO" yes
run_case "missing component -> exit 2" 2 "needs a component" -- --root "$REPO"
run_case "unknown component -> exit 2" 2 "unknown component" -- gateway --root "$REPO"
run_case "--base without a ref -> exit 2" 2 "needs a ref" -- server --root "$REPO" --base

# A base ref that is not in the checkout must NOT read as "nothing to compare":
# a shallow CI clone would otherwise turn the gate green on every PR.
REPO="$WORK/r7"; fixture "$REPO" yes
run_case "unresolvable base ref -> exit 2" 2 "does not resolve" -- server --base origin/nope --root "$REPO"

# A working tree without a snapshot is a setup error, not a skip: exiting 75 here
# would let a deleted snapshot pass the gate as "not verified" rather than red.
REPO="$WORK/r6"; fixture "$REPO" yes; rm -f "$REPO/$REL"
run_case "missing working-tree snapshot -> exit 2" 2 "--update-openapi-snapshot" -- server --base HEAD --root "$REPO"

echo "openapi_breaking_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
