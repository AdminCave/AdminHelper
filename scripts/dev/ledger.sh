#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# ledger.sh — the one way a task's state changes in tasks/<slug>.md.
#
#   bash scripts/dev/ledger.sh start <ledger> <id>
#   bash scripts/dev/ledger.sh mark-done <ledger> <id> --evidence "<summary>" [--note "…"] [--review "…"]
#   bash scripts/dev/ledger.sh mark-skip <ledger> <id> "<reason>"
#   bash scripts/dev/ledger.sh mark-question <ledger> <id> "<question>"
#   bash scripts/dev/ledger.sh set-files <ledger> <id> <path…>
#   bash scripts/dev/ledger.sh status [<ledger> <value>]
#   bash scripts/dev/ledger.sh new-task <ledger> --title "…"
#   bash scripts/dev/ledger.sh lint <ledger>
#
# The ledger is the only truth about progress (CLAUDE.md §2), which is why the
# writing happens here and not in a model's editor: `mark-done` refuses to tick a
# box without the summary line of the run that proves it, and from stage 4 on
# `task-close.sh` is the only caller that has one.
#
# <ledger> is a path (tasks/foo.md) or just the slug (foo). <id> is the task id
# as it stands in its heading (`### T3 — …` -> T3). grep/sed/awk only: this runs
# on the runner user's box, which has no toolchain beyond python, git and shell.
#
# Free text (notes, reasons, evidence, titles) reaches awk through the
# ENVIRONMENT, never through `-v` or a sed pattern: awk resolves backslash
# escapes in a -v value, so a Windows path in a question would have torn the
# heading into two lines, and a `&` or `|` in a title would have been read as
# sed syntax.
#
# Exit: 0 ok · 1 lint found an error · 2 usage, unknown ledger or unknown task

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

STATES="geplant freigegeben aktiv bereit erledigt blockiert"

usage() { sed -n '/^#   bash scripts\/dev\/ledger.sh start/,/^# The ledger is/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die() { echo "ledger.sh: $*" >&2; exit 2; }

ledger_path() {
  local l="${1:-}"
  [ -n "$l" ] || die "which ledger?"
  case "$l" in */*) ;; *) l="tasks/$l" ;; esac
  case "$l" in *.md) ;; *) l="$l.md" ;; esac
  [ -f "$l" ] || die "no such ledger: $l"
  printf '%s\n' "$l"
}

check_id() {
  case "$1" in
    *[!A-Za-z0-9._-]*|"") die "not a task id: $1" ;;
  esac
}

have_task() { grep -qE "^###[[:space:]]+$2([[:space:]]|\$)" "$1"; }

# Rewrite through a temp file: a half-written ledger is the one file this project
# cannot reconstruct from anywhere else. The temp copy is removed only after the
# content is safely in place, and an empty result is refused outright — a ledger
# emptied by a failed awk would look like a finished one.
apply() {  # apply <file> <awk-program>   (values come from the environment)
  local f="$1" prog="$2" tmp
  tmp="$(mktemp)" || die "mktemp failed"
  if ! awk "$prog" "$f" > "$tmp" || [ ! -s "$tmp" ]; then
    rm -f "$tmp"; return 1
  fi
  if ! cat "$tmp" > "$f"; then
    echo "ledger.sh: could not write $f — the new content is kept at $tmp" >&2
    return 1
  fi
  rm -f "$tmp"
}

# ── the marker in the heading ────────────────────────────────────────────────
MARK_PROG='
BEGIN { id = ENVIRON["L_ID"]; mark = ENVIRON["L_MARK"]; note = ENVIRON["L_NOTE"]; done = 0 }
{
  if (!done && $0 ~ "^###[ \t]+" id "([ \t]|$)") {
    line = $0
    # Everything from the state box on is replaced, so re-marking a task does
    # not leave the previous note standing next to the new one.
    sub(/[ \t]*\[[ x~?]\].*$/, "", line)
    line = line "  " mark
    if (note != "") line = line " (" note ")"
    print line; done = 1; next
  }
  print
}
END { if (!done) exit 3 }'

mark() {  # mark <file> <id> <marker> <note>
  L_ID="$2" L_MARK="$3" L_NOTE="$4" apply "$1" "$MARK_PROG" \
    || die "no task $2 in $1"
}

# ── the Evidenz:/Review: lines under the heading ─────────────────────────────
EVIDENCE_PROG='
function emit() {
  if (ev != "") print "Evidenz: " ev
  if (rv != "") print "Review: " rv
}
BEGIN { id = ENVIRON["L_ID"]; ev = ENVIRON["L_EV"]; rv = ENVIRON["L_RV"] }
{
  if (pending) {
    pending = 0
    # Right under Komponente:/Dateien: when there is one, directly under the
    # heading when there is not.
    if ($0 ~ /^Komponente:/) { print; emit(); next }
    emit()
  }
  if ($0 ~ "^###[ \t]+" id "([ \t]|$)") { insec = 1; pending = 1; print; next }
  if (insec && ($0 ~ /^Evidenz:/ || $0 ~ /^Review:/)) next   # replace, never stack
  if (insec && ($0 ~ /^###[ \t]/ || $0 ~ /^## /)) insec = 0
  print
}
END { if (pending) emit() }'

# ── verbs ────────────────────────────────────────────────────────────────────
CMD="${1-}"; [ $# -gt 0 ] && shift

case "$CMD" in
  start)
    LEDGER="$(ledger_path "${1-}")" || exit 2
    ID="${2-}"; [ -n "$ID" ] || die "start needs a task id"; check_id "$ID"
    have_task "$LEDGER" "$ID" || die "no task $ID in $LEDGER"
    # The component and file list of the task, as the ledger states them: what
    # the scope check (review.sh) later holds the staged paths against.
    LINE="$(L_ID="$ID" awk '
      BEGIN { id = ENVIRON["L_ID"] }
      $0 ~ "^###[ \t]+" id "([ \t]|$)" { insec = 1; next }
      insec && /^Komponente:/ { print; exit }
      insec && (/^###[ \t]/ || /^## /) { exit }' "$LEDGER")"
    KOMP="$(sed -n 's/^Komponente:[[:space:]]*\([^·]*\).*/\1/p' <<<"$LINE" | sed 's/[[:space:]]*$//')"
    FILES="$(sed -n 's/.*Dateien:[[:space:]]*//p' <<<"$LINE")"
    mkdir -p "$ROOT/.vm" || die "cannot create .vm"
    printf '%s\t%s\t%s\t%s\n' "$LEDGER" "$ID" "$KOMP" "$FILES" > "$ROOT/.vm/active-task"
    echo "active task: $ID ($LEDGER) · component: ${KOMP:-?} · files: ${FILES:-?}"
    ;;

  mark-done)
    LEDGER="$(ledger_path "${1-}")" || exit 2
    ID="${2-}"; [ -n "$ID" ] || die "mark-done needs a task id"; check_id "$ID"
    shift 2
    NOTE="" EVIDENCE="" REVIEW=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --note)     shift; NOTE="${1-}" ;;
        --evidence) shift; EVIDENCE="${1-}" ;;
        --review)   shift; REVIEW="${1-}" ;;
        *) die "unknown flag for mark-done: $1" ;;
      esac
      shift 2>/dev/null || break
    done
    # The whole point of this verb: a green box without the run that made it
    # green is the failure mode this stage exists to end.
    [ -n "$EVIDENCE" ] || die "mark-done needs --evidence \"<summary line of the run>\""
    have_task "$LEDGER" "$ID" || die "no task $ID in $LEDGER"
    mark "$LEDGER" "$ID" "[x]" "$NOTE"
    L_ID="$ID" L_EV="$EVIDENCE" L_RV="$REVIEW" apply "$LEDGER" "$EVIDENCE_PROG" \
      || die "could not write the evidence lines"
    echo "$ID: [x] in $LEDGER"
    ;;

  mark-skip|mark-question)
    LEDGER="$(ledger_path "${1-}")" || exit 2
    ID="${2-}"; REASON="${3-}"
    [ -n "$ID" ] || die "$CMD needs a task id"; check_id "$ID"
    [ -n "$REASON" ] || die "$CMD needs a reason in quotes"
    have_task "$LEDGER" "$ID" || die "no task $ID in $LEDGER"
    if [ "$CMD" = mark-skip ]; then M="[~]"; else M="[?]"; fi
    mark "$LEDGER" "$ID" "$M" "$REASON"
    echo "$ID: $M in $LEDGER"
    ;;

  set-files)
    LEDGER="$(ledger_path "${1-}")" || exit 2
    ID="${2-}"; [ -n "$ID" ] || die "set-files needs a task id"; check_id "$ID"
    shift 2
    [ $# -gt 0 ] || die "set-files needs at least one path"
    have_task "$LEDGER" "$ID" || die "no task $ID in $LEDGER"
    L_ID="$ID" L_ADD="$*" apply "$LEDGER" '
      BEGIN { id = ENVIRON["L_ID"]; add = ENVIRON["L_ADD"] }
      {
        if ($0 ~ "^###[ \t]+" id "([ \t]|$)") { insec = 1; print; next }
        if (insec && $0 ~ /^Komponente:/) {
          n = split(add, want, " ")
          line = $0
          if (line !~ /Dateien:/) line = line " · Dateien:"
          for (i = 1; i <= n; i++)
            # Substring check on purpose: the list carries notes like
            # "scripts/tests/run.sh (Registrierung)", and a path already there
            # in any shape must not be added a second time.
            if (index(line, want[i]) == 0) line = line ", " want[i]
          sub(/Dateien:[ \t]*,[ \t]*/, "Dateien: ", line)
          print line; insec = 0; hit = 1; next
        }
        if (insec && ($0 ~ /^###[ \t]/ || $0 ~ /^## /)) insec = 0
        print
      }
      # A task without a Komponente: line has nowhere to put the paths, and a
      # silent no-op here would look exactly like a successful extension.
      END { if (!hit) exit 3 }' \
      || die "task $ID has no 'Komponente: … · Dateien: …' line to extend"
    grep -A1 -E "^###[[:space:]]+$ID([[:space:]]|\$)" "$LEDGER" | sed -n 2p
    ;;

  status)
    if [ $# -eq 0 ]; then
      # The overview every session starts from: one line per ledger, the state
      # first, then how much of it is still open.
      for f in tasks/*.md; do
        [ -f "$f" ] || continue
        [ "$f" = "tasks/README.md" ] && continue   # the conventions, not a ledger
        st="$(sed -n 's/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$f" | head -n1)"
        printf '%-34s %-12s %s\n' "$f" "${st:-?}" \
          "$(awk '
             /^###[ \t]/ {
               if ($0 ~ /\[x\]/) x++; else if ($0 ~ /\[~\]/) s++
               else if ($0 ~ /\[\?\]/) q++; else if ($0 ~ /\[ \]/) o++
             }
             END { printf "offen %d · fertig %d · übersprungen %d · Frage %d", o, x, s, q }' "$f")"
      done
      exit 0
    fi
    LEDGER="$(ledger_path "${1-}")" || exit 2
    VALUE="${2-}"; [ -n "$VALUE" ] || die "status needs a value ($STATES)"
    case " $STATES " in *" $VALUE "*) ;; *) die "unknown status: $VALUE (of $STATES)" ;; esac
    grep -qE '^Status:' "$LEDGER" || die "$LEDGER has no Status: line"
    L_VALUE="$VALUE" apply "$LEDGER" '
      BEGIN { value = ENVIRON["L_VALUE"] }
      !done && /^Status:/ { sub(/^Status:[ \t]*[^ \t·]*/, "Status: " value); done = 1 }
      { print }' || die "could not set the status"
    sed -n '/^Status:/{p;q}' "$LEDGER"
    ;;

  new-task)
    LEDGER="$(ledger_path "${1-}")" || exit 2
    shift
    TITLE=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --title) shift; TITLE="${1-}" ;;
        *) die "unknown flag for new-task: $1" ;;
      esac
      shift 2>/dev/null || break
    done
    [ -n "$TITLE" ] || die "new-task needs --title \"…\""
    TPL="tasks/templates/task.md"
    [ -f "$TPL" ] || die "no template at $TPL"
    NEXT="$(awk '
      /^###[ \t]+T[0-9]+/ { n = $2; sub(/^T/, "", n); if (n + 0 > max) max = n + 0 }
      END { print "T" (max + 1) }' "$LEDGER")"
    # The body of the template, with the placeholders replaced as TEXT: a title
    # is free text, and free text in a sed pattern is a title that can write
    # files (`s|<Titel>|a|w ./x`).
    BODY="$(L_ID="$NEXT" L_TITLE="$TITLE" awk '
      BEGIN { id = ENVIRON["L_ID"]; title = ENVIRON["L_TITLE"]; skip = 1 }
      skip { if ($0 == "-->") skip = 0; next }
      {
        line = $0
        p = index(line, "<ID>");    if (p) line = substr(line, 1, p - 1) id substr(line, p + 4)
        p = index(line, "<Titel>"); if (p) line = substr(line, 1, p - 1) title substr(line, p + 7)
        print line
      }' "$TPL")"
    [ -n "$BODY" ] || die "the template has no body below its comment"
    # In front of the closing section if there is one — a new task belongs to the
    # list, not behind the summary.
    if grep -qE '^## Abschluss' "$LEDGER"; then
      L_BODY="$BODY" apply "$LEDGER" '
        BEGIN { body = ENVIRON["L_BODY"] }
        !done && /^## Abschluss/ { print body; print ""; done = 1 }
        { print }
        END { if (!done) { print ""; print body } }' || die "could not append the task"
    else
      { printf '\n'; printf '%s\n' "$BODY"; } >> "$LEDGER" || die "could not append the task"
    fi
    echo "$NEXT — $TITLE appended to $LEDGER"
    ;;

  lint)
    LEDGER="$(ledger_path "${1-}")" || exit 2
    RC=0 WARNINGS=0
    # An env prefix in a Verify: line cannot be covered by a Bash allow-rule
    # (CLAUDE.md §7) — the run would prompt, and in an autonomous run it would
    # simply stop. Also after a `&&` and behind `env`, where it hides just as well.
    while IFS= read -r line; do
      echo "ERROR  Verify: line with an env prefix (an allow-rule never matches one): $line" >&2
      RC=1
    done < <(grep -E '^Verify:([[:space:]]+|.*(&&|;)[[:space:]]*)([A-Z_][A-Z0-9_]*=|source |\. )|^Verify:.*[[:space:]]env[[:space:]]+[A-Z_]+=' "$LEDGER")

    # A ticked box whose run left no summary line is exactly the claim this
    # stage stopped accepting.
    while IFS= read -r warn; do
      echo "WARN   $warn" >&2
      WARNINGS=$((WARNINGS + 1))
    done < <(awk '
      function flush() { if (open && !ev) print id ": [x] without an Evidenz: line" }
      /^###[ \t]/ { flush(); open = ($0 ~ /\[x\]/); id = $2; ev = 0; next }
      open && /^Evidenz:/ { ev = 1 }
      /^## / { flush(); open = 0 }
      END { flush() }' "$LEDGER")

    # A declared test deletion (review.sh diff-scan --task) needs the test and a
    # reason: the gate passes an assertion over only for the <file>::<test>
    # named here, and a deletion nobody can explain is the one thing it exists
    # to stop.
    while IFS= read -r entry; do
      echo "ERROR  Test-Löschung: '$entry' is not <file>::<test> — <reason>" >&2
      RC=1
    done < <(sed -n 's/^Test-Löschung:[[:space:]]*//p' "$LEDGER" | tr ';' '\n' \
      | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' \
      | grep -vE '^[^[:space:]:]+::[^—]*[^[:space:]—][[:space:]]+—[[:space:]]+[^[:space:]]')

    if grep -qE '^Status:[[:space:]]*aktiv' "$LEDGER" && ! grep -qE '^###.*\[ \]' "$LEDGER"; then
      echo "ERROR  Status: aktiv, but no open [ ] task left (tasks/README.md: the invariant)" >&2
      RC=1
    fi
    if [ "$RC" -eq 0 ]; then
      if [ "$WARNINGS" -gt 0 ]; then echo "lint: $LEDGER ok ($WARNINGS warning(s))"
      else echo "lint: $LEDGER ok"; fi
    fi
    exit "$RC"
    ;;

  -h|--help) usage ;;
  "") echo "ledger.sh needs a verb" >&2; usage >&2; exit 2 ;;
  *)  echo "unknown verb: $CMD" >&2; usage >&2; exit 2 ;;
esac
