<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket status-classes: status zeigt nur bekannte Stop-Klassen und Muster und liest begrenzt (R-0338) — Task-Ledger
Status: erledigt · Branch: harness/status-classes · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage und Reihenfolge Kevin 2026-10-13; Bau nach dem Merge von status-builder; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0338 (Kurz-Ledger ohne Spec)
Heavy: none — ledger-loop.sh status und session-status.sh mit ledger_loop_test und session_status_test (Fixture-Dateien, Shims); nur Platzhalter, kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/status-builder — beide ändern session-status.sh und session_status_test.sh, und dessen
Builder-Fälle ziehen hier mit; erst nach dessen Merge bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeilen am 2026-10-13 angenommen.
Zeilenangaben origin/main@75ed3e09; beim Bau an Symbolen orientieren.

Vorab geprüft:
- Die erste Zeile von `ledger-loop.sh status` geht als „Worker:“ (Runner) und seit status-builder als „Builder:“ in
  jeden AH-STATUS-Block. Die Werte aus state.json werden heute nur gesäubert (druckbar, gekürzt), nicht geprüft.
- Die Stop-Klassen, die der Loop selbst schreibt (ledger-loop.sh, origin/main@75ed3e09):
  - als feste Werte `infra` (:311), `harness-modified` (:451) und `ledger-leer` (:1110);
  - über `stop_run` die Kappen aus `over_cap` (:325–336): `max-hours`, `max-budget`, `max-tasks`, `kevin-queue`;
  - dazu `usage-limit` (:981).
- Muster aus dem Code:
  - Task-ID `[A-Za-z0-9._-]+` (ledger.sh `check_id` :54–58, ledger-loop.sh `next_task` :625);
  - Ledger `tasks/<slug>.md` mit Slug `[a-z0-9][a-z0-9-]*`, das Zeichensatz-Muster von lane.sh.
- Tests nur mit Platzhaltern (`plchold`).

### T1 — status zeigt nur bekannte Stop-Klassen, Task-IDs und Ledger-Namen  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3a42a523 2026-10-13T08:11:17+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `ledger-loop.sh status` (:143ff.):
  - `stop` erscheint nur, wenn es eine der acht Klassen oben ist, sonst als `?`.
  - Die Task-ID nur im Muster `[A-Za-z0-9._-]{1,20}`, der Ledger-Name nur als `tasks/<slug>.md`, die Schlüssel unter
    `ledgers` nur als Slug. Alles andere wird `?`.
  - Das gilt für Runner und Builder gleich, weil beide dieselbe Funktion lesen.
  - `stop_reason` und die Summary-Zeilen bleiben, wie sie sind (gesäubert). Sie stehen nur in der Ausgabe von `status`,
    nicht im AH-STATUS-Block.
- Die Klassen stehen einmal im Skript, als Menge. Ein Test in ledger_loop_test liest aus dem Quelltext jede Klasse, die
  der Loop schreibt (`s["stop"] = "…"`, die ersten Wörter von `over_cap`, die Literale von `stop_run`), und prüft, dass
  die Menge sie enthält. Eine neue Klasse ohne Eintrag wird so rot.
- Fälle, Platzhalter:
  - ledger_loop_test:
    - eine unbekannte Stop-Klasse mit Freitext ergibt `Worker: stop: ? <zeit>`, und der Freitext erscheint nicht;
    - eine Task-ID mit Leerzeichen und ein Ledger-Name außerhalb des Musters ergeben `?`;
    - ein Schlüssel unter `ledgers` mit Steuerzeichen ergibt `?`.
  - Der bestehende Fall :956–959 (`stop: infra[31m`, `evil]0;t`) erwartet `?`. Das ist eine Shell-Prüfung, für
    diff-scan keine Assertion.
  - session_status_test:
    - Der Runner-Fall mit Steuerzeichen im Ledger-Namen erwartet `?` statt des gesäuberten Namens.
    - Das Builder-Fixture `kappe` wird zu einer bekannten Klasse.
    - Ein Builder-Fall mit Freitext in `stop` ergibt `stop: ?`.
Rot vorher: Auf main zeigt `status` eine Stop-Klasse `plchold plchold plchold` wörtlich (gekürzt auf 40 Zeichen).
Beweis:
- origin/main@75ed3e09, ledger-loop.sh :179 `print("Worker: stop: %s %s" % (clean(stop, 40), …))`.
- Fund: Review status-builder, Worker A, 2026-10-13.
HEAD: 75ed3e09
Semantik:
- AUTONOMOUS.md :284 (die erste Zeile von `status` steht als „Worker:“ im AH-STATUS).
- Die Stop-Klassen im Kopf von ledger-loop.sh (:88ff., „stop“ in state.json).
- Unter docs/ gibt es keine Stelle zu ledger-loop.sh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; DEVELOPMENT.md nennt die Klassen schon)

### T2 — status liest state.json und Summary nur als reguläre Dateien, begrenzt; worker_line ebenso (R-0338)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ca3dee4a 2026-10-13T08:30:51+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `ledger-loop.sh status`:
  - liest state.json (:154, :171) und die neueste `summary-*.md` (:200) nur, wenn sie reguläre Dateien sind;
  - liest höchstens 1 MiB beziehungsweise 64 KiB;
  - schreibt die erste Zeile mit `flush=True`, bevor es die Summary liest.
  - Ist state.json keine reguläre Datei, ist die erste Zeile `Worker: ? (state.json unlesbar)`. Eine Summary, die keine
    reguläre Datei ist, wird übergangen.
- session-status.sh `worker_line` (:193–198), der Runner-Pfad:
  - liest nur eine reguläre Datei (`-f`);
  - läuft unter `timeout 3` statt 10, wie die Builder-Zeile.
  - Der SessionStart-Hook hat seit #143 selbst 10 s, und `worker_line` allein durfte sie bisher ganz verbrauchen.
- Fälle:
  - ledger_loop_test:
    - state.json als FIFO, unter einem äußeren Zeitlimit;
    - eine FIFO als Summary neben einer gültigen state.json: Die erste Zeile kommt;
    - eine state.json über 1 MiB ergibt `?`.
  - session_status_test: state.json des Runners als FIFO; der Hook endet unter 4 s mit `Worker: ?` oder `—`.
Rot vorher: Auf main hängt `status` an einer FIFO als state.json bis zum Zeitlimit des Aufrufers.
Beweis:
- origin/main@75ed3e09, ledger-loop.sh :154 `[ -r "$STATE" ]`, :171 `json.load(open(sys.argv[1]))`, :200
  `open(sums[-1], errors="replace").read()`.
- session-status.sh :196 `timeout 10`.
- Fund: Review status-builder (Runde 1 und 2), Worker A, 2026-10-13.
Dedup-Key: ref:scripts:ledger-loop.sh:status-unbounded-read
HEAD: 75ed3e09
Semantik: session-status.sh, Kopf: „a SessionStart hook that fails or blocks would break every session“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — Nachbesserung aus dem Review am Ende: ein stop vom falschen Typ, der Synchron-Test, der FIFO-Summary-Fall  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, scripts/tests/session_status_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0a7f0c68 2026-10-13T09:37:10+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Review am Ende (Opus, `request_changes`: ein belegter Fund, zwei nits).
- T1 prüfte `stop in STOP_CLASSES` ohne Typprüfung.
  - Ein `stop` als Liste oder Objekt warf einen `TypeError`, und `status` gab gar nichts aus.
  - Neu: nur ein String aus der Menge zählt, alles andere ist `?`. Dazu ein Fall `{"stop": ["infra"]}`: `Worker: stop: ? ?`,
    kein Traceback.
- nit: Der Synchron-Test der Klassen fand `stop_run` nur mit einem Bindestrich im Namen und ohne Anführungszeichen.
  - Neu: Das Muster nimmt auch ein Wort ohne Bindestrich und eine Klasse in Anführungszeichen.
- nit: Der FIFO-Summary-Fall in session_status_test beschrieb noch das Verhalten vor T2.
  - Neu: Er erwartet die volle Builder-Zeile und eine Laufzeit unter 4 s.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T2
