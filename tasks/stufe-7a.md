<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 7a — der Worker: `ledger-loop.sh`, `/build-task`, Bau-Session-Grenzen — Task-Ledger
Status: geplant · Branch: harness/stufe-7a · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Spec: docs/features/stufe-7a.md (Roadmap R-0010, R-0108)
Heavy: none — nur Harness-Skripte unter scripts/dev, ein Skill, ihre hermetischen Tests (claude-Stub, kein echter Modell-Aufruf, keine VM) und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den echten Lauf liefert der Pilot nach dem Merge (Spec, „Kevins Handarbeit“).
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Voraussetzungen (vor dem Start prüfen, sonst nicht anfangen): Stufe 6b gemergt **und** ihr `--review auto`-Pilot gefahren; `runner-vorarbeit-2` (R-0152) gemergt; Kevins Setup-, Pull- und Red-Team-Handgriffe nach #70 und nach `runner-vorarbeit-2` erledigt (Spec, „Kevins Handarbeit“ 1–3).

Geplant 2026-10-03 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-10-03 (A–G, Spec „Design“). Zeilenangaben
main@2508f092 — 6b ändert `task-close.sh` und `review.sh` noch; vor jeder Task an Symbolen orientieren, nicht an Zeilen.
Bau interaktiv (Harness-Pfade), keine Lane. Jede neue Datei unter `scripts/dev/` kommt in derselben Task nach
`scripts/dev/harness-paths.txt`, jeder neue Test in `AH_SCRIPT_TESTS_DEFAULT` (`scripts/tests/run.sh:586`). Kein Test ruft
die echte CLI: der `claude`-Stub folgt dem Muster aus 6b (`review_run_test.sh`). Fehlerfeld und Limit-Text der CLI-JSON
nimmt T4 aus den `Messung:`-Zeilen von 6b T1. Nie `sudo`, nie ein Lauf als `adminhelper-runner` im Bau.

### T1 — `/build-task`: genau eine Task, ohne Commit, ohne Haken  [ ]
Komponente: scripts · Dateien: .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh
Änderung: Neuer Skill (SPDX-Kommentar wie `.claude/skills/roadmap/SKILL.md`, Frontmatter ohne
`disable-model-invocation`), aufgerufen als `/build-task tasks/<slug>.md <id> [--fix <close-log> [<verdict>]]`. Inhalt:
Ledger-Kopf lesen — nicht `aktiv` oder keine `Freigabe:`-Zeile ⇒ sofort enden, nichts ändern; Task, Spec-Stelle und
echten Code lesen; surgical bauen; `bash scripts/dev/verify.sh <komponente> --strict` iterativ (Flag-Form); neue Dateien
per `ledger.sh set-files`; `[~]`/`[?]` nur per `ledger.sh mark-skip|mark-question`; am Ende die Commit-Nachricht
(Conventional Commit, englisch) nach `.ah-out/loop/<slug>/<id>.commit-msg.txt`. Mit `--fix`: nur die Punkte aus Log bzw.
Verdict, nur in den Task-Dateien. Ausdrücklich nicht: `git add|commit|stash|checkout|restore`, Edits unter `tasks/`,
Harness-Pfade, `task-close.sh`, Push, eigene Revert-Proben (die fährt der Runner, 6b), `mktemp`/`rm` direkt (Scratch nur
über `bash scripts/dev/scratch.sh new|rm`, T2). `skill_consistency_test.sh`: der Skill existiert, nennt den Pfad der
Commit-Nachricht genau so, wie `ledger-loop.sh` ihn liest (Konstante, ab T3; bis dahin der Text der Spec), nennt keinen
der verbotenen Befehle als Anweisung und jeden `bash scripts/…`-Befehl, den er anweist, mit einer Allow-Regel in
`scripts/dev/runner-settings.json`. Rot vorher: der Skill fehlt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)

### T2 — Bau-Session-Grenzen: Deny auf `tasks/**`, Scratch über `scratch.sh` (R-0108)  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, scripts/dev/scratch.sh, scripts/tests/scratch_test.sh, scripts/tests/hooks_test.sh, scripts/dev/harness-paths.txt, scripts/tests/run.sh
Änderung: `runner-settings.json`: Allow `Edit(./tasks/**)` (`:88`) entfällt; Deny `Edit(./tasks/**)` und
`Edit(//srv/ah/**/tasks/**)`; Allow `Edit(./.ah-out/loop/**)`, `Bash(bash scripts/dev/scratch.sh new:*)`,
`Bash(bash scripts/dev/scratch.sh rm:*)`. Neues `scripts/dev/scratch.sh` (SPDX): `new [<name>]` ⇒ `mktemp -d -p
<toplevel>/.ah-out/scratch <name>.XXXXXX` mit Marker-Datei, druckt den Pfad; `rm <pfad>` ⇒ löscht nur ein direktes Kind
dieses Ordners mit Marker, nach `realpath`, sonst Exit 2 mit Satz (kein Glob, kein Symlink, keine Traversal, kein fremder
Ordner). Kein `worktree`-Verb (Spec, „Bau-Session-Grenzen und R-0108“). Ein Allow und sein Ziel kommen in einen Commit,
deshalb eine Task mit sechs kleinen Dateien. Tests: `scratch_test.sh` (neu, SPDX) — `new` legt an und druckt, `rm` löscht
genau den einen; `rm` auf `../x`, einen Symlink, einen Ordner ohne Marker, einen Glob, den Scratch-Ordner selbst ⇒ Exit 2,
nichts gelöscht. `hooks_test.sh` Abschnitt runner-settings.json (`:1231`): Deny `Edit(./tasks/**)` vorhanden, kein Allow
`Edit(./tasks/**)` mehr, die zwei Scratch-Allows vorhanden, kein Allow für nacktes `mktemp`, `rm` oder `git worktree`.
Beweis (R-0108, statisch): main@2508f092 — `runner-settings.json` Allow-Liste `:55–105` ohne `mktemp`, `rm`,
`git worktree`; Doku permissions „Read-only commands“ ohne sie; `dontAsk` weist alles Übrige ab.
Dedup-Key: bug:scripts:runner-settings.json:mktemp-rm-denied
HEAD: 2508f092
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)

### T3 — `ledger-loop.sh`: Gerüst, Preflight, Ledger-Prüfung, Lane, Zustand  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/dev/harness-paths.txt, scripts/tests/run.sh
Änderung: Neues Skript (SPDX) `ledger-loop.sh --ledger <pfad>… [--max-hours 8] [--max-tasks 20] [--max-budget-usd 200]
[--max-ready 2] [--task-minutes 60] [--task-turns 80] [--task-budget 12]` und `ledger-loop.sh status [--state <datei>]`;
Zustand nach `${AH_LOOP_DIR:-/srv/ah/loop}` (`state.json`, `summary-<datum>.md`, `<slug>/`). Preflight wie Spec „Start und
Preflight“ (Fehlschlag ⇒ Exit 74, `stop: infra`), inklusive Fast-Forward des Klons nur ohne Harness-Wechsel. Je Ledger wie
Spec „Je Ledger“ 1–6: Freigabe-Prüfung, Harness-Ablehnung (G), `lane.sh new` bzw. Fortsetzen einer sauberen Lane,
`git merge origin/main`, Fundament-`verify.sh`, `aktiv` als Ledger-Commit des Loops (Helfer `ledger_commit`: nur
`tasks/<slug>.md` im Diff, sonst `stop: infra`). Noch keine Task-Iteration (T4). Overrides nur für den Test, wie
`heavy.sh` (`AH_LOOP_DIR`, `AH_LOOP_REPO`, `claude`-Stub). `ledger_loop_test.sh` (neu, SPDX), hermetisch in einem
Wegwerf-Repo mit lokalem Bare-`origin`: Ledger ohne `Freigabe:` ⇒ übersprungen; `harness/…`-Branch und ein
`Dateien:`-Harness-Pfad ⇒ `blockiert (harness)` ohne Lane; schmutzige Lane ⇒ `blockiert (Lane schmutzig)`, `git stash
list` leer, Datei unverändert; Merge-Konflikt ⇒ `blockiert (merge)`, Lane sauber; Klon hinter `origin/main` mit Harness-
Änderung ⇒ Exit 74 ohne Pull; ohne ⇒ Fast-Forward; fehlendes Token ⇒ Exit 74; `status` liest `state.json` und gibt
Steuerzeichen gereinigt aus.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)

### T4 — Task-Iteration: Bau-Session, `task-close --review auto`, Runde 2, Marker  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: Je Task wie Spec „Je Task“ 1–4: `ledger.sh start`; Bau-Session mit `timeout` und den drei Task-Deckeln, JSON
auswerten (Kosten, Turns, Verweigerungen, Fehlerart, Ergebnis); Commit-Nachricht vorhanden ⇒ `task-close.sh <ledger> <id>
--stage --review auto --message-file <datei>` aus dem Klon, in der Lane; Exit 0 weiter, 3 ⇒ eine `--fix`-Session mit
Close-Log und Verdict-Pfad, dann erneut, wieder 3 ⇒ `[?]` mit erstem Blocker; 4 ⇒ `[?]`; 74 ⇒ ein Wiederholungsversuch,
dann `stop: infra`; 2 ⇒ Iteration ohne Fortschritt. `[~]` ⇒ Ledger-Commit, weiter; `[?]` ⇒ Ledger-Commit, Ledger
`blockiert` (D), nächstes Ledger. Verweigerungen je Task ins `state.json`, nicht blockierend. Tests mit Stub-`claude`, der
staged-fähige Änderungen plus Nachricht schreibt, und Stub-`task-close` (Exit-Folgen vorgegeben): approve ⇒ ein Commit mit
Code und Ledger; 3 dann 0 ⇒ zwei Sessions, die zweite mit `--fix`; 3, 3 ⇒ `[?]`, `blockiert`, nächstes Ledger der Liste
läuft; 4 ⇒ `[?]`; 74, 74 ⇒ Exit 74, Task `[ ]`; Stub setzt `[~]` ⇒ Commit nur des Ledgers.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T3

### T5 — Abbruch-Aufräumen und Stall  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: Aufräumen als Loop-Operation wie Spec „Aufräumen“: `aborted.diff`, `git restore --source=HEAD --staged
--worktree` (wahlweise ohne das Ledger), neue Dateien einzeln mit vollem Pfad löschen, Scratch der Lane über
`scratch.sh rm`; nie `stash`, `clean` oder ein Glob. Auslöser: Timeout (124/143), `error_max_turns`,
`error_max_budget_usd`, sonstiger Fehler ⇒ `[?] timeout|turns|budget|error`, `blockiert`. Stall: Ledger nach zwei
Iterationen derselben Task byte-identisch ⇒ `[?] stall`, `blockiert`. Tests: Stub schläft über `--task-minutes` (im Test
Sekunden) ⇒ `aborted.diff` existiert, Lane sauber, untrackte Datei weg, Task `[?] timeout`; Stub meldet Budget- bzw.
Turn-Fehler ⇒ dasselbe mit `budget`/`turns`; Stub ändert nichts, zweimal ⇒ `[?] stall`; eine Datei außerhalb der Lane
bleibt unberührt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T4

### T6 — Lauf-Deckel, Nutzungslimit, Stopp-Klassen, Summary  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: An jeder Task-Grenze `--max-hours`, `--max-tasks`, `--max-budget-usd` (Summe `total_cost_usd`), `--max-ready`
⇒ `stop: max-hours|max-tasks|max-budget|kevin-queue`. Nutzungslimit (Ergebnistext „You've hit your … limit · resets …“,
Feld aus 6b T1) ⇒ Aufräumen, Task bleibt `[ ]`, `stop: usage-limit`, Reset-Zeit in `state.json` (C). Lane-Diff berührt
einen Harness-Pfad ⇒ `stop: harness-modified`. Alle Ledger `bereit`/`blockiert` ⇒ `stop: ledger-leer`. Am Ende
`summary-<datum>.md` mit der Schlusszeile `ledger-loop: <n> tasks, <k> ready, <b> blocked, <$> total, stop: <klasse>`.
Tests: je Klasse ein Lauf, der genau mit ihr endet; Limit-Stub ⇒ Task `[ ]`, Lane sauber, Reset-Zeit gelesen; ein
Deckel greift erst an der Task-Grenze, nie mitten in einer Session.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T5

### T7 — Ledger-Ende: PR-Text und Übergabe als Bundle  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: Steht das Ledger nach der letzten Task auf `bereit`: `review.sh pr-body tasks/<slug>.md` nach
`<loop>/<slug>/pr-body.md`, bei `Heavy:` ≠ `none` mit dem Vermerk „Heavy offen — fährt die Aufsicht“; `git bundle create
<loop>/<slug>.bundle origin/main..feature/<slug>` plus `git bundle verify`; dann das nächste Ledger der Liste. Kein Push,
kein PR. Tests: Ledger durchgelaufen ⇒ `pr-body.md` und Bundle liegen; ein zweites Repo holt den Branch per `git fetch
<bundle> feature/<slug>:feature/<slug>` und hat dieselben Commits; `Heavy: linux-full` ⇒ Vermerk im PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T4

### T8 — Stand sichtbar: `ledger-loop.sh status` und die Worker-Zeile im AH-STATUS  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: `session-status.sh:187`: statt „Worker: — (ab 7)“ liest der Hook `${AH_LOOP_STATE:-/srv/ah/loop/state.json}`,
wenn lesbar, nur als Datei (nie `git` in `/srv/ah`), und druckt „Worker: läuft T<k>/<n> tasks/<slug>.md · <$> · seit
<hh:mm>“ bzw. „Worker: stop: <klasse> <hh:mm>“ bzw. „Worker: —“; Texte gereinigt und gekürzt. `ledger-loop.sh status`
druckt dieselbe Zeile plus die letzten Summary-Zeilen. Tests: Zustandsdatei läuft, gestoppt, fehlt, kaputtes JSON (⇒
„Worker: ? (state.json unlesbar)“, kein Abbruch des Hooks), Steuerzeichen im Slug werden entfernt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T6

### T9 — Red Team prüft die Bau-Session  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Änderung: Abschnitt 5 (`runner-redteam.sh:338`) um die Bau-Session-Grenzen aus T2: statisch, ohne Modell, dass die
Runner-Settings Deny `Edit(./tasks/**)` tragen und die zwei Scratch-Allows; mit `claude_probe` (Budget ≤ 1 $, wie
heute): eine Session, die `tasks/<x>.md` per Umleitung ändern soll ⇒ `denied`; eine, die nacktes `mktemp -d` ausführen
soll ⇒ `denied`. `redteam_test.sh`: die neuen statischen Prüfungen gegen eine Settings-Kopie mit und ohne Deny; der
Verdikt-Pfad der neuen Proben über `--verdict` mit vorbereiteten Transkripten (denied/attempted/declined).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T2

### T10 — Doku: der Worker  [ ]
Komponente: scripts · Dateien: AUTONOMOUS.md, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: `AUTONOMOUS.md` neuer Abschnitt „Der Worker (Stufe 7a)“: Start (Kevins tmux-Zeile), Ledger-Liste, Deckel und
Flags, Stopp-Klassen, `[?]`/`blockiert`, Übergabe per Bundle und warum nie `git` im Runner-Repo, Pilot. `DEVELOPMENT.md`:
Worker starten, `ledger-loop.sh status`, Bundle holen, Recovery (Lane schmutzig, `stop: infra`), Setup erneut nach
Settings-Änderung. `cicd.html` DE+EN: der Worker in der Ebenen-Übersicht. `CHANGELOG.md` unter Unreleased. Keine
CLAUDE.md-Änderung (Kevins Handarbeit, Spec).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md · DEVELOPMENT.md · docs/developer/cicd.html + docs/en/developer/cicd.html · CHANGELOG.md
Abhängt von: T1–T9
