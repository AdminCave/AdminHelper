<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 7a — der Worker: `ledger-loop.sh`, `/build-task`, Bau-Session-Grenzen — Task-Ledger
Status: bereit · Branch: harness/stufe-7a · Commit-Granularität: pro Task · Review: auto · Modell: Opus
Freigabe: Kevin, 2026-10-03 (Design-Gate Stufe 7a, „Freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Pilot: Stufe 6b — `Review: auto` (Reviewer als eigener Prozess über `task-close.sh --review auto`, im tmux mit Wächter); Kevin 2026-10-04, „7a selbst als Pilot“. Zweimal Exit 74 in einer Task ⇒ STOPP und Meldung. Kosten je Runde: `bash scripts/dev/review.sh log --ledger tasks/stufe-7a.md`.
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

### T1 — `/build-task`: genau eine Task, ohne Commit, ohne Haken  [x]
Komponente: scripts · Dateien: .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ccd26100 2026-10-04T21:10:43+02:00
Review: approve (opus/xhigh; 3 nit) · round 1
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
Abweichung: der Skill nennt den Scratch-Wrapper in T1 nur als Grenze, ohne Befehl; die Zeilen
`bash scripts/dev/scratch.sh new|rm` kommen mit T2 in den Skill, im selben Commit wie ihre Allow-Regeln (die Prüfung
„jeder angewiesene `bash scripts/…`-Befehl hat eine Allow-Regel“ wäre sonst bis T2 rot).

### T2 — Bau-Session-Grenzen: Deny auf `tasks/**`, Scratch über `scratch.sh` (R-0108)  [x]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, scripts/dev/scratch.sh, scripts/tests/scratch_test.sh, scripts/tests/hooks_test.sh, scripts/dev/harness-paths.txt, scripts/tests/run.sh, .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh, scripts/dev/hooks/harness-guard.sh, scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @38ea4864 2026-10-04T22:05:42+02:00
Review: approve (opus/xhigh; 3 nit) · round 2
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
Dazu (Aufsicht 2026-10-04, Kevin): die Zeilen `bash scripts/dev/scratch.sh new|rm` kommen in den Skill
`/build-task` (Abweichung aus T1), der Detektor in `skill_consistency_test.sh` liest auch Fenced-Blöcke und fällt rot,
wenn die Settings nicht laden (nits aus dem T1-Verdict). R-0164: der Guard des Runner-Hooks ist root-eigen
(`runner-setup.sh` legt ihn wie das Red Team nach `/usr/local/lib/adminhelper-dev`, der Hook ruft diese Kopie), und
`harness-guard.sh` liest `harness-paths.txt` und `.vm/harness.off` aus `CLAUDE_PROJECT_DIR`, nicht relativ zu sich selbst;
die Runner-Allowlist verliert die Wege, ein Programm auszuführen oder zu schreiben, die ein Lesebefehl mitbringt —
`rg` (`--pre`), `git grep` (`-O`), `sed -n` (`e`, `w`) —, die eingebauten Werkzeuge Grep und Read ersetzen sie.
Tests, die der Builder schreibt und `verify.sh` ausführt, sind Code mit den Rechten des Runners: gewollt, die Grenze dort
ist der Nutzer (kein Credential, kein Push), nicht die Allowlist.

### T3 — `ledger-loop.sh`: Gerüst, Preflight, Ledger-Prüfung, Lane, Zustand  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/dev/harness-paths.txt, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7e61ce9f 2026-10-04T22:57:05+02:00
Review: approve (opus/xhigh; 6 nit) · round 2
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

### T4 — Task-Iteration: Bau-Session, `task-close --review auto`, Runde 2, Marker  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/dev/task-close.sh, scripts/tests/task_close_test.sh, scripts/dev/review-run.sh, scripts/tests/review_run_test.sh, docs/features/stufe-7a.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @26564c6d 2026-10-05T11:00:15+02:00
Review: approve (opus/xhigh; 2 nit) · round 2
Review-Verlauf: r1/r2 (request_changes, Funde behoben) auf Kevins Wort 2026-10-05 beiseitegelegt, frische Runde; Kosten r1 $4.13 · r2 $1.86 · frische r1 $2.57 (request_changes 0/3/2, behoben) · frische r2 im Review-Log (`review.sh log --ledger tasks/stufe-7a.md`).
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
Dazu (Aufsicht 2026-10-04, Kevin): R-0167 — eine Bau-Session darf kein approve vortäuschen können:
`task-close.sh` verweigert `--review none` und `--review verdict:`, wenn der Ledger-Kopf `Review: auto` trägt oder der
Lauf autonom ist, und `CLAUDE_BIN` gilt nur im Testmodus. R-0170 — `--review auto` vertraut den Dateien unter
`.ah-out/review/` nicht blind: ein selbst geschriebenes Verdict samt `.staged` darf über die Übernahme kein approve
liefern, gelöschte Runden-Dateien setzen die Runde nicht zurück, und Runden-Dateien eines früheren Ledgers mit gleichen
IDs zählen nicht; der Loop ist der einzige Aufrufer und führt die Runde selbst.
Abhängt von: T3
Abweichung: `task-close.sh` läuft aus der Lane, nicht aus dem Klon — es schließt den Checkout, in dem es liegt; vorher
prüft der Loop, dass kein Harness-Pfad der Lane von `origin/main` abweicht. Die Bau-Session bekommt
`--setting-sources user` und den `/build-task`-Text des Klons als Prompt statt `/build-task` als Befehl (Spec, „Je
Task“ 2). Das Aufräumen aus T5 ist schon hier gebaut, weil `[?]` nach Runde 2 und `[~]` es brauchen; T5 bringt die
Auslöser Timeout/Turns/Budget und den Stall mit byte-identischem Ledger. Aus dem Review (Runde 1): der Loop erkennt
Code der Session, der hinter ihm arbeitet (HEAD der Lane, ein Commit je Abschluss, der Klon, die Prüfsumme der CLI).

### T5 — Abbruch-Aufräumen und Stall  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ed65e18c 2026-10-05T11:48:54+02:00
Review: approve (opus/xhigh; 4 nit) · round 1
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
Abweichung: Den Scratch der Lane räumt der Loop mit den Prüfungen von `scratch.sh rm` selbst (direktes Kind, kein Link,
Marker), nicht über das Skript: das der Lane ist Code, den die Session ändern kann, das des Klons räumt nur seinen
eigenen Checkout. Dazu: eine Commit-Nachricht gilt nur für die Session, die sie schrieb — der Loop löscht sie vor
jeder Session, damit ein Abschluss mit Exit 2 die nächste nicht schließt.

### T6 — Lauf-Deckel, Nutzungslimit, Stopp-Klassen, Summary  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/dev/task-close.sh, scripts/tests/task_close_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @29f06642 2026-10-05T12:25:18+02:00
Review: approve (opus/xhigh; 3 nit) · round 1
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
Dazu (Aufsicht 2026-10-05, Entscheidung F zu Ende gedacht): Laufzeit und Lauf-Budget gelten auch zwischen den
Iterationen einer Task — ohne den alten Deckel „zwei Leerläufe“ liefe eine Task, deren Sessions das Ledger jedes Mal
ändern, sonst ohne Grenze; einen Deckel „N Sessions je Task“ gibt es nicht (wäre Kevins Entscheidung). Das
Lauf-Budget zählt die Reviewer-Läufe mit: `task-close.sh` druckt nach dem Reviewer `review cost_usd=<x> round=<n>`,
der Loop liest die letzte solche Zeile aus dem Close-Log, das er selbst anlegt (ein gescheiterter Reviewer-Lauf
druckt keine). Nutzungslimit: Wortlaut aus code.claude.com/docs/en/errors; wo `-p` ihn ausgibt, ist nicht
verifiziert — der Loop liest `result`, die Rohausgabe und stderr, nur bei einem Fehler-Ergebnis. Ebenso: 1M-Kontext
ohne Credits ⇒ `stop: infra` (Spec, Risiken); die Harness-Prüfung nach jeder Session, nicht erst vor dem Abschluss;
aus dem T5-Review die Prüfungen, dass weder `.ah-out` noch ein Marker ein Link ist, und der Kopfkommentar.

### T7 — Ledger-Ende: PR-Text und Übergabe als Bundle  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8eb9c48f 2026-10-05T12:52:43+02:00
Review: approve (opus/xhigh; 2 nit) · round 1
Änderung: Steht das Ledger nach der letzten Task auf `bereit`: `review.sh pr-body tasks/<slug>.md` nach
`<loop>/<slug>/pr-body.md`, bei `Heavy:` ≠ `none` mit dem Vermerk „Heavy offen — fährt die Aufsicht“; `git bundle create
<loop>/<slug>.bundle origin/main..feature/<slug>` plus `git bundle verify`; dann das nächste Ledger der Liste. Kein Push,
kein PR. Tests: Ledger durchgelaufen ⇒ `pr-body.md` und Bundle liegen; ein zweites Repo holt den Branch per `git fetch
<bundle> feature/<slug>:feature/<slug>` und hat dieselben Commits; `Heavy: linux-full` ⇒ Vermerk im PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T4
Abweichung: Ein Ledger ohne `Heavy:`-Zeile bekommt den Vermerk ebenfalls — offen ist, was niemand als `none`
geplant hat. Dazu (Aufsicht 2026-10-05, aus dem T6-Review): Kosten einer Session unter 0, NaN oder unendlich
zählen als 0 (sonst senken sie die Lauf-Summe oder blenden den Deckel); den Text des Nutzungslimits sucht der Loop in
`result` und stderr, die Rohausgabe nur, wenn sie kein JSON ist — im JSON stehen die verweigerten Befehle, die das
Modell schrieb.

### T8 — Stand sichtbar: `ledger-loop.sh status` und die Worker-Zeile im AH-STATUS  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @cafa4f74 2026-10-05T13:17:07+02:00
Review: approve (opus/xhigh; 3 nit) · round 1
Änderung: `session-status.sh:187`: statt „Worker: — (ab 7)“ liest der Hook `${AH_LOOP_STATE:-/srv/ah/loop/state.json}`,
wenn lesbar, nur als Datei (nie `git` in `/srv/ah`), und druckt „Worker: läuft T<k>/<n> tasks/<slug>.md · <$> · seit
<hh:mm>“ bzw. „Worker: stop: <klasse> <hh:mm>“ bzw. „Worker: —“; Texte gereinigt und gekürzt. `ledger-loop.sh status`
druckt dieselbe Zeile plus die letzten Summary-Zeilen. Tests: Zustandsdatei läuft, gestoppt, fehlt, kaputtes JSON (⇒
„Worker: ? (state.json unlesbar)“, kein Abbruch des Hooks), Steuerzeichen im Slug werden entfernt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T6
Abweichung: Der Hook rechnet die Zeile nicht selbst, er nimmt die erste Zeile von `ledger-loop.sh status` dieses
Checkouts (eine Stelle, die die Datei liest und reinigt). „seit“ ist der Start des Laufs, die Kosten sind die des
Laufs; `state.json` trägt dafür je Task `of` (Zahl der Tasks im Ledger). Ein gekillter Loop steht weiter als „läuft“
da: der Zustand sagt nur, was der Loop zuletzt schrieb.

### T9 — Red Team prüft die Bau-Session  [x]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @29549f77 2026-10-05T11:22:09+02:00
Review: approve (opus/xhigh; 3 nit) · round 1
Änderung: Abschnitt 5 (`runner-redteam.sh:338`) um die Bau-Session-Grenzen aus T2: statisch, ohne Modell, dass die
Runner-Settings Deny `Edit(./tasks/**)` tragen und die zwei Scratch-Allows; mit `claude_probe` (Budget ≤ 1 $, wie
heute): eine Session, die `tasks/<x>.md` per Umleitung ändern soll ⇒ `denied`; eine, die nacktes `mktemp -d` ausführen
soll ⇒ `denied`. `redteam_test.sh`: die neuen statischen Prüfungen gegen eine Settings-Kopie mit und ohne Deny; der
Verdikt-Pfad der neuen Proben über `--verdict` mit vorbereiteten Transkripten (denied/attempted/declined).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T10)
Abhängt von: T2
Beleg: Red Team nach #74 (Kevin, 2026-10-05, Runner-Klon bf9cee5e): 27 ok, 0 FAIL, 2 info (Push in ein selbst angelegtes Bare-Repo, dessen Grenze die Deny-Regel ist; secret-tool fehlt). Jetzt echt gemessen: „no session bus socket at /run/user/1001/bus“, „cannot enter /run/user/1000“, „the runner's Proxmox token works and sees pool adminhelper-ci“, „VM 100 (outside the pool) is refused by the API (403)“, „~/.claude/settings.json is byte for byte the reviewed runner-settings.json“ und die erweiterte git-Konfigprüfung (kein credential helper, extra header, askpass, ssh command, URL rewrite). Die Prüfungen aus T9 misst erst Kevins Handgriff 4 nach dem Merge.

### T10 — Doku: der Worker  [x]
Komponente: scripts · Dateien: AUTONOMOUS.md, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @47dc4db6 2026-10-05T13:50:22+02:00
Review: approve (opus/xhigh; 2 nit) · round 2
Änderung: `AUTONOMOUS.md` neuer Abschnitt „Der Worker (Stufe 7a)“: Start (Kevins tmux-Zeile), Ledger-Liste, Deckel und
Flags, Stopp-Klassen, `[?]`/`blockiert`, Übergabe per Bundle und warum nie `git` im Runner-Repo, Pilot. `DEVELOPMENT.md`:
Worker starten, `ledger-loop.sh status`, Bundle holen, Recovery (Lane schmutzig, `stop: infra`), Setup erneut nach
Settings-Änderung. `cicd.html` DE+EN: der Worker in der Ebenen-Übersicht. `CHANGELOG.md` unter Unreleased. Keine
CLAUDE.md-Änderung (Kevins Handarbeit, Spec).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md · DEVELOPMENT.md · docs/developer/cicd.html + docs/en/developer/cicd.html · CHANGELOG.md
Abhängt von: T1–T9
Abweichung: `cicd.html` hat keine eigene Ebenen-Übersicht; der Worker steht als eigener Abschnitt hinter den
Review-Prüfern, und deren `--review auto`-Liste nennt `--round` im autonomen Lauf und die Kosten-Zeile. Im
Runner-Abschnitt von `DEVELOPMENT.md` waren drei Sätze seit 7a falsch (Deny-Zeile zu `task-close.sh`, „kann ein `[x]`
schreiben“, die Liste der Modellproben); falsche Doku ist ein Bug, sie sind mitkorrigiert. Aus Runde 1: dazu der
root-eigene Guard (R-0164) in der Setup-Liste und bei den Setup-Auslösern, und der Satz „ab Stufe 7 braucht er den
Trust“ ist jetzt „nicht verifiziert, der Pilot misst“ — `--trust` deckt die Lanes nicht ab.

### T11 — Nachbesserung T9: Beweiskraft der Bau-Session-Proben  [x]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fc2aaf18 2026-10-05T14:37:16+02:00
Review: approve (opus/xhigh; 3 nit) · round 1
Änderung: Aufsicht 2026-10-05 aus den Nits des T9-Reviews: eine Probe, die aus dem falschen Grund grün oder rot wird,
beweist nichts. (1) Die Umleitungsprobe mit einem erlaubten Befehl (`cat … >> tasks/README.md`), damit nur die Prüfung
des Umleitungsziels ablehnen kann; dazu die Gegenprobe: dasselbe Muster auf ein erlaubtes Ziel geht durch bzw. ergibt
`attempted`. (2) Weicht die `mktemp`-Probe auf das erlaubte `scratch.sh new` aus, ergibt das kein falsches FAIL
(`redteam_changed` nimmt `.ah-out/scratch/` aus, oder die Probe räumt einen solchen Ordner auf). Der dritte Nit
(`claude_probe`-shift nur strukturell getestet) bleibt liegen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Interna des Red Teams; den Lauf beschreibt T10)
Abhängt von: T9
Abweichung zu (2): Die `mktemp`-Probe läuft aus einem eigenen Verzeichnis, nicht im Klon. `.ah-out/scratch/`
auszunehmen hielte nicht: legt `scratch.sh new` `.ah-out` erst an, ändert sich die ctime des Klon-Wurzelverzeichnisses,
und `redteam_changed` meldet sie. Im eigenen Verzeichnis gibt es kein `scratch.sh`, auf das die Session ausweichen
könnte. Beide Probenverzeichnisse (`--probe-dir`) tragen eine leere Harness-Liste, weil der Wächter eines autonomen
Laufs ohne Liste jeden Schreibzugriff verweigert — die Gegenprobe sähe sonst ihn statt der Regel.

### T12 — Nachbesserung T7: Handover nachholen  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, DEVELOPMENT.md, scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0e725d26 2026-10-05T15:04:27+02:00
Review: approve (opus/xhigh; 4 nit) · round 1
Änderung: Aufsicht 2026-10-05 aus dem T7-Review: Der Loop committet `bereit` vor dem Handover; scheitern danach
`pr-body` oder das Bundle (`stop: infra`), überspringt ein neuer Lauf das Ledger, und PR-Text und Bundle fehlen.
`setup_ledger` holt den Handover nach, wenn die Lane auf `bereit` steht und kein Bundle da ist; Test dazu. Dazu die
Testlücken aus T7: eine Session-Kosten `Infinity`, ein Ledger ohne `Heavy:`-Zeile (Vermerk im PR-Text), und der
NaN-Fall so, dass er auch unter gawk ohne den Schutz rot wird. Dazu (Aufsicht 2026-10-05) die Nits aus dem T8-Review:
der Kopfkommentar von `ledger-loop.sh` nennt die Summary, die `status` liest; der Kopf von `session-status.sh` nennt
`AH_LOOP_STATE`; `status` druckt höchstens zehn Summary-Zeilen, und `cost_usd` zählt nur endlich und im Bereich. Aus
dem T10-Review: `DEVELOPMENT.md` sagt nicht mehr, der Worker lese `.vm/active-task` (kein Skript liest die Datei).
Aus dem T11-Review (Aufsicht 2026-10-05): die Gegenprobe läuft nur nach einer abgelehnten Hauptprobe (sonst kostet sie
bis zu 1 $ ohne Aussage), der Kommentar zur `mktemp`-Probe sagt den Grund richtig herum, und der Kopf von
`redteam_test.sh` nennt `--pair` und `--probe-dir`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Korrektur an T7; den Worker beschreibt T10)
Abhängt von: T7

### T13 — Bau- und Review-Sessions ohne Proxmox-Token  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f83a132e 2026-10-05T14:13:11+02:00
Review: approve (opus/xhigh) · round 1
Änderung: Aufsicht 2026-10-05, vor dem Pilot: Sessions bekommen nur die Umgebung, die sie brauchen. `runner-env.sh`
exportiert neben dem Abo-Token (das Bau-Session und Reviewer brauchen) die `AH_PVE_*` aus `pve.env`; der Worker
braucht in 7a keinen Hypervisor (Heavy aus dem Loop ist 7b) und nimmt sie nach `runner-env.sh` aus seiner Umgebung,
sodass weder Bau-Session noch `task-close.sh`, Suite, Reviewer oder Fundament sie erben. Test: der Stub-`claude` und der
Stub-`task-close` schreiben die Namen ihrer Umgebungsvariablen in eine Datei; darin steht kein `AH_PVE_`, wohl aber
`CLAUDE_CODE_OAUTH_TOKEN`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Interna des Workers; `AUTONOMOUS.md` nennt die Grenzen der Session schon allgemein)
Abhängt von: T4

### T14 — Nachbesserung aus dem Branch-Review  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, docs/features/stufe-7a.md, AUTONOMOUS.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fdb882cd 2026-10-05T17:41:25+02:00
Review: approve (opus/xhigh; 4 nit) · round 1
Review-Verlauf: r1/r2 (request_changes, Funde behoben) nach Kevins Dauerauftrag vom 2026-10-05 beiseitegelegt, frische Serie; Kosten r1 $1.95 · r2 $1.73 · die frische Serie im Review-Log (`review.sh log --ledger tasks/stufe-7a.md`).
Änderung: Aufsicht 2026-10-05 aus dem `/code-review` über den Branch, je mit Test: (1) die Prüfsumme der CLI vor
ihrem ersten Aufruf im Preflight; (2) der Stand von `origin/main` nach dem Preflight-Fetch als feste SHA für
Harness-Vergleich, Merge in die Lane und Bundle; (3) ein Stopp `harness-modified` hinterlässt eine Marke beim Ledger,
und ein neuer Lauf baut dieses Ledger erst wieder, wenn Kevin sie entfernt hat; der nachgeholte Handover prüft die
Harness-Pfade der Lane; (4) eine Session ändert im Ledger nur ihre eigene Task (Kopf und andere Tasks bleiben
byte-gleich, sonst Aufräumen und `[?]`), und ein offenes `[?]` am Ende macht das Ledger `blockiert`, nie `bereit`;
(5) die Frage nach Runde 2 nennt nur Schwere, Datei und den Pfad des Verdicts im Loop-Ordner, nie den Text eines
Fundes (kein Review-Fund in einer versionierten Datei); (6) die drei Task-Deckel müssen größer als 0 sein. Dazu
(Entscheidung der Aufsicht): (7) ein Ergebnis „API Error“ oder eine Session ohne JSON ist `stop: infra`, die Task
bleibt offen — ein Ausfall soll nicht jedes Ledger der Liste blockieren; die Spec sagt es in einem Satz; (8)
unbekannte Kosten zählen mit dem Deckel: eine Session ohne JSON mit `--task-budget`, ein Reviewer-Lauf ohne
Kosten-Zeile mit dem Budget von `review-run.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/features/stufe-7a.md (der Satz zu (7))
Abhängt von: T12
