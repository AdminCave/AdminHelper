#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# nightly_test.sh — does nightly.sh skip a night for the right reason, start the
# right mode, and keep exactly one crontab line of its own? Hermetic: its own git
# repo with an origin, fakes for tmux, crontab and vm.py; nothing real is
# started, nothing in the developer's crontab is touched.
#
# Run: bash scripts/tests/nightly_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
NIGHTLY="$REPO_ROOT/scripts/tests/nightly.sh"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── fakes ────────────────────────────────────────────────────────────────────
FAKE="$WORK/bin"; mkdir -p "$FAKE"
cat >"$FAKE/tmux" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  list-sessions) [ -n "${FAKE_TMUX_SESSIONS:-}" ] || exit 1; printf '%s\n' $FAKE_TMUX_SESSIONS ;;
  new-session)   shift; printf '%s\n' "$*" >>"$FAKE_TMUX_LOG" ;;
  *)             exit 1 ;;
esac
EOF
cat >"$FAKE/crontab" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  -l) [ -z "${FAKE_CRONTAB_FAIL:-}" ] || { echo "crontab: cannot open your crontab: Permission denied" >&2; exit 1; }
      [ -f "$FAKE_CRONTAB" ] || { echo "no crontab for user" >&2; exit 1; }; cat "$FAKE_CRONTAB" ;;
  -)  cat >"$FAKE_CRONTAB" ;;
  *)  exit 2 ;;
esac
EOF
cat >"$WORK/vmpy.sh" <<'EOF'
#!/usr/bin/env bash
echo "vmid 101 lane x addr 192.0.2.7"
exit "${FAKE_VM_RC:-0}"
EOF
chmod +x "$FAKE/tmux" "$FAKE/crontab" "$WORK/vmpy.sh"

# ── a checkout with an origin that is one commit ahead ──────────────────────
g() { git -C "$1" -c user.name=t -c user.email=t@example.invalid "${@:2}"; }
git init -q --bare -b main "$WORK/origin.git"
git clone -q "$WORK/origin.git" "$WORK/seed" 2>/dev/null
mkdir -p "$WORK/seed/tasks"; : >"$WORK/seed/tasks/.keep"
printf 'one\n' >"$WORK/seed/f"; g "$WORK/seed" add f tasks/.keep; g "$WORK/seed" commit -qm one; g "$WORK/seed" push -q origin main
git clone -q "$WORK/origin.git" "$WORK/repo"
printf 'two\n' >"$WORK/seed/f"; g "$WORK/seed" commit -qam two; g "$WORK/seed" push -q origin main
AHEAD="$(git -C "$WORK/seed" rev-parse HEAD)"

export FAKE_TMUX_LOG="$WORK/tmux.log" FAKE_CRONTAB="$WORK/crontab"
export AH_NIGHTLY_ROOT="$WORK/repo" AH_OUT_DIR="$WORK/out"
export AH_NIGHTLY_HEAVY="bash heavy-fake.sh" AH_NIGHTLY_VMPY="bash $WORK/vmpy.sh"
unset FAKE_TMUX_SESSIONS FAKE_VM_RC FAKE_CRONTAB_FAIL
# HOME too: nightly.sh appends ~/.local/bin to PATH, and a crontab or tmux there
# must never be the one this test drives.
mkdir -p "$WORK/home/.local/bin"
n() { OUT=$(HOME="$WORK/home" PATH="$FAKE:$PATH" bash "$NIGHTLY" "$@" 2>&1); rc=$?; }
lastlog() { tail -n 1 "$WORK/out/nightly.log" 2>/dev/null; }
starts() { [ -f "$FAKE_TMUX_LOG" ] && wc -l <"$FAKE_TMUX_LOG" || echo 0; }

echo "── usage ──"
n; [ $rc -eq 2 ] && ok "no verb -> 2" || bad "bare: rc=$rc"
n frobnicate; [ $rc -eq 2 ] && ok "unknown verb -> 2" || bad "unknown: rc=$rc"
n install --dry-run; [ $rc -eq 2 ] && ok "--dry-run only with run" || bad "install --dry-run: rc=$rc"

echo "── pre-flight skips ──"
git -C "$WORK/repo" checkout -q -b other
AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: checkout is on other, not main' <<<"$(lastlog)" && ok "not on main -> skip, logged" || bad "branch: rc=$rc $(lastlog)"
git -C "$WORK/repo" checkout -q main

touch "$WORK/repo/stray"
AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: checkout not clean' <<<"$(lastlog)" && ok "untracked file -> skip" || bad "dirty: rc=$rc $(lastlog)"
rm "$WORK/repo/stray"
touch "$WORK/repo/tasks/notes.md"
AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: checkout not clean' <<<"$(lastlog)" && ok "another untracked file under tasks/ -> skip" || bad "tasks dirty: rc=$rc $(lastlog)"
rm "$WORK/repo/tasks/notes.md"

FAKE_TMUX_SESSIONS="work ah-all" AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: tmux session ah-all is running' <<<"$(lastlog)" && ok "a running ah-* session -> skip" || bad "tmux: rc=$rc $(lastlog)"

echo "── heavy.sh's REG draft ──"
touch "$WORK/repo/tasks/reg-2026-11-12-server_pytest.md"
AH_NIGHTLY_TODAY=3 n run --dry-run
[ $rc -eq 0 ] && ok "an untracked REG draft of heavy.sh does not stop the night" || bad "reg draft: rc=$rc $OUT"
rm "$WORK/repo/tasks/reg-2026-11-12-server_pytest.md"

echo "── dry run ──"
before="$(wc -l <"$WORK/out/nightly.log")"
# Before the first night that gets past the tmux check: every skip so far came
# ahead of the fetch, so HEAD still trails origin/main here.
AH_NIGHTLY_TODAY=3 n run --dry-run
[ $rc -eq 0 ] && grep -q "would start 'bash heavy-fake.sh all'" <<<"$OUT" && ok "dry run: pre-flight ok, names the run" || bad "dry: rc=$rc $OUT"
[ "$(git -C "$WORK/repo" rev-parse HEAD)" != "$AHEAD" ] && ok "dry run fetched and merged nothing" || bad "dry run moved HEAD"
[ "$(starts)" = 0 ] && [ "$(wc -l <"$WORK/out/nightly.log")" = "$before" ] && ok "dry run started nothing, logged nothing" || bad "dry run side effects"

echo "── pre-flight skips, after the fetch ──"
FAKE_VM_RC=74 AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: vm.py list exited 74' <<<"$(lastlog)" && ok "vm.py list 74 -> skip" || bad "vm: rc=$rc $(lastlog)"
grep -q '192.0.2.7' "$WORK/out/nightly.log" && bad "the vm listing leaked into the log" || ok "the vm listing stays out of the log"
grep -q '192.0.2.7' "$WORK/out/nightly-vmlist.out" && ok "the vm listing is kept in nightly-vmlist.out" || bad "listing not kept"
[ "$(starts)" = 0 ] && ok "no skipped night started anything" || bad "started on a skip: $(cat "$FAKE_TMUX_LOG")"

echo "── start ──"
AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 0 ] && ok "a clean night starts (rc 0)" || bad "start: rc=$rc $OUT"
[ "$(git -C "$WORK/repo" rev-parse HEAD)" = "$AHEAD" ] && ok "main fast-forwarded to origin/main first" || bad "HEAD not at origin/main"
grep -q -- "-s ah-nightly -c $WORK/repo bash heavy-fake.sh all" "$FAKE_TMUX_LOG" && ok "weekday 3: heavy all in tmux ah-nightly" || bad "tmux: $(cat "$FAKE_TMUX_LOG")"
grep -q ' all start (HEAD ' <<<"$(lastlog)" && ok "the start is logged with its commit" || bad "log: $(lastlog)"
AH_NIGHTLY_TODAY=6 n run
grep -q 'bash heavy-fake.sh weekly' <<<"$(tail -n 1 "$FAKE_TMUX_LOG")" && ok "weekday 6: weekly" || bad "weekly: $(tail -n 1 "$FAKE_TMUX_LOG")"
AH_NIGHTLY_TODAY=2 AH_NIGHTLY_WEEKLY_DAY=2 n run
grep -q 'bash heavy-fake.sh weekly' <<<"$(tail -n 1 "$FAKE_TMUX_LOG")" && ok "the weekly day is configurable" || bad "weekly day: $(tail -n 1 "$FAKE_TMUX_LOG")"

echo "── fetch and fast-forward ──"
printf 'three\n' >"$WORK/seed/f"; g "$WORK/seed" commit -qam three; g "$WORK/seed" push -q origin main
before_head="$(git -C "$WORK/repo" rev-parse HEAD)"; before_starts="$(starts)"
git -C "$WORK/repo" remote set-url origin "$WORK/no-such-origin.git"
AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: git fetch origin failed' <<<"$(lastlog)" && ok "fetch fails -> skip, logged" || bad "fetch: rc=$rc $(lastlog)"
git -C "$WORK/repo" remote set-url origin "$WORK/origin.git"
printf 'local\n' >"$WORK/repo/g"; g "$WORK/repo" add g; g "$WORK/repo" commit -qm local
local_head="$(git -C "$WORK/repo" rev-parse HEAD)"
AH_NIGHTLY_TODAY=3 n run
[ $rc -eq 1 ] && grep -q 'skip: main does not fast-forward to origin/main' <<<"$(lastlog)" && ok "diverged main -> skip, logged" || bad "non-ff: rc=$rc $(lastlog)"
[ "$(git -C "$WORK/repo" rev-parse HEAD)" = "$local_head" ] && ok "a diverged main is left as it is" || bad "HEAD moved on a diverged main"
[ "$(starts)" = "$before_starts" ] && [ "$before_head" != "$local_head" ] && ok "neither failure started anything" || bad "started on a fetch failure"

echo "── crontab ──"
printf '0 5 * * * echo mine\n' >"$FAKE_CRONTAB"
n install; n install
[ $rc -eq 0 ] && [ "$(grep -c 'ah-nightly (scripts/tests/nightly.sh)' "$FAKE_CRONTAB")" = 1 ] && ok "install twice -> one marked line" || bad "install: $(cat "$FAKE_CRONTAB")"
grep -q '^0 5 \* \* \* echo mine$' "$FAKE_CRONTAB" && ok "a foreign line stays" || bad "foreign line lost"
grep -q "^30 1 \* \* \* cd $WORK/repo && AH_OUT_DIR=$WORK/out bash scripts/tests/nightly.sh run >>$WORK/out/nightly-cron.out" "$FAKE_CRONTAB" \
  && ok "01:30 nightly, from the checkout, the same output root for the run and its redirect" || bad "line: $(cat "$FAKE_CRONTAB")"
n status; grep -q '^installed: 30 1' <<<"$OUT" && grep -q 'last runs:' <<<"$OUT" && ok "status shows the line and the log" || bad "status: $OUT"
n uninstall
[ $rc -eq 0 ] && [ "$(cat "$FAKE_CRONTAB")" = '0 5 * * * echo mine' ] && ok "uninstall removes exactly its line" || bad "uninstall: $(cat "$FAKE_CRONTAB")"
printf '0 5 * * * echo mine\n\n# a comment\n' >"$FAKE_CRONTAB"; n install; n uninstall
[ "$(cat "$FAKE_CRONTAB")" = "$(printf '0 5 * * * echo mine\n\n# a comment')" ] && ok "blank lines and comments of the user stay" || bad "blank lines: $(cat -A "$FAKE_CRONTAB")"
cp "$FAKE_CRONTAB" "$WORK/crontab.before"
FAKE_CRONTAB_FAIL=1 n install
[ $rc -eq 2 ] && cmp -s "$FAKE_CRONTAB" "$WORK/crontab.before" && ok "an unreadable crontab: exit 2, nothing written" || bad "read error: rc=$rc $(cat "$FAKE_CRONTAB")"
FAKE_CRONTAB_FAIL=1 n uninstall
[ $rc -eq 2 ] && cmp -s "$FAKE_CRONTAB" "$WORK/crontab.before" && ok "uninstall on an unreadable crontab writes nothing either" || bad "uninstall read error: rc=$rc"
AH_OUT_DIR="$WORK/o%t" n install
[ $rc -eq 2 ] && cmp -s "$FAKE_CRONTAB" "$WORK/crontab.before" && ok "a % in a path is refused, nothing written" || bad "percent: rc=$rc $(cat "$FAKE_CRONTAB")"
rm -f "$FAKE_CRONTAB"; n install; n uninstall
[ $rc -eq 0 ] && [ ! -s "$FAKE_CRONTAB" ] && ok "install/uninstall on an empty crontab" || bad "empty: rc=$rc $(cat "$FAKE_CRONTAB" 2>/dev/null)"

echo "── registration ──"
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'nightly_test' <<<"$LIST" && ok "nightly_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo "nightly_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
