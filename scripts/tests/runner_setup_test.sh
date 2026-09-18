#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# runner_setup_test.sh — hermetic test for scripts/dev/runner-setup.sh.
#
# That script creates a unix user, a database and a clone under /srv — so the
# only thing a test may ever run is `--dry-run`, and the thing it has to prove is
# that --dry-run really CHANGES NOTHING. Every command it could call (useradd,
# userdel, su, psql, install, chown, git, rm) is shadowed by a shim on PATH that
# records its call; after the dry run, not one of them may have been touched.
#
# Run: bash scripts/tests/runner_setup_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
SETUP="$REPO_ROOT/scripts/dev/runner-setup.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SHIM="$WORK/shim"; mkdir -p "$SHIM"
CALLED="$WORK/called.txt"; : > "$CALLED"
for cmd in useradd userdel su psql createdb install chown chmod rm ln mkdir; do
  cat > "$SHIM/$cmd" <<EOF
#!/usr/bin/env bash
echo "$cmd \$*" >> "$CALLED"
exit 0
EOF
  chmod +x "$SHIM/$cmd"
done
# git is shimmed too, but the one read-only call the plan legitimately makes
# (reading the origin URL) passes through — everything else is recorded.
cat > "$SHIM/git" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"config --get"*) exec $(command -v git) "\$@" ;;
esac
echo "git \$*" >> "$CALLED"
exit 0
EOF
chmod +x "$SHIM/git"

dry() { OUT=$(PATH="$SHIM:$PATH" bash "$SETUP" --dry-run "$@" 2>&1); rc=$?; }
# The fingerprint of everything the script would touch outside this test.
system_state() {
  {
    getent passwd adminhelper-runner 2>/dev/null
    stat -c '%n %Y %a' /srv/ah /srv/ah/repo /srv/ah/lanes 2>/dev/null
    stat -c '%n %Y %a' /home/adminhelper-runner/.devenv.sh 2>/dev/null
    stat -c '%n %Y %a' /home/adminhelper-runner/.config/adminhelper/oauth.env 2>/dev/null
  } 2>/dev/null
}
STATE_BEFORE="$(system_state)"

# ══ the plan ══════════════════════════════════════════════════════════════════
echo "── --dry-run prints the plan ──"
dry
[ $rc -eq 0 ] && ok "--dry-run exits 0 without root" || bad "rc=$rc out=$OUT"

# Every step the ledger asks for, in the order the script performs it.
for want in 'preflight: what this box has to provide' \
            'useradd -m -s /bin/bash adminhelper-runner' \
            'git clone --no-hardlinks -b main' \
            'remote.origin.pushurl /dev/null' \
            '/srv/ah/lanes' \
            'chown -R adminhelper-runner:adminhelper-runner /srv/ah' \
            'CREATE ROLE ah_runner LOGIN CREATEDB' \
            'createdb -O ah_runner ah_runner_test' \
            '/home/adminhelper-runner/.devenv.sh' \
            'AH_TEST_DB="postgresql://ah_runner:' \
            'AH_REQUIRED=' \
            '.local/share/ah-tools/venv' \
            'pip install --quiet ruff pytest pytest-cov pytest-httpx' \
            '.local/bin' \
            'scripts/dev/runner-settings.json /home/adminhelper-runner/.claude/settings.json' \
            '.config/adminhelper/oauth.env' \
            '.config/adminhelper/pve.env'; do
  grep -qF -- "$want" <<<"$OUT" && ok "plans: $want" || bad "missing from the plan: $want"
done

# The runner's own venv path: run.sh's default (/tmp/ah-venv) belongs to whoever
# created it first, and pip then fails for this user in exactly the three suites
# its AH_REQUIRED declares mandatory.
grep -q 'AH_VENV=' <<<"$OUT" && ok "plans: its own AH_VENV, not the shared /tmp one" \
  || bad "the devenv does not set AH_VENV"
# install -d applies owner and mode to a symlink's TARGET — a refusal, not a chown.
grep -q 'refusing to chown its target' "$SETUP" \
  && ok "a directory that is a symlink stops the script (no chown of its target)" \
  || bad "install -d would follow a symlink"

# The three things this user must not have.
grep -q 'no ssh key, no gh, not in a sudo group' <<<"$OUT" \
  && ok "it checks for ssh key, gh and sudo group" || bad "no negative check in the plan"
# And the three handovers Kevin has to do himself.
for want in 'claude setup-token' 'pveum user token add' 'runner-redteam.sh'; do
  grep -qF -- "$want" <<<"$OUT" && ok "hands over: $want" || bad "missing handover: $want"
done

# ══ a dry run changes nothing ═════════════════════════════════════════════════
echo "── --dry-run touches nothing ──"
[ ! -s "$CALLED" ] && ok "not one of useradd/userdel/su/psql/install/chown/rm/ln/git/mkdir was called" \
  || bad "the dry run executed: $(cat "$CALLED")"
# "unchanged", not "absent": on Kevin's box — and inside the runner's own clone,
# where this suite also runs — the user and /srv/ah exist by design.
[ "$STATE_BEFORE" = "$(system_state)" ] \
  && ok "user, home and /srv/ah are exactly as before the dry run" \
  || bad "the dry run changed the system: $STATE_BEFORE -> $(system_state)"

# A password must never appear in a plan that gets pasted into a terminal or a PR.
grep -q '<redacted>' <<<"$OUT" \
  && ok "the database password is redacted in the plan" || bad "the plan does not redact the password"
grep -qE 'PASSWORD .[A-Za-z0-9_-]{20,}' <<<"$OUT" && bad "a real password is printed in the plan" \
  || ok "and no real secret is printed"
# A dry run can only ever show the placeholder, so the real protection is checked
# in the source: no SQL and no file content may travel in argv, where `ps` reads
# it, and every print of them goes through the redaction.
grep -qE 'psql +-c|psql +-tAc.*PASSWORD' "$SETUP" && bad "SQL with a secret is passed in argv (visible in ps)" \
  || ok "all SQL travels on stdin, not in argv"
grep -q '\${2//\$DB_PW/<redacted>}' "$SETUP" && grep -q '\${DEVENV_CONTENT//\$DB_PW/<redacted>}' "$SETUP" \
  && ok "the printed plan redacts the password in both places that carry it" \
  || bad "a password would be printed unredacted"

# ══ a second run keeps what Kevin put there ═══════════════════════════════════
echo "── idempotence ──"
grep -q 'already has content — left alone' "$SETUP" \
  && ok "a filled oauth.env/pve.env is left alone on a second run" || bad "a second run would truncate the token files"
grep -q 'ALTER ROLE' "$SETUP" \
  && ok "an existing database role gets the new password instead of keeping the old one" \
  || bad "a second run would leave role and devenv out of sync"
dry
if id adminhelper-runner >/dev/null 2>&1; then
  grep -q 'exists — useradd would be skipped' <<<"$OUT" \
    && ok "the plan says which steps would be skipped" || bad "the plan does not mark existing state"
else
  ok "(no runner user on this box — the skip note cannot be exercised here)"
fi

# ══ --remove ══════════════════════════════════════════════════════════════════
echo "── --remove ──"
dry --remove
[ $rc -eq 0 ] && grep -q 'userdel -r adminhelper-runner' <<<"$OUT" \
  && ok "--remove plans userdel, DROP DATABASE and DROP ROLE" || bad "remove plan: rc=$rc"
grep -q 'DROP DATABASE IF EXISTS ah_runner_test' <<<"$OUT" && ok "  DROP DATABASE" || bad "no DROP DATABASE"
grep -q 'DROP ROLE IF EXISTS ah_runner' <<<"$OUT" && ok "  DROP ROLE" || bad "no DROP ROLE"
[ ! -s "$CALLED" ] && ok "and still nothing was executed" || bad "remove dry run executed: $(cat "$CALLED")"

# ══ the guards ════════════════════════════════════════════════════════════════
echo "── the guards ──"
OUT=$(PATH="$SHIM:$PATH" bash "$SETUP" 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "needs root" <<<"$OUT" \
  && ok "without root and without --dry-run it refuses (exit 2)" || bad "root check: rc=$rc out=$OUT"
OUT=$(PATH="$SHIM:$PATH" bash "$SETUP" --remove 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "needs root" <<<"$OUT" \
  && ok "--remove as a normal user hits the root check first" || bad "remove as user: rc=$rc out=$OUT"
# The --yes guard only comes after the root check, so it needs an `id` that
# claims uid 0 — everything it would then do is shimmed anyway.
cat > "$SHIM/id" <<EOF
#!/usr/bin/env bash
[ "\$1" = "-u" ] && { echo 0; exit 0; }
exec $(command -v id) "\$@"
EOF
chmod +x "$SHIM/id"
OUT=$(PATH="$SHIM:$PATH" bash "$SETUP" --remove 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q '\-\-yes' <<<"$OUT" \
  && ok "--remove without --yes refuses even as root (it deletes a home)" || bad "yes guard: rc=$rc out=$OUT"
rm -f "$SHIM/id"
OUT=$(PATH="$SHIM:$PATH" bash "$SETUP" --wat 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "unknown argument" <<<"$OUT" && ok "an unknown argument -> exit 2" || bad "unknown arg: rc=$rc"
[ ! -s "$CALLED" ] && ok "none of the refusals executed anything either" || bad "executed: $(cat "$CALLED")"

# ══ what it installs ══════════════════════════════════════════════════════════
echo "── the settings it installs ──"
[ -f "$REPO_ROOT/scripts/dev/runner-settings.json" ] \
  && ok "the settings file it copies exists in the repo" || bad "scripts/dev/runner-settings.json is missing"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'runner_setup_test' \
  && ok "runner_setup_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "runner_setup_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
