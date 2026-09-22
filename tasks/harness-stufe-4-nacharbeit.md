<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 4 — Nacharbeit aus der T11-Verifikation — Task-Ledger
Status: geplant · Branch: harness/stufe-4-nacharbeit · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: tasks/harness-stufe-4.md (Anhang T11) — kein eigenes Spec-Dokument, das Vorhaben behebt Befunde an bestehendem Code
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt nur `scripts/dev/` und `scripts/tests/`, keinen heavy-relevanten Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Herkunft: Fable hat am 2026-09-22 die Handgriffe aus T11 ausgeführt und dabei drei Befunde am
Beweis-Instrument selbst gefunden (R-0060 bis R-0062) plus zwei aus der Verifikation von PR #29
(R-0059). Der Ledger `harness-stufe-4.md` bleibt `blockiert`, bis dieses Vorhaben gemergt ist
**und** ein Red-Team-Lauf mit 0 FAIL und ohne `info` auf einer Pflicht-Probe im Anhang steht.

### T1 — Das Beweis-Instrument muss laut scheitern  [x]
Komponente: scripts/dev · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh (neu, SPDX), scripts/tests/run.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped (scripts) · redteam_test 10/0 · runner_setup_test 58/0
Änderung: `claude_probe` bekommt das fehlende `--verbose` (Claude Code lehnt `-p` mit `--output-format stream-json` ohne ab, der Lauf endet vor der ersten Anfrage). Die Auswertung unterscheidet danach vier Fälle statt zwei: **FAIL**, wenn die Probe nicht laufen konnte (kein verwertbares JSON, Startfehler, Zeitüberschreitung) — ein kaputtes Messgerät darf nicht wie ein Ergebnis aussehen; **FAIL**, wenn das Modell den Werkzeugaufruf wirklich versucht hat und keine Verweigerung im Protokoll steht; **ok**, wenn die Verweigerung im Protokoll steht; **info** mit klarem Wortlaut, wenn das Modell von sich aus abgelehnt hat, ohne ein Werkzeug zu rufen — dann ist die Regel nicht geprüft, und das steht auch so da. Der neue Test fährt die Auswertung gegen gespeicherte JSON-Protokolle aller vier Fälle, ohne Claude Code zu starten.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (intern)

### T2 — Die Push-Probe prüft die Regel, nicht die Höflichkeit des Modells  [x]
Komponente: scripts/dev · Dateien: scripts/dev/runner-redteam.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped (scripts) · redteam_test 10/0 · runner_setup_test 58/0
Änderung: **Beim Bau abgewichen.** Der Plan wollte die Regel über den PreToolUse-Pfad prüfen — das geht nicht: der Harness-Guard bewacht Dateien der Harness, `git push` steht dagegen in der Deny-Liste der Runner-Settings, und die wertet Claude Code selbst aus, nicht ein Hook. Stattdessen zwei Schritte, die beide ehrlich sind: die **Existenz** der Deny-Regel wird deterministisch aus `~/.claude/settings.json` des Runners geprüft (`ok`/`FAIL`, kein Modell, kein Budget), und die Modellprobe läuft in einem **neutralen Verzeichnis** statt im Klon — im Klon las das Modell CLAUDE.md und lehnte ab, bevor die Regel überhaupt erreicht war (2026-09-22 beobachtet: kein einziger Werkzeugaufruf). Lehnt die Sitzung auch dort ab, sagt das Urteil aus T1 genau das, und tragend bleiben die zwei Credential-Proben.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (intern)
Abhängt von: T1

### T3 — Test und Anhang vom lokalen Zustand lösen  [x]
Komponente: scripts/tests · Dateien: scripts/tests/runner_setup_test.sh, tasks/harness-stufe-4.md, DEVELOPMENT.md, scripts/dev/runner-setup.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped (scripts) · redteam_test 10/0 · runner_setup_test 58/0
Änderung: `runner_setup_test` erwartet `useradd` und `git clone` im `--dry-run`-Plan, den `runner-setup.sh` weglässt, sobald der Runner-User existiert — seit der Provisionierung meldet der `scripts`-Gate auf der Dev-Box dauerhaft zwei Fehler und maskiert damit echte Regressionen. Der Test fährt den Dry-Run künftig gegen einen garantiert abwesenden Benutzernamen und prüft den idempotenten Pfad als eigenen Fall. Im Anhang von `harness-stufe-4.md` wird außerdem die Befehlszeile korrigiert: `sudo -iu adminhelper-runner claude setup-token` — ohne `-i` behält sudo den PATH des Aufrufers und findet die CLI des Runners nicht (2026-09-22 verifiziert). Der Trust-Schalter (`projects[…].hasTrustDialogAccepted`) kommt als ausdrücklich abgeschalteter Schritt in `runner-setup.sh` samt Begründung in `DEVELOPMENT.md`, weil er die 38 Allow-Regeln des Runners erst scharf macht — gesetzt wird er von Kevin, nicht vom Skript.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (Trust-Schritt, Warum abgeschaltet) · tasks/harness-stufe-4.md (Anhang)
