#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# nightly.sh — start the Sammellauf at night from cron instead of after every
# third linux-full merge (Kevin 2026-11-11, R-1337).
#
#   bash scripts/tests/nightly.sh run [--dry-run]
#   bash scripts/tests/nightly.sh install|uninstall|status
#
#   run        pre-flight, then `heavy.sh all` — on the weekly day `heavy.sh
#              weekly` (all, then the capstone) — detached in tmux `ah-nightly`.
#              The pre-flight, in this order; the first check that fails skips
#              the night:
#                1. the checkout is on main and clean (untracked files count)
#                2. no tmux session ah-* is running (a heavy run, or a session's)
#                3. git fetch origin, git merge --ff-only origin/main
#                4. `vm.py list` exits 0: nothing leaked, nothing foreign on the
#                   lane (vm.py reads pve.env and settings.local.json itself, so
#                   cron's bare environment is enough)
#              --dry-run runs 1, 2 and 4, fetches nothing, starts nothing and
#              writes no log line.
#   install    the one marked crontab line (01:30 every night); idempotent. A
#              crontab that cannot be read (other than "no crontab") is left
#              alone: exit 2, nothing written
#   uninstall  removes exactly that line, every other line stays
#   status     the line if installed, and the last lines of the log
#
# Every real `run` appends one line to $AH_OUT_DIR/nightly.log: the time, the
# mode and `start` or `skip: <reason>`. A skipped night is not a red run; the
# session reads this log next to the report (/feature-build §5).
#
# Exit: 0 started (or install/uninstall/status done) · 1 skipped, the reason in
#       the log · 2 usage
#
# Overrides for nightly_test.sh, never for real runs:
#   AH_NIGHTLY_ROOT        the checkout (default: this repo)
#   AH_NIGHTLY_HEAVY       what tmux runs instead of `bash scripts/tests/heavy.sh`
#   AH_NIGHTLY_VMPY        what runs instead of `python3 scripts/vm/vm.py`
#   AH_NIGHTLY_TODAY       the weekday 1..7 instead of `date +%u`
#   AH_NIGHTLY_WEEKLY_DAY  the weekday of `weekly`, 1..7 (default 6, Saturday)
#   AH_OUT_DIR             the output root (default <root>/.ah-out)

set -uo pipefail

ROOT="${AH_NIGHTLY_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
OUT="${AH_OUT_DIR:-$ROOT/.ah-out}"
LOG="$OUT/nightly.log"
HEAVY="${AH_NIGHTLY_HEAVY:-bash scripts/tests/heavy.sh}"
VMPY="${AH_NIGHTLY_VMPY:-python3 scripts/vm/vm.py}"
read -r -a VMPY_CMD <<<"$VMPY"
WEEKLY_DAY="${AH_NIGHTLY_WEEKLY_DAY:-6}"
SESSION=ah-nightly
MARK="# ah-nightly (scripts/tests/nightly.sh)"
# cron starts with PATH=/usr/bin:/bin; the session's tools (the ~/.local/bin links
# of CLAUDE.md §10) come after it, never before: in front they would shadow the
# fakes nightly_test.sh puts first, and a real crontab would be rewritten.
PATH="$PATH:$HOME/.local/bin:/usr/local/bin"

usage() { sed -n '/^#   bash scripts\/tests\/nightly.sh/p' "$0" | sed 's/^# \{0,1\}//'; }

VERB="${1:-}"; [ $# -gt 0 ] && shift
DRY=0
for a in "$@"; do
  case "$a" in
    --dry-run) [ "$VERB" = run ] || { echo "nightly: --dry-run only with run" >&2; exit 2; }; DRY=1 ;;
    *) echo "nightly: unexpected argument: $a" >&2; usage >&2; exit 2 ;;
  esac
done

today="${AH_NIGHTLY_TODAY:-$(date +%u)}"
mode=all; [ "$today" = "$WEEKLY_DAY" ] && mode=weekly

log() { mkdir -p "$OUT" && printf '%s %s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$mode" "$*" >>"$LOG"; }
skip() {
  echo "nightly: skip: $*" >&2
  [ "$DRY" = 1 ] || log "skip: $*"
  exit 1
}

preflight() {
  local branch dirty sessions s rc
  branch="$(git -C "$ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || echo '(detached)')"
  [ "$branch" = main ] || skip "checkout is on $branch, not main"
  dirty="$(git -C "$ROOT" status --porcelain 2>/dev/null)" || skip "git status failed"
  [ -z "$dirty" ] || skip "checkout not clean ($(printf '%s\n' "$dirty" | wc -l) path(s))"
  sessions="$(tmux list-sessions -F '#{session_name}' 2>/dev/null || true)"
  for s in $sessions; do
    case "$s" in ah-*) skip "tmux session $s is running" ;; esac
  done
  if [ "$DRY" = 0 ]; then
    git -C "$ROOT" fetch -q origin 2>/dev/null || skip "git fetch origin failed"
    git -C "$ROOT" merge -q --ff-only origin/main >/dev/null 2>&1 || skip "main does not fast-forward to origin/main"
  fi
  # Its listing names boxes and addresses: into the gitignored output root, never
  # into the log line or cron's mail.
  mkdir -p "$OUT"
  rc=0; (cd "$ROOT" && "${VMPY_CMD[@]}" list) >"$OUT/nightly-vmlist.out" 2>&1 || rc=$?
  [ "$rc" = 0 ] || skip "vm.py list exited $rc (see $OUT/nightly-vmlist.out)"
}

case "$VERB" in
  run)
    preflight
    if [ "$DRY" = 1 ]; then
      echo "nightly: pre-flight ok — would start '$HEAVY $mode' in tmux $SESSION"
      exit 0
    fi
    tmux new-session -d -s "$SESSION" -c "$ROOT" "$HEAVY $mode" || skip "tmux new-session failed"
    log "start (HEAD $(git -C "$ROOT" rev-parse --short HEAD))"
    echo "nightly: started '$HEAVY $mode' in tmux $SESSION"
    ;;
  install|uninstall)
    # Only "no crontab" means empty. Any other read error would make the write
    # below replace every line of the user's crontab with ours alone.
    rc=0; current="$(crontab -l 2>/dev/null)" || rc=$?
    if [ "$rc" != 0 ]; then
      msg="$(crontab -l 2>&1 >/dev/null)"
      case "$msg" in
        *"no crontab"*) current="" ;;
        *) echo "nightly: crontab -l failed (exit $rc), nothing written: $msg" >&2; exit 2 ;;
      esac
    fi
    others=""
    [ -z "$current" ] || others="$(printf '%s\n' "$current" | awk -v m="$MARK" 'index($0, m) == 0')"
    # cron ends a command at an unescaped %: a path holding one would cut the line.
    case "$ROOT$OUT" in *%*) echo "nightly: a path contains %, which cron cannot take: $ROOT $OUT" >&2; exit 2 ;; esac
    line="30 1 * * * cd $(printf '%q' "$ROOT") && AH_OUT_DIR=$(printf '%q' "$OUT") bash scripts/tests/nightly.sh run >>$(printf '%q' "$OUT/nightly-cron.out") 2>&1 $MARK"
    if [ "$VERB" = install ]; then
      { [ -n "$others" ] && printf '%s\n' "$others"; printf '%s\n' "$line"; } | crontab - \
        || { echo "nightly: crontab could not be written" >&2; exit 2; }
      echo "nightly: installed — every night at 01:30, weekly on day $WEEKLY_DAY"
    else
      { if [ -n "$others" ]; then printf '%s\n' "$others"; fi; } | crontab - \
        || { echo "nightly: crontab could not be written" >&2; exit 2; }
      echo "nightly: removed"
    fi
    ;;
  status)
    installed="$(crontab -l 2>/dev/null | awk -v m="$MARK" 'index($0, m) > 0')"
    if [ -n "$installed" ]; then echo "installed: $installed"; else echo "not installed"; fi
    if [ -f "$LOG" ]; then echo "last runs:"; tail -n 5 "$LOG"; else echo "no run logged yet"; fi
    ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
