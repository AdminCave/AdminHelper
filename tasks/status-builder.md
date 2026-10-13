<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket status-builder: AH-STATUS zeigt einen Lauf im Builder-Profil (R-0256) — Task-Ledger
Status: bereit · Branch: harness/status-builder · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0256, Triage Kevin 2026-10-09; nur die Stop-Klasse, kein freier stop_reason; Bau nach dem Merge von status-guard; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0256 (Kurz-Ledger ohne Spec)
Heavy: none — session-status.sh mit session_status_test (Fixture-Repo, Fixture-Builder-Verzeichnis, tmux-Shim); kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/status-guard (PR #140) — beide ändern session-status.sh und session_status_test.sh; erst nach
dessen Merge bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-09 angenommen (Schritt 6 des
Team-Plans, Fragen und Bericht). Zeilenangaben origin/main@710b68a2; beim Bau an Symbolen orientieren.

Vorab geprüft:
- AH-STATUS (session-status.sh, `worker_line` :193–198) liest nur `${AH_LOOP_STATE:-/srv/ah/loop/state.json}`, den
  Zustand des Runners.
- Ein Lauf im Builder-Profil, das Team unter Kevins UID, steht woanders, und der Block zeigt ihn nicht. Er hinterlässt:
  - `${AH_BUILDER_DIR:-~/.cache/ah-builder}/loop/state.json`;
  - die tmux-Sitzung `ah-builder`;
  - `loop/builder.done` mit `rc=<n>` (ledger-loop.sh :109–126).
- `ledger-loop.sh status --state <datei>` liest jede state.json. Seine erste Zeile säubert jeden Wert (`clean`: nur
  Druckbares, gekürzt) und zeigt Stand, Kosten und Stop-Klasse. Der Hook nutzt sie heute schon für den Runner.
- Die Tests dürfen weder das echte `~/.cache/ah-builder` noch eine echte tmux-Sitzung sehen: Fixture-Verzeichnis über
  `AH_BUILDER_DIR`, ein tmux-Shim im Shim-Verzeichnis des Tests.

### T1 — AH-STATUS zeigt einen Lauf im Builder-Profil  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @aba3ebb7 2026-10-13T05:39:27+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Neu: Nach Zeile 4 schreibt der Hook eine Zeile „Builder: …“, aber nur, wenn das Builder-Profil eine Spur hat.
  - **Stand und Kosten:** die erste Zeile von `ledger-loop.sh status --state <AH_BUILDER_DIR>/loop/state.json` ohne
    das `Worker: `. Das ist dieselbe gesäuberte Zeile wie beim Runner. Läuft der Loop, zeigt sie Task, Kosten und Start;
    ist er gestoppt, Stop-Klasse und Zeit.
  - **Laufende Sitzung:** `(tmux ah-builder)`, wenn `tmux has-session -t =ah-builder` gelingt, mit Zeitlimit.
  - **Ende:** `· fertig rc=<n>`, wenn `loop/builder.done` genau `rc=<Ziffern>` trägt. Jede andere Zeile der Datei zeigt
    der Hook nicht.
  - Ohne state.json, Sitzung und builder.done gibt es keine Zeile.
  - Kein Wert aus Dateien des Loops erscheint ungefiltert. Der Hook liest keine weitere Datei des Builders, nicht
    `home/` und nicht die Logs.
- Fälle in session_status_test:
  - `AH_BUILDER_DIR` zeigt auf ein Fixture-Verzeichnis, ein tmux-Shim antwortet per Umgebungsvariable.
  - Ohne Spur keine Zeile; die bestehenden Zeilen bleiben, wie sie sind.
  - Laufend: `Builder: läuft T2/5 tasks/x.md · 1,20 $ · seit …`. Gestoppt: `Builder: stop: <klasse> <zeit>`.
  - Mit Sitzung erscheint der Zusatz `(tmux ah-builder)`. Mit `builder.done` = `rc=1` erscheint `· fertig rc=1`; eine
    builder.done mit anderem Inhalt zeigt nichts davon.
  - Ein Steuerzeichen in state.json erscheint nicht (wie der Fall :194 beim Runner).
Rot vorher: Auf main zeigt der Block für ein Fixture-Builder-Verzeichnis mit laufendem Loop keine Zeile.
Beweis:
- origin/main@710b68a2, session-status.sh :194 `local f="${AH_LOOP_STATE:-/srv/ah/loop/state.json}"`.
- Fund: Bau 4b, harness/team-4b-loop-profile@591afaa0.
Dedup-Key: ref:scripts:session-status.sh:builder-loop
HEAD: 710b68a2
Semantik:
- DEVELOPMENT.md :1154 „Die erste Zeile ist die Worker-Zeile des AH-STATUS“.
- AUTONOMOUS.md :284 (die erste Zeile von `status` steht als „Worker:“ im AH-STATUS) und :302–304
  (`status --profile kevin` liest den Stand des Builders).
- Unter docs/ gibt es keine Stelle zu session-status.sh.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md :1229–1230 (Builder-Profil). Ein Satz: Ein Lauf im Builder-Profil steht als Zeile „Builder:“ im
AH-STATUS, mit Stand, Kosten, laufender Sitzung und Exit-Code.

### T2 — Nachbesserung aus dem Review am Ende: der Hook hängt an keiner Datei des Builders  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b70c88aa 2026-10-13T06:04:35+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Review am Ende (Opus, `request_changes`: ein belegter Fund, vier nits).
- Der Hook las `builder.done` mit grep ohne Zeitlimit und prüfte nur `-r`.
  - Ist die Datei eine FIFO oder ein Symlink auf ein Gerät, blockiert grep, und jede Session wartet ohne AH-STATUS.
  - Für `state.json` gilt dasselbe im Kleinen: 10 s bis zum `timeout`.
  - Neu: Beide Dateien werden nur gelesen, wenn sie reguläre Dateien sind (`-f`), und grep läuft unter
    `timeout 5`.
- nits:
  - `${HOME:-}` statt `$HOME` unter `set -u`.
  - `AH_BUILDER_DIR` kommt in die Liste der Variablen im Kopf.
  - Kommentar und DEVELOPMENT.md sagen „zeigt nichts weiter“ statt „liest nicht“, denn `ledger-loop.sh status` öffnet
    auch die neueste Summary.
  - Tests:
    - der Zweig ohne state.json (nur Sitzung, nur builder.done);
    - eine mehrzeilige builder.done;
    - ein tmux-Shim, der den Sitzungsnamen `=ah-builder` prüft;
    - eine FIFO als builder.done und als state.json, bei der der Hook unter einem äußeren Zeitlimit mit 0 endet.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, der Satz aus T1
Abhängt von: T1

### T3 — Nachbesserung aus Runde 2: jeder Lesezugriff des Builders bleibt unter dem Budget des Hooks  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @bd09f150 2026-10-13T06:50:33+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Re-Review von T2 (Opus, `request_changes`: ein belegter Fund, drei nits).
- `ledger-loop.sh status` liest neben state.json auch die neueste `summary-*.md`, ohne Prüfung auf reguläre Datei.
  - Eine FIFO dort hielt den Hook 10 s fest, und der SessionStart-Hook hat seit #143 selbst nur 10 s.
  - Die Ursache in `status` behebt R-0338 im nächsten Paket.
  - Hier: Der Builder-Status läuft unter `timeout 3` statt 10. tmux und builder.done bekommen je `timeout 2`.
  - Ein hängender Builder kostet so eine Zeile, nicht den Block.
- builder.done wird nur bis 4096 Byte gelesen (`head -c 4096`), denn grep puffert eine lange Zeile ganz.
- Kommentar und DEVELOPMENT.md sagen, was stimmt: Der Hook prüft state.json und builder.done auf reguläre Dateien, und
  jeder Lesezugriff hat ein kurzes Zeitlimit.
- Tests:
  - eine FIFO als `summary-*.md` neben einer gültigen state.json;
  - die FIFO-Fälle prüfen jetzt auch die Laufzeit;
  - „nothing else“ prüft, dass `rc=8` nicht erscheint;
  - ein `rc=` hinter 4096 Byte erscheint nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, der Satz aus T1
Abhängt von: T2
