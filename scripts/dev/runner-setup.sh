#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# runner-setup.sh — provisions the unix user the autonomous runs work as.
#
#   sudo bash scripts/dev/runner-setup.sh [--dry-run] [--remove --yes]
#
#     --dry-run   print every step, execute nothing, need no root
#     --remove    take the user, its clone and its database away again
#     --yes       required for --remove: it deletes a home directory
#
# `sudo bash …`, not `su -` first: the clone comes out of Kevin's checkout, and
# git refuses a repository whose owner is somebody else ("dubious ownership") —
# under sudo it still sees SUDO_UID.
#
# Why a second user at all (autonomy stage 4): today every build runs with
# Kevin's rights — his ssh keys, his gh login, his session bus, his bypass
# permissions. As long as a human starts every run and reads every PR that
# holds; from stage 7 (workers in tmux, unattended) it does not. This user has
#
#   * no ssh key, no gh, no sudo group, no d-bus session
#   * a clone at /srv/ah/repo whose origin cannot be pushed to
#     (remote.origin.pushurl=/dev/null). That alone is not the boundary — a push
#     to an explicit URL would bypass it; what carries is that this user has no
#     credential anywhere and its settings deny `git push` outright.
#   * its own Postgres role and test database
#   * its own subscription token and its own Proxmox token, both 0600 and read
#     by scripts/dev/runner-env.sh
#   * ~/.claude/settings.json from scripts/dev/runner-settings.json: mode
#     dontAsk plus a deny list that keeps it out of git history, GitHub, sudo
#     and the harness
#
# The proof that all of this holds is scripts/dev/runner-redteam.sh, which Kevin
# runs AS that user afterwards.
#
# Idempotent in the way that matters: a second run never destroys state Kevin
# created. The two token files are written ONLY when they are still empty, and
# the database password is rotated together with the devenv file that carries it,
# never one without the other. The password never reaches the terminal or the
# process list: SQL and file contents travel on stdin, and what is printed is
# redacted.

set -uo pipefail

RUNNER="adminhelper-runner"
SRV="/srv/ah"
DB_ROLE="ah_runner"
DB_NAME="ah_runner_test"
VENV_PKGS="ruff pytest pytest-cov pytest-httpx"

DB_PW=""   # set in step 3; referenced by the redaction in as_pg_sql before that
DRY=0 REMOVE=0 YES=0 TRUST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --remove)  REMOVE=1 ;;
    --yes)     YES=1 ;;
    --trust)   TRUST=1 ;;
    -h|--help) sed -n '/^#   sudo bash/,/^# `sudo bash …`/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# Two names the TEST has to be able to move, honoured ONLY under --dry-run: the
# plan legitimately omits `useradd` once the user exists and `git clone` once the
# clone is there, so runner_setup_test cannot assert either against a box that has
# already been provisioned — from 2026-09-21 on it was red for exactly that reason
# (found 2026-09-22), and a permanently red test hides the next real regression.
# A real run ignores both variables, so they cannot misdirect a provisioning.
if [ "$DRY" = 1 ]; then
  RUNNER="${AH_RUNNER_DRY_USER:-$RUNNER}"
  SRV="${AH_RUNNER_DRY_SRV:-$SRV}"
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
# The real home if the user exists, the default before that.
HOME_DIR="$(getent passwd "$RUNNER" 2>/dev/null | cut -d: -f6)"
[ -n "$HOME_DIR" ] || HOME_DIR="/home/$RUNNER"

step() { printf '\n── %s\n' "$*"; }
note() { printf '   (%s)\n' "$*"; }
# Every change goes through run(): --dry-run prints the exact command instead of
# running it, so the plan a reviewer reads is the plan that executes.
run() {
  if [ "$DRY" = 1 ]; then printf '   $ %s\n' "$*"
  else printf '   $ %s\n' "$*"; "$@" || { echo "runner-setup: failed: $*" >&2; exit 1; }
  fi
}
# Same, for a command that needs a shell (redirection, a pipeline).
run_sh() {
  if [ "$DRY" = 1 ]; then printf '   $ %s\n' "$1"
  else printf '   $ %s\n' "$1"; bash -c "$1" || { echo "runner-setup: failed: $1" >&2; exit 1; }
  fi
}
# SQL on stdin, never in argv: an inline -c statement is readable in `ps` by
# every local user on the box, and one of these statements carries the database
# password.
as_pg_sql() {  # as_pg_sql <label> <sql>
  printf '   $ su - postgres -c "psql -q -v ON_ERROR_STOP=1 -v VERBOSITY=terse"   << %s\n' "$1"
  printf '%s\n' "${2//$DB_PW/<redacted>}" | sed 's/^/       | /'
  [ "$DRY" = 1 ] && return 0
  # terse: psql otherwise echoes the offending statement on an error — with the
  # password in it. A removal keeps going even when a drop fails, so a database
  # that refuses to go does not leave the user and the clone standing.
  printf '%s\n' "$2" | su - postgres -c "psql -q -v ON_ERROR_STOP=1 -v VERBOSITY=terse" \
    || { echo "runner-setup: failed: $1" >&2; [ "${REMOVE_TOLERANT:-0}" = 1 ] || exit 1; }
}
as_pg_query() {  # as_pg_query <sql> -> stdout (no secrets in these)
  su - postgres -c "psql -tAc $(printf '%q' "$1")" 2>/dev/null
}
# install -d follows a symlink — the last component AND every parent — and applies
# owner and mode to whatever it lands on, existing directories included. A runner
# that has been talked into replacing `~/.config` with a link to somebody else's
# would get that directory handed to it on Kevin's next, deliberately idempotent
# run. So every component of a path this script writes to is checked, not just
# its tail.
no_symlink_in() {  # no_symlink_in <absolute path> — refuse if any component is a link
  local p="$1" walk="" part
  case "$p" in
    /*) ;;
    *) echo "runner-setup: refusing a relative path: $p" >&2; exit 1 ;;
  esac
  local IFS='/'
  for part in ${p#/}; do
    walk="$walk/$part"
    if [ -L "$walk" ]; then
      echo "runner-setup: $walk is a symlink — refusing to write through it" >&2
      echo "  (remove it as root and run again: the runner's own home must be real directories)" >&2
      exit 1
    fi
  done
}
safe_dir() {  # safe_dir <path> — create it, but never through a symlink
  no_symlink_in "$1"
  run_sh "install -d -o $RUNNER -g $RUNNER -m 700 $(printf '%q' "$1")"
}
# A file written from a variable: the content never appears in argv either. The
# printed plan is redacted, because a plan gets pasted into terminals and PRs.
write_file() {  # write_file <path> <mode> <content> [redacted-preview]
  local path="$1" mode="$2" content="$3" preview="${4:-$3}"
  # Same reason as safe_dir: `install` and `>` both follow a symlinked parent.
  no_symlink_in "$path"
  printf '   $ install -o %s -g %s -m %s /dev/null %s   (content on stdin)\n' \
    "$RUNNER" "$RUNNER" "$mode" "$path"
  printf '%s\n' "$preview" | sed 's/^/       | /'
  [ "$DRY" = 1 ] && return 0
  install -o "$RUNNER" -g "$RUNNER" -m "$mode" /dev/null "$path" \
    && printf '%s' "$content" > "$path" \
    && chown "$RUNNER:$RUNNER" "$path" && chmod "$mode" "$path" \
    || { echo "runner-setup: failed to write $path" >&2; exit 1; }
}

if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ]; then
  echo "runner-setup: needs root (sudo bash scripts/dev/runner-setup.sh) — or --dry-run" >&2
  exit 2
fi

if [ "$REMOVE" = 1 ]; then
  if [ "$YES" != 1 ] && [ "$DRY" = 0 ]; then
    echo "runner-setup: --remove deletes $HOME_DIR, $SRV and the $DB_NAME database — add --yes" >&2
    exit 2
  fi
  # Repeatable on purpose: every step tolerates the thing already being gone, so
  # a half-finished removal can simply be run again.
  step "remove the database and its role"
  REMOVE_TOLERANT=1
  as_pg_sql "drop database" "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE);"
  as_pg_sql "drop role" "DROP ROLE IF EXISTS $DB_ROLE;"
  step "remove the user and its home"
  if [ "$DRY" = 1 ] || id "$RUNNER" >/dev/null 2>&1; then
    run_sh "userdel -r $(printf '%q' "$RUNNER") || true   # 6 = already gone"  # review: ok removal must stay repeatable
  else
    note "no such user: $RUNNER"
  fi
  step "remove the clone and the lanes"
  run rm -rf "$SRV"
  echo ""
  echo "── removed: $RUNNER, $SRV, $DB_NAME"
  exit 0
fi

# ── 0. preflight ─────────────────────────────────────────────────────────────
# Without this the run dies in step 3 or 5 — after useradd and the clone — with
# a `su` error instead of a sentence.
step "preflight: what this box has to provide"
MISSING=""
command -v git >/dev/null 2>&1 || MISSING="$MISSING git"
command -v psql >/dev/null 2>&1 || MISSING="$MISSING postgresql-client(psql)"
getent passwd postgres >/dev/null 2>&1 || MISSING="$MISSING the-postgres-account"
python3 -c 'import ensurepip' >/dev/null 2>&1 || MISSING="$MISSING python3-venv"
# The pinned CLI version goes into a string root hands to `su -c` (step 5), so it is
# checked here, before step 1 changes anything: exactly N.N.N, and the digits are
# spelled out because a [0-9] range can match other scripts' digits under a UTF-8
# locale.
CLAUDE_VERSION="$(tr -d '[:space:]' < "$ROOT/scripts/dev/runner-claude.version" 2>/dev/null)"
if ! [[ "$CLAUDE_VERSION" =~ ^[0123456789]+\.[0123456789]+\.[0123456789]+$ ]]; then
  echo "runner-setup: scripts/dev/runner-claude.version must hold a version like 2.1.280" >&2
  exit 1
fi
if [ -n "$MISSING" ]; then
  echo "   missing:$MISSING" >&2
  [ "$DRY" = 1 ] || { echo "runner-setup: install the above first" >&2; exit 1; }
else
  note "git, psql, the postgres account and python3-venv are present"
fi

# ── 1. the user ──────────────────────────────────────────────────────────────
step "user $RUNNER (no sudo group, no ssh key, no gh)"
if id "$RUNNER" >/dev/null 2>&1; then
  note "exists — useradd would be skipped"
else
  run useradd -m -s /bin/bash "$RUNNER"
  HOME_DIR="$(getent passwd "$RUNNER" 2>/dev/null | cut -d: -f6)"
  [ -n "$HOME_DIR" ] || HOME_DIR="/home/$RUNNER"
fi

# ── 2. the clone it works in ─────────────────────────────────────────────────
# The push URL is /dev/null, not "unset": an unset pushurl falls back to the
# fetch URL, and this user must not be able to push even if it finds a token.
ORIGIN="$(git -C "$ROOT" config --get remote.origin.url 2>/dev/null)"
[ -n "$ORIGIN" ] || ORIGIN="https://github.com/AdminCave/AdminHelper.git"
case "$ORIGIN" in
  git@*|ssh://*) echo "   WARNING: $ORIGIN is an SSH remote — this user has no key and could not fetch" >&2 ;;
esac
step "clone $SRV/repo from $ROOT, fetching from $ORIGIN, unable to push"
# The runner OWNS $SRV after the first run (chown -R below), so on every later
# run these paths are attacker-controlled: a $SRV/repo replaced by a symlink
# would make root's mkdir, `git clone` or `chown -R` act on whatever it points at.
no_symlink_in "$SRV"
no_symlink_in "$SRV/repo"
no_symlink_in "$SRV/lanes"
run mkdir -p "$SRV" "$SRV/lanes"
if [ -d "$SRV/repo/.git" ]; then
  note "exists — git clone would be skipped"
else
  # -b main: the runner's base is main, whatever branch this checkout sits on.
  run git clone --no-hardlinks -b main "$ROOT" "$SRV/repo"
fi
run chown -R "$RUNNER:$RUNNER" "$SRV"
# From here the clone belongs to the runner, on the first run as on every later
# one, so its config is written AS the runner. Root's git refuses a repository
# owned by somebody else (safe.directory; a second run of this script died right
# here on 2026-09-23), and it is right to: a runner-owned .git/config can name
# programs (core.fsmonitor, core.hooksPath) that root's git would then run.
run su - "$RUNNER" -c "git -C $SRV/repo config remote.origin.url $(printf '%q' "$ORIGIN")"
run su - "$RUNNER" -c "git -C $SRV/repo config remote.origin.pushurl /dev/null"

# ── 3. its own database, and the devenv that carries the password ────────────
# Both or neither: a rotated password without the matching devenv file leaves a
# runner whose AH_TEST_DB no longer works.
if [ "$DRY" = 1 ]; then
  DB_PW="<generated at run time>"
else
  DB_PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  [ -n "$DB_PW" ] || { echo "runner-setup: could not generate a password" >&2; exit 1; }
fi
step "Postgres role $DB_ROLE (CREATEDB, for the alembic smoke) and database $DB_NAME"
as_pg_sql "create or update the role" "DO \$\$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_ROLE') THEN
    ALTER ROLE $DB_ROLE LOGIN CREATEDB PASSWORD '$DB_PW';
  ELSE
    CREATE ROLE $DB_ROLE LOGIN CREATEDB PASSWORD '$DB_PW';
  END IF;
END
\$\$;"
step "$HOME_DIR/.devenv.sh (PATH, AH_TEST_DB, AH_REQUIRED)"
# AH_REQUIRED is what --strict insists on here: this box has python, shell and
# git — no go, rust or node. The heavy work happens on the VMs (Fast-Suite: vm).
DEVENV_CONTENT="export PATH=\"\$HOME/.local/bin:\$PATH\"
export AH_TEST_DB=\"postgresql://$DB_ROLE:$DB_PW@localhost/$DB_NAME\"
# run.sh puts the shared python venv in AH_VENV (default /tmp/ah-venv). That
# directory belongs to whoever created it first — as somebody else's, the pip
# install of the three python suites fails for this user.
export AH_VENV=\"\$HOME/.cache/ah-venv\"
export AH_REQUIRED=\"ruff ruff-vm shellcheck server-pytest monitoring-pytest ca-issuer-pytest scripts vm-pytest\"
"
write_file "$HOME_DIR/.devenv.sh" 600 "$DEVENV_CONTENT" \
  "${DEVENV_CONTENT//$DB_PW/<redacted>}"

if [ "$DRY" = 1 ]; then
  run_sh "su - postgres -c 'createdb -O $DB_ROLE $DB_NAME'   # unless it exists"
elif [ "$(as_pg_query "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" = 1 ]; then
  note "database $DB_NAME exists"
else
  run_sh "su - postgres -c 'createdb -O $DB_ROLE $DB_NAME'"
fi

# ── 4. the toolchain it needs locally ────────────────────────────────────────
step "python venv $HOME_DIR/.local/share/ah-tools/venv ($VENV_PKGS) and its symlinks"
run_sh "su - $RUNNER -c 'python3 -m venv --upgrade-deps ~/.local/share/ah-tools/venv'"
run_sh "su - $RUNNER -c '~/.local/share/ah-tools/venv/bin/pip install --quiet $VENV_PKGS'"
run_sh "su - $RUNNER -c 'mkdir -p ~/.local/bin && for b in ruff pytest python3; do ln -sfn ~/.local/share/ah-tools/venv/bin/\$b ~/.local/bin/\$b; done'"

# ── 5. its permission boundary ───────────────────────────────────────────────
step "$HOME_DIR/.claude/settings.json from scripts/dev/runner-settings.json"
safe_dir "$HOME_DIR/.claude"
run_sh "install -o $RUNNER -g $RUNNER -m 600 $(printf '%q' "$ROOT/scripts/dev/runner-settings.json") $(printf '%q' "$HOME_DIR/.claude/settings.json")"

# Claude Code ignores a project's allow list until the workspace is trusted — as
# adminhelper-runner it says so out loud: "Ignoring 38 permissions.allow entries
# … this workspace has not been trusted" (seen 2026-09-22). That direction is
# fail-safe, the DENY list keeps working, so this stays OFF unless it is asked
# for: accepting the trust is what arms those 38 allow rules, and that is Kevin's
# call, not a side effect of provisioning. From stage 7 on the runner needs it.
step "trusted workspace for $SRV/repo (only with --trust)"
if [ "$TRUST" = 1 ]; then
  # Same reason as everywhere else in this script: the runner OWNS its home, so
  # root writing into it must not follow a link the runner put there. O_NOFOLLOW
  # and O_EXCL cover the two files this step touches, no_symlink_in the path to
  # them; without that, a `.claude.json.new -> /etc/passwd` would be written as root.
  no_symlink_in "$HOME_DIR/.claude.json"
  no_symlink_in "$HOME_DIR/.claude.json.new"
  run_sh "$(printf '%q' "$(command -v python3)") - $(printf '%q' "$HOME_DIR/.claude.json") $(printf '%q' "$SRV/repo") <<'PY'
import json, os, sys
path, project = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    # O_NOFOLLOW: the file belongs to the runner, this process is root.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as fh:
        data = json.load(fh)
data.setdefault('projects', {}).setdefault(project, {})['hasTrustDialogAccepted'] = True
tmp = path + '.new'
# O_EXCL: a pre-placed .new is a reason to stop, not something to write through.
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as fh:
    json.dump(data, fh, indent=2)
os.chmod(tmp, 0o600)   # Claude Code keeps this file at 0600; it carries the account.
os.replace(tmp, path)
PY"
  run_sh "chown $RUNNER:$RUNNER $(printf '%q' "$HOME_DIR/.claude.json")"
  run_sh "chmod 600 $(printf '%q' "$HOME_DIR/.claude.json")"
else
  note "not done — run again with --trust when the runner's allow rules should apply (DEVELOPMENT.md)"
fi

# The CLI is pinned like every other toolchain in this repo (frp, oasdiff, Go, ruff):
# an unattended run must not change its substrate because an updater ran overnight.
# The version lives in ONE file, scripts/dev/runner-claude.version (read and checked in
# the preflight). This script reads it from THIS checkout, runner-redteam.sh reads it
# back from the runner's clone — both have to stand on the same main, or the red team
# reports a version the setup never installed (DEVELOPMENT.md, Anheben). 2.1.280
# is the first version whose model catalog knows claude-opus-5-5 — the 2.1.278 binary
# has no entry for it (measured 2026-09-23: 0 hits in the binary, 15 in 2.1.280).
# The auto-updater is off through runner-env.sh (DISABLE_AUTOUPDATER) — not through
# runner-settings.json, which is public and carries no env block.
step "Claude Code $CLAUDE_VERSION for $RUNNER (pinned; runner-env.sh switches the updater off)"
if [ "$DRY" = 1 ] || su - "$RUNNER" -c 'command -v claude' >/dev/null 2>&1; then
  run_sh "su - $RUNNER -c 'claude install $CLAUDE_VERSION'"
else
  note "no claude CLI for $RUNNER yet — install exactly this version, then run this again:"
  printf '     %s\n' "sudo -iu $RUNNER bash -c 'curl -fsSL https://claude.ai/install.sh | bash -s $CLAUDE_VERSION'"
fi

# ── 6. the two token files ───────────────────────────────────────────────────
# Written ONLY while they are still empty: after Kevin has put the tokens in,
# a second run of this script must not take them away again.
step "$HOME_DIR/.config/adminhelper/{oauth.env,pve.env} as 0600 templates"
safe_dir "$HOME_DIR/.config/adminhelper"
if [ -s "$HOME_DIR/.config/adminhelper/oauth.env" ]; then
  note "oauth.env already has content — left alone"
else
  write_file "$HOME_DIR/.config/adminhelper/oauth.env" 600 "# The subscription token of this user (roadmap D18: everything runs on the
# subscription, never on an API key). Create it with:
#   sudo -iu $RUNNER env DISABLE_AUTOUPDATER=1 claude setup-token
# then put it here as one line:
# CLAUDE_CODE_OAUTH_TOKEN=...
"
fi
if [ -s "$HOME_DIR/.config/adminhelper/pve.env" ]; then
  note "pve.env already has content — left alone"
else
  write_file "$HOME_DIR/.config/adminhelper/pve.env" 600 "# This user's own Proxmox token (pool adminhelper-ci only). Create it with:
#   pveum user token add $RUNNER@pve run --privsep 1
# then the four ACL paths, and put the values here as AH_PVE_* lines:
# AH_PVE_URL=...
# AH_PVE_NODE=...
# AH_PVE_TOKEN=...
"
fi

# ── 7. what this user must NOT have ──────────────────────────────────────────
step "check: no ssh key, no gh, not in a sudo group"
run_sh "test ! -e $(printf '%q' "$HOME_DIR/.ssh") || echo '   WARNING: $HOME_DIR/.ssh exists — remove it'"
run_sh "su - $RUNNER -c 'command -v gh' >/dev/null 2>&1 && echo '   WARNING: gh is on this user PATH' || echo '   ok: no gh'"
run_sh "id -nG $RUNNER | tr ' ' '\\n' | grep -qxE 'sudo|wheel|admin' && echo '   WARNING: $RUNNER is in a sudo group' || echo '   ok: no sudo group'"

cat <<HANDOVER

── done. Three steps are yours, $RUNNER cannot do them itself:

  1. sudo -iu $RUNNER env DISABLE_AUTOUPDATER=1 claude setup-token
     put the token into $HOME_DIR/.config/adminhelper/oauth.env

  2. pveum user token add $RUNNER@pve run --privsep 1   (plus the four ACL paths)
     put host, node, token id and secret into $HOME_DIR/.config/adminhelper/pve.env

  3. sudo -u $RUNNER git -C $SRV/repo pull --ff-only
     (not just fetch: the red team runs from that worktree and reads the pin there)
     then prove the boundary holds:
     sudo -u $RUNNER bash $SRV/repo/scripts/dev/runner-redteam.sh
HANDOVER
