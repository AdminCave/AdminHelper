#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# builder-home.sh — the builder HOME: ledger-loop.sh under Kevin's UID with a
# HOME of its own, no sudo (team plan 4b).
#
#   bash scripts/dev/builder-home.sh setup     create or bring up to date, idempotent
#   bash scripts/dev/builder-home.sh token     Kevin's step: claude setup-token, then
#                                              paste the token (read hidden)
#   bash scripts/dev/builder-home.sh status    what is missing; exit 1 if anything
#
# Layout under ${AH_BUILDER_DIR:-~/.cache/ah-builder}, as the first measuring run
# left it: home/ (the HOME of the sessions), repo/ (the clone the loop runs from,
# its lanes beside it), loop/ (the loop's state).
#
# setup runs from the main checkout and brings, each step only where it is not
# already so:
#   - the directories, 0700;
#   - the claude CLI of scripts/dev/runner-claude.version in home/, against the
#     root-owned checksum runner-setup.sh recorded (a difference is a note: the
#     loop's own preflight checks the version);
#   - the clone: from this checkout, origin as here, pushurl /dev/null,
#     core.hooksPath scripts/dev/hooks, fast-forwarded to origin/main. This is
#     Kevin's setup step the loop waits for before new harness rules count;
#   - home/.claude/settings.json from the CLONE's runner-settings.json: the lane
#     rules of the runner (//srv/ah/) moved to this directory, plus denies for
#     Kevin's real HOME and for every checkout's private files. They are absolute
#     (//path): ~/ in a session means home/ (Claude Code docs, permissions);
#   - a tools venv (ruff pinned as runner-setup.sh pins it, pytest), and
#     python3 as a wrapper onto it: a symlink starts the base python
#     (sys.prefix /usr, measured 2026-10-09), a wrapper the venv;
#   - its own test database on the server of this checkout's AH_TEST_DB, with
#     its credentials; the password travels in the environment, as in lane.sh;
#   - home/.devenv.sh (0600) and the git identity of this user.
# Neither setup nor status ever prints a password or a token, and setup never
# touches oauth.env.
#
# Test overrides: AH_BUILDER_DIR, AH_BUILDER_SUM (the recorded checksum),
# AH_BUILDER_CLAUDE (the CLI that installs the pinned one).
#
# Exit: 0 done · 1 a step failed, or status found something missing · 2 usage

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
B="${AH_BUILDER_DIR:-$HOME/.cache/ah-builder}"
# Absolute: the settings rules are written as //<path>, and a relative one would
# anchor somewhere else.
case "$B" in /*) ;; *) echo "builder-home: AH_BUILDER_DIR must be an absolute path" >&2; exit 2 ;; esac
H="$B/home"
CLONE="$B/repo"
V="$H/.local/share/ah-tools/venv"
OAUTH="$H/.config/adminhelper/oauth.env"
SUM="${AH_BUILDER_SUM:-/var/lib/adminhelper-dev/runner-claude.sha256}"
DBNAME=adminhelper_builder
# As runner-setup.sh VENV_PKGS: one ruff for every user that lints this repo.
VENV_PKGS=(ruff==0.15.20 pytest pytest-cov pytest-httpx)
# runner-env.sh's shape, spelled out: outside the C locale A-Z matches by collation.
TOKEN_RE='^sk-ant-oat01-[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]+$'

say() { printf '%s\n' "$*"; }
fail() { printf 'builder-home: %s\n' "$*" >&2; exit 1; }

pin() { tr -d '[:space:]' < "$ROOT/scripts/dev/runner-claude.version" 2>/dev/null; }

# write_if <path> <mode> — stdin to <path> only when it differs; prints whether.
# Through a file beside it and a rename: a reader never sees half a file, and the
# mode is right before the content lands.
write_if() {
  local f="$1" mode="$2" tmp
  tmp="$(mktemp "$f.XXXXXX")" || return 1
  cat > "$tmp" && chmod "$mode" "$tmp" || { rm -f "$tmp"; return 1; }
  if [ -f "$f" ] && [ ! -L "$f" ] && cmp -s "$tmp" "$f" && [ "$(stat -c %a "$f")" = "$mode" ]; then
    rm -f "$tmp"; say "  ok    $f"
  else
    mv -fT "$tmp" "$f" || { rm -f "$tmp"; return 1; }
    say "  wrote $f"
  fi
}

# The main checkout's AH_TEST_DB, as SQLAlchemy writes it. The file is sourced
# with -e/-u off, as lane.sh does: it is written for an interactive shell.
main_db_url() {
  [ -f "$ROOT/.devenv.sh" ] || return 0
  (set +eu; . "$ROOT/.devenv.sh" >/dev/null 2>&1; printf '%s' "${AH_TEST_DB:-}")  # review: ok sources an interactive-shell file, silences no test
}

# The same server with the builder's database name, for its .devenv.sh.
db_url() {
  local url
  url="$(main_db_url)"
  [ -z "$url" ] || printf '%s/%s' "${url%/*}" "$DBNAME"
}

# pg psql|createdb <args…> — on the server of the main checkout's AH_TEST_DB,
# connected to that database, with its credentials. The password travels in
# PGPASSWORD and not in an argument: every local user can read a process's
# arguments, only its owner its environment (lane.sh lane_db).
pg() {
  local prog="$1" url pass=""; shift
  url="$(main_db_url | sed -E 's#^postgres(ql)?(\+[a-z0-9]+)?://#postgresql://#')"
  if [[ "$url" =~ ^(postgresql://[^:@/]+):([^@]*)@(.*)$ ]]; then
    pass="${BASH_REMATCH[2]}"
    url="${BASH_REMATCH[1]}@${BASH_REMATCH[3]}"
    pass="${pass//\\/\\\\}"
    pass="$(printf '%b' "${pass//%/\\x}")"
  fi
  # A user:password the pattern did not take apart would go into an argument.
  [[ ! "$url" =~ ^[^/]*//[^/@]*:[^/@]*@ ]] || fail "AH_TEST_DB has a form whose password cannot be taken out of the URL"
  ( [ -z "$pass" ] || export PGPASSWORD="$pass"
    case "$prog" in
      psql) exec psql -X --dbname="$url" "$@" ;;
      createdb) exec createdb --maintenance-db="$url" "$@" ;;
    esac )
}

setup_dirs() {
  say "── directories (0700)"
  mkdir -p "$B/loop" "$H/.claude" "$H/.config/adminhelper" "$H/.local/bin" "$H/.cache" || fail "mkdir failed under $B"
  chmod 700 "$B" "$B/loop" "$H" "$H/.claude" "$H/.config" "$H/.config/adminhelper" || fail "chmod failed under $B"
  say "  ok    $B"
}

setup_cli() {
  local v real want got src
  v="$(pin)"
  [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "scripts/dev/runner-claude.version holds no version"
  say "── claude CLI $v"
  if [ ! -f "$H/.local/share/claude/versions/$v" ]; then
    src="${AH_BUILDER_CLAUDE:-$(command -v claude)}"
    [ -n "$src" ] && [ -x "$src" ] || fail "no claude CLI to install $v with"
    HOME="$H" DISABLE_AUTOUPDATER=1 "$src" install "$v" < /dev/null > "$B/install.log" 2>&1 \
      && [ -f "$H/.local/share/claude/versions/$v" ] || fail "claude install $v failed — see $B/install.log"
  fi
  ln -sfn "$H/.local/share/claude/versions/$v" "$H/.local/bin/claude" || fail "could not link $H/.local/bin/claude"
  real="$(readlink -f "$H/.local/bin/claude")"
  want="$(tr -d '[:space:]' < "$SUM" 2>/dev/null)"
  got="$(sha256sum < "$real" | cut -d' ' -f1)"
  if [ -z "$want" ]; then say "  note  no recorded checksum at $SUM (runner-setup.sh writes it)"
  elif [ "$got" = "$want" ]; then say "  ok    $real is the CLI runner-setup.sh recorded"
  else say "  note  $real differs from the checksum in $SUM"
  fi
}

setup_clone() {
  local origin
  say "── clone $CLONE"
  origin="$(git -C "$ROOT" config --get remote.origin.url)" || fail "this checkout has no origin"
  if [ ! -d "$CLONE/.git" ]; then
    git clone -q --no-hardlinks -b main "$ROOT" "$CLONE" || fail "git clone failed"
  fi
  git -C "$CLONE" config remote.origin.url "$origin" &&
    git -C "$CLONE" config remote.origin.pushurl /dev/null &&
    git -C "$CLONE" config core.hooksPath scripts/dev/hooks || fail "git config of the clone failed"
  # The loop wants a clean main checkout on main; setup neither cleans nor switches.
  [ "$(git -C "$CLONE" symbolic-ref -q --short HEAD)" = main ] || fail "$CLONE is not on main"
  [ -z "$(git -C "$CLONE" status --porcelain)" ] || fail "$CLONE has changes — they are left for you to look at"
  git -C "$CLONE" fetch -q --prune origin || fail "git fetch origin failed in $CLONE"
  git -C "$CLONE" merge -q --ff-only origin/main || fail "main of $CLONE does not fast-forward to origin/main"
  say "  ok    $(git -C "$CLONE" log --oneline -1)"
}

setup_settings() {
  local json
  say "── $H/.claude/settings.json from the clone's runner-settings.json"
  # Into a variable first: a failing generator must not leave an empty file.
  json="$(python3 - "$CLONE/scripts/dev/runner-settings.json" "$B" "$HOME" <<'PY'
import json, sys
src, builder, home = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3].rstrip("/")
d = json.load(open(src))
perm = d["permissions"]
# The runner lanes live under /srv/ah, the builder ones beside its clone.
for k in ("allow", "deny"):
    perm[k] = [r.replace("//srv/ah/", "/" + builder + "/") for r in perm[k]]
private = [home + "/" + p for p in (".ssh", ".config/gh", ".claude", ".config/adminhelper",
                                    ".local/share/keyrings", ".gnupg")]
for p in private:
    for tool in ("Read", "Edit"):
        perm["deny"].append(f"{tool}(/{p}/**)")
# The file beside ~/.claude: account and MCP settings.
for tool in ("Read", "Edit"):
    perm["deny"].append(f"{tool}(/{home}/.claude.json)")
for p in ("**/tasks/private/**", "**/.claude/settings.local.json"):
    for tool in ("Read", "Edit"):
        perm["deny"].append(f"{tool}(//{p})")
perm["deny"] += ["Bash(ssh:*)", "Bash(docker:*)"]
print(json.dumps(d, indent=2))
PY
)" || fail "could not build the settings from $CLONE/scripts/dev/runner-settings.json"
  printf '%s\n' "$json" | write_if "$H/.claude/settings.json" 600 || fail "could not write the builder settings"
}

setup_venv() {
  local wrapper
  say "── tools venv ${VENV_PKGS[*]}"
  [ -x "$V/bin/python3" ] || python3 -m venv "$V" || fail "python3 -m venv $V failed"
  "$V/bin/pip" install --quiet "${VENV_PKGS[@]}" < /dev/null || fail "pip install into $V failed"
  for t in ruff pytest; do ln -sfn "$V/bin/$t" "$H/.local/bin/$t" || fail "could not link $t"; done
  printf -v wrapper '#!/bin/sh\nexec "%s/bin/python3" "$@"\n' "$V"
  printf '%s' "$wrapper" | write_if "$H/.local/bin/python3" 755 || fail "could not write the python3 wrapper"
}

setup_db() {
  local exists
  say "── test database $DBNAME"
  [ -n "$(main_db_url)" ] || fail "no AH_TEST_DB in $ROOT/.devenv.sh — the builder needs a database server"
  exists="$(pg psql -Atqc "SELECT 1 FROM pg_database WHERE datname = '$DBNAME'" 2>/dev/null)"
  if [ "$exists" = 1 ]; then say "  ok    exists"
  else pg createdb "$DBNAME" || fail "createdb $DBNAME failed"; say "  made  $DBNAME"
  fi
}

setup_devenv() {
  local url
  say "── $H/.devenv.sh (0600)"
  url="$(db_url)"
  {
    printf 'export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"\n'
    printf 'export AH_TEST_DB="%s"\n' "$url"
    printf 'export AH_VENV="$HOME/.cache/ah-venv"\n'
    printf 'export AH_REQUIRED="ruff ruff-vm shellcheck server-pytest monitoring-pytest ca-issuer-pytest scripts vm-pytest dev-pytest"\n'
  } | write_if "$H/.devenv.sh" 600 || fail "could not write $H/.devenv.sh"
}

setup_git() {
  local name email
  say "── git identity"
  name="$(git config --global user.name)" && email="$(git config --global user.email)" \
    || fail "no git user.name/user.email to give the builder"
  # Its own file: with HOME alone, git would take an XDG config of the caller's.
  git config --file "$H/.gitconfig" user.name "$name" && git config --file "$H/.gitconfig" user.email "$email" \
    || fail "git config failed for $H/.gitconfig"
  say "  ok    $name"
}

do_setup() {
  setup_dirs
  setup_cli
  setup_clone
  setup_settings
  setup_venv
  setup_db
  setup_devenv
  setup_git
  say ""
  if [ -s "$OAUTH" ]; then say "oauth.env is there — left as it is"
  else say "still missing: the token — bash scripts/dev/builder-home.sh token"
  fi
}

do_token() {
  local tok
  [ -x "$H/.local/bin/claude" ] || fail "no CLI in $H yet — run setup first"
  HOME="$H" DISABLE_AUTOUPDATER=1 "$H/.local/bin/claude" setup-token || fail "claude setup-token failed"
  printf 'Paste the token it printed (hidden): ' >&2
  IFS= read -rs tok
  printf '\n' >&2
  # The same shape runner-env.sh takes; the browser's code on the way carries a #.
  [[ "$tok" =~ $TOKEN_RE ]] \
    || fail "that is not a token of the form sk-ant-oat01-… (the code the browser shows is not the token) — nothing written"
  printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$tok" | write_if "$OAUTH" 600 >/dev/null || fail "could not write $OAUTH"
  say "token written to $OAUTH (0600)"
}

# runner-env.sh's own verdict on the builder's token files (mode, owner, shape),
# the one the loop's preflight will give: in a subshell, without the devenv,
# nothing printed but its message, which never names a value. The empty
# GH_CONFIG_DIR it makes goes again.
token_ok() {
  ( export HOME="$H" AH_RUNNER_ENV_NO_DEVENV=1
    # shellcheck source=scripts/dev/runner-env.sh
    . "$CLONE/scripts/dev/runner-env.sh" > /dev/null; rc=$?
    [ -z "${GH_CONFIG_DIR:-}" ] || rmdir -- "$GH_CONFIG_DIR" 2>/dev/null
    exit "$rc" )
}

do_status() {
  local miss=0 v why
  v="$(pin)"
  m() { say "missing: $*"; miss=1; }
  [ "$(stat -c %a "$H" 2>/dev/null)" = 700 ] || m "$H (0700)"
  [ -x "$H/.local/bin/claude" ] && [ "$(readlink -f "$H/.local/bin/claude")" = "$(readlink -f "$H/.local/share/claude/versions/$v")" ] \
    || m "the claude CLI $v in $H"
  [ -f "$H/.claude/settings.json" ] || m "$H/.claude/settings.json"
  [ -x "$V/bin/ruff" ] || m "ruff in $V"
  [ -f "$H/.local/bin/python3" ] && [ ! -L "$H/.local/bin/python3" ] || m "the python3 wrapper in $H/.local/bin"
  [ "$(stat -c %a "$H/.devenv.sh" 2>/dev/null)" = 600 ] || m "$H/.devenv.sh (0600)"
  [ "$(git -C "$CLONE" config --get remote.origin.pushurl 2>/dev/null)" = /dev/null ] || m "the clone $CLONE (pushurl /dev/null)"
  [ -n "$(git config --file "$H/.gitconfig" user.email 2>/dev/null)" ] || m "the git identity in $H/.gitconfig"
  if [ ! -f "$CLONE/scripts/dev/runner-env.sh" ]; then m "the clone's runner-env.sh — run setup"
  elif ! why="$(token_ok 2>&1)"; then
    m "the token, as runner-env.sh takes it, in $OAUTH — bash scripts/dev/builder-home.sh token"
    [ -z "$why" ] || printf '  %s\n' "$why"
  fi
  [ "$miss" = 0 ] && say "builder home $B: complete"
  return "$miss"
}

case "${1-}" in
  setup) do_setup ;;
  token) do_token ;;
  status) do_status ;;
  -h|--help) sed -n '/^#   bash/,/^#$/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
  *) sed -n '/^#   bash/,/^#$/p' "$0" | sed '$d; s/^# \{0,1\}//' >&2; exit 2 ;;
esac
