#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# harness.sh — the kill switch for the harness guard (autonomy stage 4).
#
#   bash scripts/dev/harness.sh off      write .vm/harness.off; the PreToolUse
#                                        guard then only warns about harness paths
#   bash scripts/dev/harness.sh on       remove the marker; the guard denies again
#   bash scripts/dev/harness.sh status   marker, AH_AUTONOMOUS, and whether the
#                                        guard is registered in .claude/settings.json
#
# A marker FILE, not an environment variable: hooks are started by Claude Code,
# not from the session's shell, so a variable exported inside a Bash tool call
# would never reach them. The file lives in .vm/ (gitignored), so a guard that
# was switched off cannot travel into a commit.
#
# Exit: 0 the verb ran · 2 no verb, or one this script does not know.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
MARKER="$ROOT/.vm/harness.off"
SETTINGS="$ROOT/.claude/settings.json"

usage() { sed -n '/^#   bash scripts\/dev\/harness.sh off/,/^# A marker FILE/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }

# Informational only, so a grep for the script name is enough: status answers
# "did someone wire the guard up at all", not "is this JSON shaped right" — the
# settings file's structure is checked by hooks_test.sh, against the real file.
hook_line() {
  if [ ! -f "$SETTINGS" ]; then
    echo "PreToolUse hook: no .claude/settings.json at $SETTINGS"
  elif grep -q 'harness-guard\.sh' "$SETTINGS"; then
    echo "PreToolUse hook: registered in .claude/settings.json"
  else
    echo "PreToolUse hook: NOT registered in .claude/settings.json"
  fi
}

case "${1-}" in
  off)
    mkdir -p "$ROOT/.vm" || exit 2
    # Overwritten, not appended: the line says since when the guard has been
    # off, and a second `off` restarting that clock is the honest answer.
    printf 'harness guard off since %s by %s\n' \
      "$(date -Is)" "${USER:-$(id -un)}" > "$MARKER" || exit 2
    echo "harness guard OFF — $MARKER"
    echo "  edits to harness paths only warn now; 'harness.sh on' arms it again"
    ;;
  on)
    if [ -e "$MARKER" ]; then
      rm -f "$MARKER" || exit 2
      echo "harness guard armed — marker removed"
    else
      echo "harness guard armed — no marker was set"
    fi
    ;;
  status)
    if [ -e "$MARKER" ]; then
      echo "harness guard:   OFF ($(head -n1 "$MARKER" 2>/dev/null))"
    else
      echo "harness guard:   armed (no marker at $MARKER)"
    fi
    if [ "${AH_AUTONOMOUS:-}" = "1" ]; then
      echo "AH_AUTONOMOUS:   1 (autonomous run — the guard denies)"
    else
      echo "AH_AUTONOMOUS:   ${AH_AUTONOMOUS:-unset} (interactive — the guard warns)"
    fi
    hook_line
    ;;
  -h|--help) usage ;;
  "") echo "harness.sh needs a verb" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown verb: $1" >&2; usage >&2; exit 2 ;;
esac
