#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# session-status.sh — the AH-STATUS block a session starts with (CLAUDE.md §3:
# "Stand feststellen, nicht raten"). Read-only, exits 0 unconditionally: a
# SessionStart hook that fails or blocks would break every session, so every
# fact is best-effort and an unavailable one prints "?" instead of erroring.
#
# Run: bash scripts/dev/hooks/session-status.sh [--for test|build-queue|find]
#
#   AH_AUTONOMOUS=1  print nothing (settings hooks fire in `claude -p` too)
#   AH_DEVENV        path to the devenv file (default <root>/.devenv.sh)
#
# The WARN lines fire ONLY when Kevin's next move would fail or something
# irreversible looms. No trigger, no WARN line.
#
# Line 4 carries the weekly run's verdict, read verbatim from the newest
# non-empty $AH_OUT_DIR/weekly/<stamp>/report.md (heavy.sh, stage 3); "kein
# Report" when none exists yet. The WARN trigger "release without a green weekly
# run" (CLAUDE.md §3 trigger 2) deliberately waits for stage 13 — a FAIL here
# without a WARN line does not mean the trigger already fired.
#
# Implemented: version bumped without a tag · main ahead of origin · an open draft
# release · .claude/rules or .claude/agents gitignored · an env block in the public
# settings.json · tasks/private unpushed or without a remote · AH_TEST_DB missing.
#
# NOT yet implemented, so their silence means nothing: CLAUDE.md §3 trigger 1
# (a stage whose `Hängt ab von` is unmerged), 3 (the WIP caps aktiv 1 · bereit 2 ·
# pr 3 · neu 20 — the ledger line below merges aktiv and bereit, so the two caps
# cannot be told apart as printed), 4 (harness files changed in a feature branch)
# and 5 (the main checkout not clean while planning or merging).

set -uo pipefail

[ "${AH_AUTONOMOUS:-0}" = "1" ] && exit 0

# --for <lane> is a preflight hook for later stages (test/build-queue/find get
# their own probes); accepted and ignored here so callers can already pass it.
while [ $# -gt 0 ]; do
  case "$1" in
    --for) shift 2>/dev/null; [ $# -gt 0 ] && shift ;;
    --for=*) shift ;;
    *) shift ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -n "$ROOT" ] || exit 0
cd "$ROOT" || exit 0

WARNINGS=()
warn() { WARNINGS+=("$1"); }
gh_json() {  # gh_json <args…> -> value, or "?" when gh/network/auth is unavailable
  local out
  out="$(timeout 3 gh "$@" 2>/dev/null)" && [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
  echo "?"
}

# ── line 1: checkout ──────────────────────────────────────────────────────────
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
DIRTY="$(git status --porcelain 2>/dev/null | grep -c .)"
if UP="$(git rev-list --count --left-right '@{upstream}...HEAD' 2>/dev/null)"; then
  ORIGIN="+${UP##*[[:space:]]}/-${UP%%[[:space:]]*}"
else
  ORIGIN="?"
fi

# The hook runs without `source .devenv.sh`, so an unset AH_TEST_DB says nothing
# about the box. Treat "declared in the devenv file" as present — that is what
# makes `verify.sh`/`run.sh` work once the shell sources it.
DEVENV="${AH_DEVENV:-$ROOT/.devenv.sh}"
if [ -n "${AH_TEST_DB:-}" ] || { [ -f "$DEVENV" ] && grep -qE '^[[:space:]]*(export[[:space:]]+)?AH_TEST_DB=' "$DEVENV"; }; then
  TESTDB="ok"
else
  TESTDB="fehlt"
  warn "AH_TEST_DB fehlt (weder Env noch $DEVENV) — server-pytest skippt still; Zeile in .devenv.sh nachtragen."
fi

echo "AH-STATUS $(date +%F) · $BRANCH @$SHA · $DIRTY dirty · origin $ORIGIN · AH_TEST_DB $TESTDB"

# ── line 2: release ───────────────────────────────────────────────────────────
TAURI_CONF="apps/desktop/src-tauri/tauri.conf.json"
VERSION="$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$TAURI_CONF" 2>/dev/null | head -1)"
[ -n "$VERSION" ] || VERSION="?"
LAST_TAG="$(git tag --sort=-v:refname 2>/dev/null | head -1)"
[ -n "$LAST_TAG" ] || LAST_TAG="—"
DRAFTS="$(gh_json release list --limit 20 --json isDraft -q '[.[]|select(.isDraft)]|length')"
case "$DRAFTS" in
  "?") DRAFT="?" ;;
  0)   DRAFT="nein" ;;
  *)   DRAFT="ja"
       warn "$DRAFTS Draft-Release offen — ein halb geschnittenes Release; \`gh release view\` prüfen, dann publish oder löschen." ;;
esac
echo "Release: tauri $VERSION · letzter Tag $LAST_TAG · Draft: $DRAFT"

if [ "$VERSION" != "?" ] && ! git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null 2>&1; then
  warn "tauri.conf.json $VERSION, kein Tag v$VERSION — Release halb geschnitten; erst die drei Testebenen, dann Tag und Push."
fi

# ── line 3: roadmap ───────────────────────────────────────────────────────────
ROADMAP="tasks/private/ROADMAP.md"
if [ -f "$ROADMAP" ]; then
  echo "Roadmap:"
  awk '/^## Als Nächstes/{f=1;next} f&&/^## /{exit} f&&NF{print "  " $0; n++; if(n==4) exit}' "$ROADMAP"
else
  echo "Roadmap: fehlt ($ROADMAP)"
fi

# ── line 4: ledgers, PRs, weekly run ──────────────────────────────────────────
LEDGERS="$(grep -lE '^Status:[[:space:]]*(aktiv|bereit)\b' tasks/*.md 2>/dev/null \
  | sed 's|.*/||; s|\.md$||' | paste -sd' ' -)"
[ -n "$LEDGERS" ] || LEDGERS="—"
PRS="$(gh_json pr list --state open --limit 50 --json number -q 'length')"

# The newest weekly report's OWN first line (heavy.sh writes exactly one:
# PASS | FAIL | UNVERIFIED (<reason>)). Nothing is re-derived here — a second
# place computing the verdict is a second place that can disagree with it.
weekly_line() {
  local out f dir="" stamp day head t0 now n
  out="${AH_OUT_DIR:-$ROOT/.crabbox-out}"
  # Newest FIRST, and the newest non-empty report.md wins — not the newest
  # DIRECTORY. heavy.sh creates the run directory before it starts and writes the
  # report at the very end, so while a run is going (hours), and forever after a
  # hard abort, the newest directory holds no verdict. Reporting "kein Report"
  # there would hide last week's result exactly when it is still the truth.
  # Stamps are jjjj-mm-tt-hhmm, so lexicographic order IS chronological order.
  # The verdict itself decides, not the file's size: an unreadable report or one
  # that starts with a blank line must fall through to the previous week just as
  # an absent one does — otherwise the fallback has a hole of its own.
  while IFS= read -r f; do
    head="$(head -1 "$f" 2>/dev/null)"
    [ -n "$head" ] || continue
    dir="$(dirname "$f")"; break
  done < <(ls -1d "$out"/weekly/*/report.md 2>/dev/null | sort -r)
  [ -n "$dir" ] || { echo "kein Report"; return 0; }
  stamp="$(basename "$dir")"; day="${stamp%-*}"
  # Both ends normalised to UTC midnight: a local-time difference is off by one
  # for an hour around a DST change, and "(3 d)" that flickers is worse than none.
  if t0="$(date -u -d "$day" +%s 2>/dev/null)" && now="$(date -u -d "$(date +%F)" +%s 2>/dev/null)"; then
    n=$(( (now - t0) / 86400 ))
    [ "$n" -lt 0 ] && n=0   # clock skew: a report from the future is 0 days old
    echo "$day ($n d): $head"
  else
    echo "$day: $head"
  fi
}
echo "Ledger aktiv|bereit: $LEDGERS · PRs offen: $PRS · Wochenlauf: $(weekly_line) · Worker: — (ab 7)"

# ── line 5: warm boxes ────────────────────────────────────────────────────────
WARM="$(grep -E '^[A-Za-z0-9_-]+=' .crabbox/warm.env 2>/dev/null | paste -sd' ' -)"
[ -n "$WARM" ] || WARM="leer"
echo "VMs: warm.env $WARM"

# ── remaining triggers ────────────────────────────────────────────────────────
AHEAD_MAIN="$(git rev-list --count origin/main..main 2>/dev/null)"
if [ -n "$AHEAD_MAIN" ] && [ "$AHEAD_MAIN" -gt 0 ] 2>/dev/null; then
  warn "main $AHEAD_MAIN Commit(s) vor origin/main — Push auf main setzt Kevin; Befehl nennen, nicht ausführen."
fi

# --no-index: `git check-ignore` stays silent about TRACKED paths by default, so
# without it the very case worth warning about — the rules are committed today but
# a new ignore rule would drop them from the next clone — reports clean.
for d in .claude/rules .claude/agents; do
  [ -d "$d" ] || continue
  if git check-ignore --no-index -q "$d" 2>/dev/null; then
    warn "$d ist gitignored — die Regeln fehlen im Repo; .gitignore-Whitelist um '!$d/' ergänzen."
  fi
done

if [ -f .claude/settings.json ] && grep -qE '^[[:space:]]*"env"[[:space:]]*:' .claude/settings.json; then
  warn "env-Block in .claude/settings.json — dieses Repo ist öffentlich; Provider-Env gehört in settings.local.json."
fi

# --show-toplevel compared against the expected path, not `rev-parse --git-dir`:
# that one walks UP when tasks/private is a plain directory and would then report
# the main repo's unpushed commits as the private repo's (a false warning on every
# checkout without the private clone). The comparison also covers the worktree and
# submodule layouts, where .git is a file rather than a directory.
if [ "$(git -C tasks/private rev-parse --show-toplevel 2>/dev/null)" = "$ROOT/tasks/private" ]; then
  if [ -z "$(git -C tasks/private remote 2>/dev/null)" ]; then
    warn "tasks/private hat kein Remote — Roadmap und Sicherheitsfunde liegen nur lokal; privates Repo anhängen."
  else
    UNPUSHED="$(git -C tasks/private rev-list --count '@{upstream}..HEAD' 2>/dev/null)"
    if [ -n "$UNPUSHED" ] && [ "$UNPUSHED" -ge 3 ] 2>/dev/null; then
      warn "tasks/private $UNPUSHED Commits unpushed — die Reihenfolge-Wahrheit ist nur lokal; im privaten Repo pushen."
    fi
  fi
fi

for w in ${WARNINGS+"${WARNINGS[@]}"}; do echo "WARN: $w"; done
exit 0
