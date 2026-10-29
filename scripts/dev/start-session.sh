#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# start-session.sh — start one of the sessions of CLAUDE.md §2 with its model,
# effort and goal.
#
#   bash scripts/dev/start-session.sh kern|klein|arch [<R-nnnn oder Slug>] [--dry-run]
#
#   kern   Opus, medium: SEC, REG, BUG with a data path, FEAT, install/update/
#          restore, release — its trains and the rows outside any klein- train
#   klein  Sonnet, medium: the klein- trains (docs, comments, test gaps, small
#          REF and UI bugs)
#   arch   Opus, xhigh: one architecture project across components, on Kevin's word
#
# Every session compacts at 200k (the measured sweet spot, 2026-10-29) and
# starts with a /goal, so it works through its trains without a prompt per
# step. --dry-run prints the command instead of running it.
#
# Exit: 0 ok · 2 usage · otherwise claude's

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
usage() { sed -n '/^#   bash scripts\/dev\/start-session.sh/p' "$0" | sed 's/^# \{0,1\}//'; }

KIND="" ARG="" DRY=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) usage; exit 0 ;;
    --*)       echo "start-session: unknown flag: $a" >&2; exit 2 ;;
    *)         if [ -z "$KIND" ]; then KIND="$a"; elif [ -z "$ARG" ]; then ARG="$a"
               else echo "start-session: unexpected argument: $a" >&2; exit 2; fi ;;
  esac
done

case "$KIND" in
  kern)
    [ -z "$ARG" ] || { echo "start-session: kern takes no argument" >&2; exit 2; }
    FLAGS=(--model opus --effort medium) NAME=adminhelper-kern
    GOAL="/goal Du bist die Kern-Session (CLAUDE.md §2). Zuerst bringst du die Züge unterwegs aus \`python3 scripts/dev/roadmap.py zuege --stufe kern\` zu Ende (Ledger aktiv/bereit, offene PRs: /feature-build ab dem Stand im Ledger, CLAUDE.md §13), dann die wartenden (oberster zuerst), dann \`roadmap.py next --status freigegeben --stufe kern\` und \`--status geplant --stufe kern\`; je Zug bzw. Zeile /feature-plan (Zug: --zug), /feature-build bis Merge, roadmap.py sync. Fertig, wenn \`zuege --stufe kern\` keinen Zug und beide next-Befehle nichts mehr zeigen, oder alles Übrige auf Kevin wartet (Fragen gesammelt mit Empfehlung gestellt); die Ausgabe der Befehle steht als Beleg im Verlauf."
    ;;
  klein)
    [ -z "$ARG" ] || { echo "start-session: klein takes no argument" >&2; exit 2; }
    FLAGS=(--model sonnet --effort medium) NAME=adminhelper-klein
    GOAL="/goal Du bist die Klein-Session (CLAUDE.md §2). Bring zuerst die Züge unterwegs aus \`python3 scripts/dev/roadmap.py zuege --stufe klein\` zu Ende (CLAUDE.md §13), dann arbeite die wartenden ab, den obersten zuerst: /feature-plan --zug, /feature-build bis Merge, roadmap.py sync. Task-Prüfer mit model \"sonnet\", security und Abschlussprüfung Opus (CLAUDE.md §6). Steht kein Zug an, aber es gibt neu-Zeilen, schlag Kevin /roadmap triage vor. Fertig, wenn \`roadmap.py zuege --stufe klein\` keinen Zug mehr zeigt oder alles Übrige auf Kevin wartet; die Ausgabe steht als Beleg im Verlauf."
    ;;
  arch)
    [ -n "$ARG" ] || { echo "start-session: arch needs the row or slug of the project" >&2; exit 2; }
    FLAGS=(--model opus --effort xhigh) NAME="adminhelper-arch"
    GOAL="/goal Du bist eine Architektur-Session (CLAUDE.md §2) für genau ein Vorhaben: $ARG. Sein Slug beginnt mit arch- (Ledger tasks/arch-<…>.md, roadmap.py --stufe arch), damit keine andere Session es aufnimmt. Plane es mit /feature-plan (Spec, Design-Gate) und baue es mit /feature-build bis zum Merge. Fertig, wenn der PR gemergt ist, die CI auf dem Merge-Commit grün ist und roadmap.py sync gelaufen ist, oder eine Entscheidung Kevins offen ist (Frage mit Empfehlung gestellt); Belege als Ausgabe im Verlauf."
    ;;
  *) usage >&2; exit 2 ;;
esac

CMD=(claude "${FLAGS[@]}" --autocompact 200k -n "$NAME" "$GOAL")
if [ "$DRY" = 1 ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi
cd "$ROOT" || exit 2
exec "${CMD[@]}"
