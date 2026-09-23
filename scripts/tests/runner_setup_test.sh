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

# ── the two steps that depend on what this box already has ──────────────────
# `useradd` and `git clone` drop out of the plan the moment the user and the clone
# exist — and on a box that has been provisioned they do. Asserting them against
# the real names made this test report 49/2 for the rest of that machine's life
# (found 2026-09-22, one day after the runner was created), and a permanently red
# test hides the next real regression. --dry-run therefore accepts a different
# name and a different target, and both branches are checked here.
echo "── the plan follows what exists, in both directions ──"
ABSENT="ah-runner-probe-$$"
FRESH="$WORK/srv-fresh"
PLAN=$(PATH="$SHIM:$PATH" AH_RUNNER_DRY_USER="$ABSENT" AH_RUNNER_DRY_SRV="$FRESH" bash "$SETUP" --dry-run 2>&1)
grep -qF -- "useradd -m -s /bin/bash $ABSENT" <<<"$PLAN" \
  && ok "absent user: the plan creates it" || bad "absent user: no useradd in the plan"
grep -qF -- 'git clone --no-hardlinks -b main' <<<"$PLAN" \
  && ok "empty target: the plan clones into it" || bad "empty target: no git clone in the plan"

PRESENT="$WORK/srv-present"; mkdir -p "$PRESENT/repo/.git"
PLAN=$(PATH="$SHIM:$PATH" AH_RUNNER_DRY_USER="$(id -un)" AH_RUNNER_DRY_SRV="$PRESENT" bash "$SETUP" --dry-run 2>&1)
grep -q 'exists — useradd would be skipped' <<<"$PLAN" \
  && ok "existing user: the plan says useradd is skipped" || bad "existing user: the plan is silent about skipping useradd"
grep -q 'exists — git clone would be skipped' <<<"$PLAN" \
  && ok "existing clone: the plan says the clone is skipped" || bad "existing clone: the plan is silent about skipping it"
grep -qF -- 'useradd -m -s /bin/bash' <<<"$PLAN" \
  && bad "existing user: useradd is still in the plan" || ok "existing user: useradd appears nowhere in the plan"

# The overrides are a test hook and must stay one: outside --dry-run they have to
# be ignored, or a stray variable in somebody's shell could provision the wrong
# user. A behaviour test cannot show this — between argument parsing and the root
# check the script prints nothing, so "the name does not appear" is true with the
# guard and without it. So check the anchoring in the source, the way the
# no_symlink_in assertion below does, and keep the behaviour check as a second line.
awk '/^if \[ "\$DRY" = 1 \]; then/{f=1} f{print} f&&/^fi$/{exit}' "$SETUP" | grep -q 'AH_RUNNER_DRY_USER' \
  && ok "the overrides sit inside the --dry-run guard" || bad "AH_RUNNER_DRY_USER is not guarded by DRY=1"
awk '/^if \[ "\$DRY" = 1 \]; then/{f=1} f{print} f&&/^fi$/{exit}' "$SETUP" | grep -q 'AH_RUNNER_DRY_SRV' \
  && ok "the SRV override sits inside the same guard" || bad "AH_RUNNER_DRY_SRV is not guarded by DRY=1"
PLAN=$(PATH="$SHIM:$PATH" AH_RUNNER_DRY_USER=nobody-at-all bash "$SETUP" 2>&1); prc=$?
[ $prc -eq 2 ] && ! grep -q 'nobody-at-all' <<<"$PLAN" \
  && ok "a real run without --dry-run still demands root and names no override" \
  || bad "a real run reacted to the override: rc=$prc out=$PLAN"

# The runner's own venv path: run.sh's default (/tmp/ah-venv) belongs to whoever
# created it first, and pip then fails for this user in exactly the three suites
# its AH_REQUIRED declares mandatory.
grep -q 'AH_VENV=' <<<"$OUT" && ok "plans: its own AH_VENV, not the shared /tmp one" \
  || bad "the devenv does not set AH_VENV"
# install -d applies owner and mode to a symlink's TARGET — and it follows a
# symlinked PARENT just as happily, existing directories included. Checked for
# real against the function itself, not by grepping for a message.
SYM=$(mktemp -d); mkdir -p "$SYM/real/deep"; ln -s "$SYM/real" "$SYM/link"
probe_no_symlink() {  # probe_no_symlink <path> -> rc
  ( set +e   # review: ok the probe must survive a refusal, that is what it measures
    eval "$(sed -n '/^no_symlink_in()/,/^}/p' "$SETUP")"
    no_symlink_in "$1" >/dev/null 2>&1 )
}
probe_no_symlink "$SYM/real/deep/x" \
  && ok "a path of real directories passes" || bad "a real path was refused"
probe_no_symlink "$SYM/link/deep/x" \
  && bad "a symlinked PARENT was not caught" || ok "a symlinked parent component is refused"
probe_no_symlink "$SYM/link" \
  && bad "a symlinked leaf was not caught" || ok "a symlinked leaf is refused"
probe_no_symlink "relative/path" \
  && bad "a relative path was accepted" || ok "a relative path is refused"
# The everyday case: on the first run almost nothing exists yet. A check that
# stops there would block the setup it is supposed to protect.
probe_no_symlink "$SYM/real/does/not/exist/yet" \
  && ok "components that do not exist yet pass (the first run)" || bad "a fresh path was refused"
probe_no_symlink "$SYM/real/deep/with space/x" \
  && ok "a path with a space passes" || bad "a path with a space was refused"
rm -rf "$SYM"
# Both writers use it — a check only one of them runs is not a check. And the
# clone path too: the runner owns /srv/ah after the first run, so on every later
# run root would follow a symlink it put there.
grep -q 'no_symlink_in "\$1"' "$SETUP" && grep -q 'no_symlink_in "\$path"' "$SETUP" \
  && ok "safe_dir and write_file both refuse to write through a symlink" \
  || bad "one of the two writers skips the symlink check"
grep -q 'no_symlink_in "\$SRV/repo"' "$SETUP" \
  && ok "the clone path is checked too (the runner owns /srv/ah after the first run)" \
  || bad "git clone/config/chown run without the symlink check"

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
echo "── the trusted workspace is opt-in ──"
# Trust arms the runner's 38 allow rules. Provisioning must not do that as a side
# effect, so the default plan says what it did NOT do, and --trust is what asks.
PLAN=$(PATH="$SHIM:$PATH" bash "$SETUP" --dry-run 2>&1)
grep -q 'hasTrustDialogAccepted' <<<"$PLAN" \
  && bad "the default plan already trusts the workspace" || ok "the default plan does not trust the workspace"
grep -q 'run again with --trust' <<<"$PLAN" \
  && ok "the plan says how to ask for it" || bad "the plan does not say how to ask for trust"
PLAN=$(PATH="$SHIM:$PATH" bash "$SETUP" --dry-run --trust 2>&1)
grep -q 'hasTrustDialogAccepted' <<<"$PLAN" \
  && ok "--trust plans the flag in the runner's .claude.json" || bad "--trust does not plan the trust flag"

echo "── the CLI version is pinned from one file ──"
VFILE="$REPO_ROOT/scripts/dev/runner-claude.version"
PINNED="$(tr -d '[:space:]' < "$VFILE" 2>/dev/null)"
if [[ "$PINNED" =~ ^[0123456789]+\.[0123456789]+\.[0123456789]+$ ]]; then
  ok "runner-claude.version holds a plain version ($PINNED)"
else
  bad "scripts/dev/runner-claude.version does not hold a plain version (got '$PINNED')"
fi
PLAN=$(PATH="$SHIM:$PATH" bash "$SETUP" --dry-run 2>&1)
grep -qF -- "claude install $PINNED" <<<"$PLAN" \
  && ok "the plan installs exactly the pinned version" \
  || bad "the plan does not install claude $PINNED"
# The version reaches a string root runs through su -c; anything but digits and dots
# must stop the script before that. Checked against a copy, never the real file.
BADTREE="$WORK/badver"; mkdir -p "$BADTREE/scripts/dev"
cp "$SETUP" "$BADTREE/scripts/dev/runner-setup.sh"
cp "$REPO_ROOT/scripts/dev/runner-settings.json" "$BADTREE/scripts/dev/" 2>/dev/null
printf '2.1.280; touch /tmp/pwned\n' > "$BADTREE/scripts/dev/runner-claude.version"
BPLAN=$(PATH="$SHIM:$PATH" bash "$BADTREE/scripts/dev/runner-setup.sh" --dry-run 2>&1); brc=$?
[ $brc -ne 0 ] && grep -q 'must hold a version' <<<"$BPLAN" && ! grep -q 'pwned' <<<"$(grep 'claude install' <<<"$BPLAN")" \
  && ok "a version with shell in it stops the script before su -c" \
  || bad "a malformed version reached the plan: rc=$brc"
# ...and before step 1: a stop halfway through would leave a half-provisioned user.
! grep -q 'no sudo group, no ssh key' <<<"$BPLAN" \
  && ok "the version is checked before anything is changed" \
  || bad "the version check runs after the user step"
# Exactly N.N.N — also no empty segments and no digits of another script (an
# Arabic-Indic three passes a [0-9] range under de_DE.UTF-8, not under C.UTF-8, so
# that locale is used where the box has it).
LOC="$(locale -a 2>/dev/null | grep -im1 '^de_DE\.utf-\?8$')"
LOOSE=""
for v in '...' '2.1' '2.1.280.1' '2..280' "2.1.2$(printf '\xd9\xa3')0"; do
  printf '%s\n' "$v" > "$BADTREE/scripts/dev/runner-claude.version"
  LC_ALL="${LOC:-C.UTF-8}" PATH="$SHIM:$PATH" bash "$BADTREE/scripts/dev/runner-setup.sh" --dry-run >/dev/null 2>&1 \
    && LOOSE="$LOOSE '$v'"
done
# The same tree and locale with a good version must pass, or the loop proves nothing.
printf '2.1.280\n' > "$BADTREE/scripts/dev/runner-claude.version"
LC_ALL="${LOC:-C.UTF-8}" PATH="$SHIM:$PATH" bash "$BADTREE/scripts/dev/runner-setup.sh" --dry-run >/dev/null 2>&1 \
  || LOOSE="$LOOSE (and a good version was refused too — the probe is broken)"
[ -z "$LOOSE" ] && ok "only N.N.N passes (empty segments, 2 or 4 parts, foreign digits refused)" \
  || bad "the version check let through:$LOOSE"

# The branch for a runner without any CLI is never reached under --dry-run; what it
# prints has to install exactly the pinned version.
grep -qF "install.sh | bash -s \$CLAUDE_VERSION" "$SETUP" \
  && ok "without a CLI the setup names the installer with the pinned version" \
  || bad "the missing-CLI hint does not install \$CLAUDE_VERSION"

grep -qE '^[[:space:]]*export DISABLE_AUTOUPDATER=1' "$REPO_ROOT/scripts/dev/runner-env.sh" \
  && ok "runner-env.sh switches the CLI updater off" || bad "runner-env.sh does not export DISABLE_AUTOUPDATER=1"

echo "── the settings it installs ──"
[ -f "$REPO_ROOT/scripts/dev/runner-settings.json" ] \
  && ok "the settings file it copies exists in the repo" || bad "scripts/dev/runner-settings.json is missing"
# What the runner works with is pinned, not inherited from a default: the "at least
# Opus" rule of CLAUDE.md §2 would otherwise rest on whatever the CLI ships with.
# Measured 2026-09-23: Opus 5.5 defaults to effort medium, and /effort stores the
# level per model under modelSettings — so both places are checked.
python3 - "$REPO_ROOT/scripts/dev/runner-settings.json" <<'PY' \
  && ok "the runner's model and effort are pinned, with no env block" \
  || bad "runner-settings.json does not pin model and effort (or carries an env block)"
import json, re, sys
d = json.load(open(sys.argv[1]))
model = d.get("model", "")
# An alias (opus, sonnet, opus[1m], ...) moves with every release; a pin is a full id.
is_alias = re.fullmatch(r"(opus|sonnet|haiku|fable|best|default)(\[1m\])?", model) is not None
base = re.sub(r"\[1m\]$", "", model)
ok = (model.startswith("claude-") and not is_alias
      and d.get("effortLevel") == "xhigh"
      and (d.get("modelSettings") or {}).get(base, {}).get("effortLevel") == "xhigh"
      and "env" not in d          # public file: rules only, never an env block
      and "permissions" in d and "hooks" in d)
sys.exit(0 if ok else 1)
PY
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'runner_setup_test' \
  && ok "runner_setup_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "runner_setup_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
