#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# runner-env.sh — the environment the user `adminhelper-runner` works in.
# SOURCE it, do not execute it:
#
#   . scripts/dev/runner-env.sh
#
# What it establishes, and why each line is there (autonomy stage 4):
#
#   ~/.devenv.sh        PATH and AH_TEST_DB of this user — the runner has its own
#                       Postgres role, never Kevin's.
#   GH_TOKEN=""         there is no GitHub credential for this user. Empty rather
#   GITHUB_TOKEN=""     than unset, and a throwaway config dir, so a `gh` that is
#   GH_CONFIG_DIR=…     somehow reachable finds no login instead of inheriting
#                       one. Both names, because gh reads GH_TOKEN and falls
#                       through to GITHUB_TOKEN.
#   ANTHROPIC_API_KEY   unset, with ANTHROPIC_AUTH_TOKEN: both take PRECEDENCE
#                       over CLAUDE_CODE_OAUTH_TOKEN, and everything here runs on
#                       the subscription token (roadmap D18), never on an API key.
#   CLAUDE_CODE_OAUTH_TOKEN  unset first, then read out of
#                       ~/.config/adminhelper/oauth.env, which must be a regular
#                       0600 file — a token file the group can read is a finding,
#                       not a detail, so this aborts instead of warning.
#   AH_AUTONOMOUS=1     the session is unattended: the harness guard denies edits
#                       to harness paths, the status hook stays quiet.
#   AH_VM_MAX=8         the ceiling this user may lease in the pool.
#   AH_PVE_*            unset first, then this user's OWN Proxmox token from
#                       ~/.config/adminhelper/pve.env. The unset is the important
#                       half: vm.py lets the environment win over its config, so
#                       an inherited AH_PVE_TOKEN would quietly keep the runner on
#                       somebody else's hypervisor credential.
#
# Both env files are READ, not sourced: they carry data, and a token file that
# can execute code is a token file that can do anything the runner can.
#
# Returns non-zero (without killing the shell) when a token file is missing,
# empty, not a regular file or too permissive — that is the un-provisioned state,
# and a run that starts anyway would fail later with a worse message.
# scripts/dev/runner-setup.sh creates both files as 0600 templates.

ah_runner_env() {
  local cfg="$HOME/.config/adminhelper"
  local devenv="$HOME/.devenv.sh" oauth="$cfg/oauth.env" pve="$cfg/pve.env"
  local perm token line key value

  # shellcheck disable=SC1090  # per-host file, gitignored by design
  [ -f "$devenv" ] && . "$devenv"

  export GH_TOKEN="" GITHUB_TOKEN="" GH_ENTERPRISE_TOKEN="" GITHUB_ENTERPRISE_TOKEN=""
  # Always a fresh directory, never an inherited one: a GH_CONFIG_DIR that
  # happens to point at somebody's real gh config would pass an "is it a
  # directory" test and hand this user a working login — the exact opposite of
  # what the line is for. The cost is an empty directory per login.
  GH_CONFIG_DIR="$(mktemp -d)" \
    || { echo "runner-env: mktemp failed — gh would fall back to ~/.config/gh" >&2; return 1; }
  export GH_CONFIG_DIR
  unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN
  unset "${!AH_PVE_@}"
  export AH_AUTONOMOUS=1
  export AH_VM_MAX=8

  ah_secure_file() {  # ah_secure_file <path> -> 0 if it is a regular 0600 file of ours
    local f="$1" p
    if [ -L "$f" ]; then
      echo "runner-env: $f is a symlink — a token file must be a regular file" >&2
      return 1
    fi
    p="$(stat -c %a "$f" 2>/dev/null)"
    if [ "$p" != "600" ]; then
      echo "runner-env: $f is mode ${p:-?}, must be 600 — chmod 600 \"$f\"" >&2
      return 1
    fi
    if [ "$(stat -c %U "$f" 2>/dev/null)" != "$(id -un)" ]; then
      echo "runner-env: $f belongs to somebody else" >&2
      return 1
    fi
    return 0
  }

  # A 0600 file inside a directory others may write is a file others may replace.
  # Only the group and other digits count — the owner's write bit is the point of
  # owning the directory.
  perm="$(stat -c %a "$cfg" 2>/dev/null)"
  case "${perm: -2:1}${perm: -1}" in
    *[2367]*) echo "runner-env: $cfg is mode $perm — group/other must not write here (chmod 700 \"$cfg\")" >&2; return 1 ;;
  esac

  [ -e "$oauth" ] || {
    echo "runner-env: no $oauth — run: claude setup-token, then write CLAUDE_CODE_OAUTH_TOKEN=… into it" >&2
    return 1
  }
  ah_secure_file "$oauth" || return 1
  token="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}CLAUDE_CODE_OAUTH_TOKEN=//p' "$oauth" \
    | tail -n1 | sed 's/[[:space:]]*$//; s/^"\(.*\)"$/\1/; s/^'\''\(.*\)'\''$/\1/')"
  if [ -z "$token" ]; then
    echo "runner-env: $oauth has no CLAUDE_CODE_OAUTH_TOKEN= line yet (claude setup-token)" >&2
    return 1
  fi
  export CLAUDE_CODE_OAUTH_TOKEN="$token"

  # The Proxmox token of THIS user. Missing is not fatal: the scripts-only work
  # (python, shell, lint) needs no hypervisor, and vm.py says so itself — the
  # AH_PVE_* of another user are gone either way, that happened above.
  if [ -e "$pve" ]; then
    ah_secure_file "$pve" || return 1
    # `|| [ -n "$line" ]`: a last line without a newline is a value, not noise.
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line#"${line%%[![:space:]]*}"}"
      case "$line" in
        export[[:space:]]*) line="${line#export}"; line="${line#"${line%%[![:space:]]*}"}" ;;
      esac
      case "$line" in
        AH_PVE_*=*)
          key="${line%%=*}"
          value="$(printf '%s' "${line#*=}" | sed 's/[[:space:]]*$//; s/^"\(.*\)"$/\1/; s/^'\''\(.*\)'\''$/\1/')"
          export "$key=$value"
          ;;
      esac
    done < "$pve"
  fi
  return 0
}

ah_runner_env
