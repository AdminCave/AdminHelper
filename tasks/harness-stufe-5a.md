<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 5a — Die Roadmap als Skript — Task-Ledger
Status: aktiv · Branch: harness/stufe-5a · Commit-Granularität: pro Task · Review: pro Task (Sonnet, 10 min) · Modell: Opus
Spec: docs/features/harness-stufe-5.md (Roadmap R-0008, Teil 5a)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — nur `scripts/dev/`, `scripts/tests/`, ein Skill und Doku; `heavy.sh` wird hermetisch getestet (`heavy_test.sh`).
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: —

Tests arbeiten **nie** auf `tasks/private/ROADMAP.md`, sondern auf Fixture-Kopien in einem Temp-Verzeichnis:
`roadmap.py` nimmt den Pfad über `--file` oder `AH_ROADMAP`, Default `tasks/private/ROADMAP.md`.

### T1 — `roadmap.py` liest und lintet  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py (neu, SPDX), scripts/dev/tests/test_roadmap.py (neu, SPDX), scripts/tests/run.sh, scripts/tests/run_flags_test.sh, DEVELOPMENT.md, scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @a3bf1d97 2026-09-25T08:48:30+02:00
Review: approve (sonnet, Runde 2 nach runner-setup-Fix)
Änderung:
- **Parser:** Er liest Abschnitte, Tabellenzeilen mit genau zehn Spalten und den Kopf. Der Rest der Datei wird unverändert durchgereicht; Prosa, „Als Nächstes“ und Leerzeilen bleiben byte-gleich.
- **`lint` meldet:**
  - doppelte IDs;
  - unbekannte Status (`geparkt` und `erledigt` als Alias melden);
  - Zeilen im falschen Abschnitt (Zuordnung laut Spec);
  - Zeilen mit falscher Spaltenzahl;
  - einen doppelten `Dedup-Key:` unter offenen Zeilen;
  - einen WIP-Kopf, der nicht zu den Zeilen passt.

  Das Ergebnis ist Exit 0 bei sauber, 1 bei Funden. Die Ausgabe hat eine Zeile je Fund mit ID und Grund.
- **Neuer run.sh-Schritt `dev-pytest`** unter dem Key `scripts` (`python3 -m pytest scripts/dev/tests -q`), in `AH_REQUIRED_DEFAULT`. Er braucht keine Abhängigkeit außer pytest aus dem gemeinsamen Venv.
- **Tests:**
  - Rundlauf ohne Änderung ist byte-gleich.
  - Jede Fund-Art hat eine eigene Fixture.
  - Eine Fixture im Stil der heutigen Datei mit R-0047 doppelt und Zeilen im Archiv muss genau diese Funde melden.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (roadmap.py, Schritt dev-pytest)

### T2 — Schreiben mit Sperre: `add`  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @2c3c62c4 2026-09-25T09:10:29+02:00
Review: approve (sonnet, Runde 2 nach atomarer Wiederherstellung)
Änderung: `add --class --title --source [--proof] [--dedup-key] [--ledger]` legt eine `neu`-Zeile an. Die ID ist max + 1 über alle Zeilen, der Dedup-Key steht als Token in „Quelle / Beweis“.
- **Jede Schreiboperation (auch T3):**
  - läuft unter `flock` auf `<datei>.lock`;
  - schreibt `.bak`;
  - prüft die Zeilenzahl (vorher + erwartete Änderung = nachher, sonst Abbruch und `.bak` zurück);
  - hält die 5-s-Regel ein: Wurde die Datei in den letzten 5 s außerhalb des Skripts geändert, verweigert es. Die mtime wird gegen die letzte eigene Schreibmarke geprüft.
  - macht einen lokalen Commit im Repo der Datei (`roadmap: <verb> <id>`), ohne Push.
- **Regeln:**
  - Deckel: 20 `neu`-Zeilen. Beim 21. verweigert `add` mit Exit 3.
  - Ein bekannter offener Dedup-Key wird verweigert (Exit 4, nennt die ID).
- **Tests:**
  - Parallele `add`-Aufrufe (zwei Prozesse) ergeben zwei verschiedene IDs.
  - Weitere Fälle: Deckel, Dedup, 5-s-Regel, Zeilenzahl-Invariante mit absichtlich kaputter Schreibfunktion.
  - Commit im Fixture-Git-Repo.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T8)
Abhängt von: T1

### T3 — `status`, `approve`, und der Abschnitt folgt dem Status  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @188ff332 2026-09-25T09:31:26+02:00
Review: approve (sonnet, Runde 2 nach Alias-Fix)
Änderung:
- `status <id> <wert>` setzt den Status und verschiebt die Zeile in den Abschnitt, der zum Status gehört (Tabelle laut Spec). Zeilen, die länger als 30 Tage `abgeschlossen` sind, wandern beim nächsten Schreiben ins Archiv.
- `approve <id> [--revoke]` ist die Kurzform für `freigegeben` bzw. zurück auf `geplant`.
- Der WIP-Kopf wird bei jedem Schreiben neu gerechnet.
- Ungültige Übergänge verweigert das Skript mit Exit 2, etwa `abgeschlossen` → `neu`.
- Tests: jeder Übergang, Verschieben zwischen Abschnitten, Archiv-Grenze mit festem Datum und neu gerechneter Kopf.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T8)
Abhängt von: T2

### T4 — `show`, `next`, `sync`, `stats` (schlank)  [ ]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py
Änderung:
- `show [id]`: eine Zeile oder die Übersicht je Abschnitt.
- `next [--status freigegeben] [--exclude-components …]`: die nächste Zeile nach Klasse (SEC > REG > REL > BUG > FEAT > REF > IDEE), dann nach Reihenfolge der Zeilen.
- `sync`: `gh pr list --state merged` → Zeilen mit PR-Nummer werden `abgeschlossen`. Am Ende druckt es den Push-Befehl für das private Repo, führt ihn aber nicht aus.
- `stats`:
  - Tasks/Tag aus `git log -p -- tasks/*.md`;
  - Kevin-min/PR aus der Spalte;
  - Wartezeit je Zustand aus der git-Historie der Datei;
  - Dedup- und Stale-Quote.

  `$/Task` gibt es nicht (Stufe 7).
- Tests: Die Reihenfolge von `next` stimmt mit einer Fixture überein. `sync` läuft mit einem gefälschten `gh` im PATH. `stats` rechnet auf einem Fixture-Git-Repo mit drei Commits.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T8)
Abhängt von: T3

### T5 — `heavy.sh` schreibt über `roadmap.py add`  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung:
- `roadmap_append` (heavy.sh:582–606) wird zu einem Aufruf `roadmap.py add` mit Klasse, Titel, Quelle und Dedup-Key.
  - REG-Schlüssel: `reg:<schritt>`.
  - REL-Schlüssel aus dem Audit: `rel:deps-audit`.
- Die bisherige `seen.md`-Sperre bleibt, der Dedup-Key ersetzt sie nicht. `seen.md` sperrt 30 Tage auch nach dem Schließen, der Key nur, solange eine Zeile offen ist.
- Den `commit_private`-Commit gibt es weiterhin, aber ohne ROADMAP.md, denn die committet `roadmap.py` selbst.
- Tests: `heavy_test.sh` prüft, dass eine REG-Zeile über das Skript entsteht und ein zweiter roter Lauf keine zweite Zeile anlegt. Gegenprobe gegen den alten Stand.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T8)
Abhängt von: T2

### T6 — Der Status-Hook zeigt den ganzen Plan und die Deckel  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/hooks_test.sh
Änderung:
- Die Roadmap-Zeile im AH-STATUS-Block zeigt alle Punkte von „Als Nächstes“ statt nur vier. Punkte mit mehr als einer Zeile werden auf die erste Zeile gekürzt.
- Die WIP-Deckel kommen aus `roadmap.py show --wip` und werden an den Zahlen aus CLAUDE.md gemessen: `aktiv` 1 · `bereit` 2 · `pr` 3 · `neu` 20. Ist ein Deckel erreicht, steht dort `Warnung:` (Warn-Trigger 3).
- Fehlt `roadmap.py` oder scheitert es, zeigt die Zeile den Fehler, nicht nichts.
- Tests: fünf Punkte ⇒ fünf Zeilen; ein erreichter Deckel ⇒ Warnung; ein kaputtes Skript ⇒ Fehlermeldung.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T8)
Abhängt von: T3

### T7 — Der Skill `/roadmap`  [ ]
Komponente: scripts · Dateien: .claude/skills/roadmap/SKILL.md (neu, SPDX-Kommentar)
Änderung:
- `/roadmap` rendert `roadmap.py show` knapp: Als Nächstes, In Arbeit mit Deckeln, Neu mit Anzahl.
- `/roadmap triage` führt per `AskUserQuestion` durch die `neu`-Zeilen, 2–4 je Runde, mit einer Empfehlung zuerst:
  - annehmen → `roadmap.py status <id> geplant`, dann `/feature-plan --kurz <id>` vorschlagen;
  - ablehnen → `status … abgelehnt` mit Grund;
  - zurückstellen;
  - bündeln → `--bundle`-Vorschlag;
  - REG → Haken „Regression bestätigt“.
- Jede Änderung läuft nur über `roadmap.py`, nie als Edit an der Datei.
- Test: keiner, es ist Skill-Text. Nachweis ist ein Trockenlauf über die Fixture aus T1, der im Ledger festgehalten wird.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T8)
Abhängt von: T4

### T8 — Doku  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, AUTONOMOUS.md, CHANGELOG.md
Änderung:
- `DEVELOPMENT.md`: `roadmap.py`, die Verben mit einem Satz je Verb, die Schreibregeln (flock, `.bak`, 5 s, Deckel) und `AH_ROADMAP` für Tests.
- `AUTONOMOUS.md`: Die Roadmap wird über `roadmap.py` gepflegt, „Als Nächstes“ bleibt von Hand, `/roadmap triage`.
- `CHANGELOG.md`: Eintrag unter „Unreleased“, Abschnitt „Changed“ (Entwickler-Werkzeuge).
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md · AUTONOMOUS.md · CHANGELOG.md
Abhängt von: T7

## Abschluss (nach T8, vor dem PR)

1. `roadmap.py lint --file tasks/private/ROADMAP.md` auf der echten Datei. Die Funde gehen als Liste an die Aufsicht.
2. Bereinigung mit den eigenen Verben, bei der Aufsicht abgestimmt, jeder Schritt ein lokaler Commit im privaten Repo:
   - R-0047 doppelt: Die jüngere Zeile bekommt eine neue ID, Verweise werden nachgezogen.
   - Zeilen im falschen Abschnitt werden per `status` neu gesetzt, dabei wandern sie.
   - Der WIP-Kopf wird neu gerechnet.
3. Danach muss `lint` sauber sein. Der Diff des privaten Repos kommt zur Ansicht in die PR-Beschreibung, gekürzt auf IDs.
4. Live-Probe: eine Wegwerf-Zeile durch alle Zustände (`add` → `geplant` → `approve` → `aktiv` → `bereit` → `pr` → `abgeschlossen`), je Schritt ein Commit, danach `status … abgelehnt`, damit sie nichts zählt.
