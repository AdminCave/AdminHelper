<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Sessions testen im Vordergrund und gezielt (R-0263) — Task-Ledger
Status: aktiv · Branch: harness/loop-verify-foreground · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-11 (kleines Fund-Paket aus R-0263, Harness-Paket Worker A aus Kevins Triage 2026-10-10; Lösung (a) Timeout-Variablen für claude -p und (b) gezielte Tests in der Session, die volle Suite fährt task-close; Bau erst nach flake-paket und team-rules oder mit main hinein; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0263 (Kurz-Ledger ohne Spec)
Heavy: none — Shell unter scripts/ und ein Skill-Text mit hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-11 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat R-0263 am 2026-10-10 in der Triage
angenommen; der Fund hat Vorrang, er hat Messlauf-3 gestoppt. Zeilenangaben origin/main@8e31cf71; beim Bau an Symbolen
orientieren.

Befund:
- In vier Sessions der Messläufe 2 und 3 lief der Verify-Lauf im Hintergrund. Danach wollte die Session warten
  (Monitor, `until … sleep`, `tail --pid`, `ps`), und das wurde verweigert. Die Session endete „wartend“, ohne
  Commit-Nachricht; in Messlauf-3 folgte `stall`.
- Dazu kamen Verweigerungen zusammengesetzter Befehle (`source .devenv.sh && cd apps/server && ruff …`,
  `review.sh docs-pairs; echo …; python3 …`): Die Allow-Liste prüft jeden Teil. `Bash(ruff:*)` steht schon in
  `runner-settings.json:82`.
- Ursache: Ein Befehl im Vordergrund hat in der Session höchstens 10 min (`BASH_MAX_TIMEOUT_MS`, Vorgabe 600000).
  Danach wandert er in den Hintergrund (Claude-Code-Doku „Tools reference“, Bash: „A command that starts in the
  foreground and then moves to the background, for example at its timeout, gets 30 minutes from the move“).
- Ein voller `verify.sh scripts --strict` dauert 10:20 min, gemessen am 2026-10-11 im Bau flake-paket. Ein Lauf mit
  Wartezeit an der py.lock dauert länger.

Entwurf:
- Der Loop gibt der Session für einen Befehl im Vordergrund so viel Zeit, wie die Session selbst hat (T1).
- `verify.sh scripts` kann gezielt einzelne Script-Tests fahren (T2).
- Der Aufgabentext verlangt: im Vordergrund testen, gezielt, ein Befehl je Aufruf. Die volle Suite fährt
  `task-close.sh` im Loop nach der Session ohnehin (T3).

### T1 — Der Loop gibt der Session für einen Befehl im Vordergrund die Zeit der Session  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3baf6102 2026-10-11T17:47:22+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Der Aufruf von `claude -p` (`ledger-loop.sh:788`) bekommt `BASH_DEFAULT_TIMEOUT_MS` und `BASH_MAX_TIMEOUT_MS` mit
  dem Wert `TASK_MINUTES · 60000` in der Umgebung. Laut Claude-Code-Doku („Environment variables“) sind beide in der
  Prozessumgebung wirksam.
- Ein Befehl im Vordergrund wandert damit nicht mehr vor dem Ende der Session in den Hintergrund; die äußere Grenze
  bleibt `timeout ${TASK_MINUTES}m`.
- Nicht in `runner-settings.json`: Die Datei trägt keinen `env`-Block (hooks_test).
- Test in `ledger_loop_test.sh`: Die Fake-CLI hält die Werte fest. Sie müssen gleich `TASK_MINUTES · 60000` sein,
  auch bei `--task-minutes 7`.
Rot vorher: Die Session bekommt keine der beiden Variablen.
Beweis:
- `~/.cache/ah-builder/loop/messlauf-2/T1.s1.json`, `T2.s1.json` und `loop-kleinpaket-2/T1.s1.json`,
  `T1.s2.json`, je `permission_denials`: Monitor `while kill -0 …`, `timeout 540 tail --pid=…`, `ps -o … -p …`,
  `until [ -s <task output> ]; do sleep 5; done`.
- Das `result` endet jeweils mit dem Warten auf den Lauf („Ich warte auf die Meldung, dass die Suite fertig ist“).
Dedup-Key: ref:scripts:runner-settings.json:loop-wait-and-ruff
HEAD: 8e31cf71
Semantik: `AUTONOMOUS.md:242–246` „**Je Task** eine frische Bau-Session … Die Session baut eine Task, testet mit
`verify.sh` und hinterlässt eine Commit-Nachricht“. Der Test der Session muss in der Session zu Ende kommen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Kopf von ledger-loop.sh nennt die Variablen)

### T2 — `verify.sh scripts --strict -- <test…>` fährt nur diese Script-Tests  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6d393f8e 2026-10-11T18:08:37+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `scripts_block` (`run.sh:597`) nimmt `AH_ARGS` als Liste von Test-Namen, wenn es gesetzt ist; `verify.sh` reicht
  `-- <args>` dorthin durch. Ein Name, der nicht in `AH_SCRIPT_TESTS_DEFAULT` steht, ist ein Fehler mit Exit 2 und
  Meldung. Ohne Argumente läuft die Liste wie heute.
- So kann eine Session den Test ihrer Task in wenigen Minuten im Vordergrund fahren. Gemessen braucht
  `ledger_loop_test` allein 130 s, die ganze Liste 10:20 min.
- DEVELOPMENT.md (`:248`, die Zeile zu `verify.sh … [-- <args>]`) nennt das für `scripts`.
- Test in `run_flags_test.sh`, mit Fixture-Tests:
  - `-- a_test` fährt nur `a_test`;
  - ein unbekannter Name gibt Exit 2;
  - ohne Argumente laufen alle.
Rot vorher: `-- a_test` fährt alle Tests der Liste.
Beweis: origin/main@8e31cf71 · `scripts_block` (`run.sh:597–604`) liest nur `AH_SCRIPT_TESTS`, `AH_ARGS` nicht.
Ein Env-Präfix (`AH_SCRIPT_TESTS=x bash …`) trifft keine Allow-Regel (CLAUDE.md §7).
Dedup-Key: ref:scripts:runner-settings.json:loop-wait-and-ruff
HEAD: 8e31cf71
Semantik: `DEVELOPMENT.md:248` `bash scripts/dev/verify.sh <komponente> … [-- <args>]`: Die Argumente gelten der
Suite der Komponente. Für `scripts` bewirkten sie bisher nichts.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (eine Zeile)

### T3 — `/build-task`: im Vordergrund, gezielt, ein Befehl je Aufruf  [x]
Komponente: scripts · Dateien: .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7a4ee785 2026-10-11T18:21:30+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Schritt 4 („Testen“, `SKILL.md:31`) und Schritt 6 („Commit-Nachricht“, `:41`) sagen:
- Tests laufen im Vordergrund, mit einem `timeout`, der den Lauf trägt. Der Loop erlaubt bis zum Ende der Session
  (T1).
- Nie `run_in_background`, nie warten mit Monitor, `sleep`, `tail --pid` oder `ps`: Das verweigern die Settings.
- Gezielt testen: `verify.sh <komponente> --strict -- <test>`, für `scripts` der Name des Script-Tests (T2). Die volle
  Suite und das `Verify:` der Task fährt `task-close.sh` im Loop nach der Session.
- Die Commit-Nachricht folgt, wenn der gezielte Lauf grün ist.
- Ein Befehl je Aufruf, ohne `source`, `cd`, `;`, `&&`, `|`: Die Allow-Liste prüft jeden Teil. Ruff geht direkt
  (`ruff check <datei>`, `ruff format --check <datei>`).
- Der Abschnitt „build-task“ in `skill_consistency_test.sh` prüft:
  - der Text nennt „Vordergrund“ und verbietet `run_in_background` und das Warten;
  - jeder Befehl, den der Text vorgibt, trifft eine Allow-Regel (die bestehende Prüfung `build_task_calls`/`_findings`
    deckt die neuen Beispiele mit ab);
  - eine Fixture mit `run_in_background` im Text fällt.
Rot vorher: Die neue Prüfung fällt auf main, weil der Text weder „Vordergrund“ nennt noch den Hintergrund verbietet.
Beweis: wie T1; dazu die Verweigerungen `source .devenv.sh && cd apps/server && ruff format --diff …; ruff check …`
und `bash scripts/dev/review.sh docs-pairs; echo rc=$?; python3 scripts/dev/doc-smoke.py --help`.
Dedup-Key: ref:scripts:runner-settings.json:loop-wait-and-ruff
HEAD: 8e31cf71
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Skill-Text ist die Anleitung)
Abhängt von: T1, T2

### T4 — Nachbesserung aus dem Review am Ende: ein gezieltes Verify: ersetzt die Suite nicht (R-0263)  [ ]
Komponente: scripts · Dateien: .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh, scripts/dev/ledger-loop.sh, scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Änderung: Angelegt 2026-10-11 aus dem Review am Ende (Opus, `request_changes`: ein belegter Fund, fünf nits).
- Schritt 4 von `/build-task` (T3) sagte, `task-close.sh` fahre die volle Suite. Es fährt aber das `Verify:` der Task,
  und ein gezieltes `Verify:` (`… server --strict -- tests/test_hooks.py`) fährt nur diesen Test. Eine Regression in
  einem anderen Test der Komponente käme grün durch.
- Schritt 4 sagt jetzt: Ist das `Verify:` gezielt (`-- …`), fährt die Session vor der Commit-Nachricht einmal
  `bash scripts/dev/verify.sh <komponente> --strict` im Vordergrund. Seit T1 trägt der Loop das zeitlich.
  `skill_consistency_test` prüft, dass Schritt 4 diesen Aufruf nennt; mit dem Text von T3 fällt die Prüfung.
- Dazu nits aus demselben Review:
  - Der Kommentar in `ledger-loop.sh` nennt die Grenzen des Bash-Werkzeugs richtig: 2 min ohne `timeout`, höchstens
    10 min.
  - Der Skill sagt, die Settings verweigern das Warten; `run_in_background` selbst prüft keine Regel.
  - `run.sh` liest die Namen nach `--` unter `set -f`: `-- '*'` wird nicht gegen das Repo expandiert, die Meldung nennt
    `*` (ein Fall in `run_flags_test`).
  - Für `agent` nennt Schritt 4 `-- -run <Test>`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Skill-Text ist die Anleitung)
Abhängt von: T3
