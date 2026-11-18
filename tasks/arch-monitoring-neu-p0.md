<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p0 — Task-Ledger
Status: geplant · Branch: feature/arch-monitoring-neu-p0 · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p0.md (Roadmap R-1558, R-1515)
Heavy: none — Mockups nur im Vite-Dev-Server (nicht im Produktions-Build), Regel-Prototyp nur in Tests, ADR und Doku; kein Stack-, Gateway-, PKI-, Agent- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@3aa2499f1`. Kein Produktverhalten ändert sich: keine Migration, keine API, kein Agent-Feld, kein
Checker. Die Mockups nutzen nur Tokens und Komponenten unter `apps/desktop/ui/src/components/ui/`, fiktive Daten
(Hosts `pve-01`, `nas-01`, `web-01` …, Domains `example.org`/`example.com`, Adressen nach RFC 5737), deutsche Texte
ohne `t()`; jede Ansicht trägt den Hinweis „Mockup, fiktive Daten“, Kennzahlen, die neue Agent-Daten brauchen, sind
markiert. Neue Quelldateien bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license
GPL-3.0-or-later <datei>`). Die Grammatik-Invarianten (Ebene 2 höchstens vier Kennzahlen, jede mit Schwellen-Kontext
oder ausdrücklich ohne; Ebene 1 ein Satz Grund; Schlüssel je Objekt eindeutig) prüft ein Test über alle Fixtures.
Experiment-Proben bleiben außerhalb des öffentlichen Baums; Verfahren und Messwerte stehen im ADR. Belegte Fehler
werden Roadmap-Zeilen (`roadmap.py add`), nicht in diesem Zug gefixt.

### T1 — Mockup-Gerüst und Darstellungs-Grammatik (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/mockup.html, apps/desktop/ui/src/mockups/monitoring-neu/main.ts, apps/desktop/ui/src/mockups/monitoring-neu/MockupApp.svelte, apps/desktop/ui/src/mockups/monitoring-neu/model.ts, apps/desktop/ui/src/mockups/monitoring-neu/grammar.ts, apps/desktop/ui/src/mockups/monitoring-neu/grammar.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/ObjectRow.svelte, apps/desktop/ui/src/mockups/monitoring-neu/ObjectDrawer.svelte, apps/desktop/ui/src/mockups/monitoring-neu/ObjectRow.test.ts
Änderung: Zweiter Vite-Einstieg `mockup.html` (nur Dev-Server; `vite build` baut weiter nur `index.html`, ein Test prüft, dass `vite.config.ts` keinen zweiten Einstieg nennt und `main.ts` nichts aus `mockups/` importiert). `model.ts` beschreibt Objekt (Schlüssel, Art, Name, Identität, Status ok/info/warning/critical/unknown/nicht erhoben/veraltet, Grund, seit, schlecht seit, Kennzahlen mit Schwelle, Detail-Abschnitte, Ausnahme). `grammar.ts`: Sortierung (schlechteste zuerst, ausgeblendete grau am Ende), Schwellen-Text („41 °C (Warnung ab 55)“), „seit“-Text, Grammatik-Prüfung. `ObjectRow` zeigt Ebene 1 + 2 und Identitätszeile, `ObjectDrawer` Ebene 3 mit Abschnitten (Kennzahlen, Verlauf, Regeln, Ausnahmen, Rohdaten). `MockupApp` mit Navigation über die Ansichten der folgenden Tasks.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: → T11

### T2 — Objektarten Speicher und Backup: disk, pool, guest-backup, backup-job (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/fixtures/storage.ts, apps/desktop/ui/src/mockups/monitoring-neu/details/SmartAttributes.svelte, apps/desktop/ui/src/mockups/monitoring-neu/details/VdevTree.svelte, apps/desktop/ui/src/mockups/monitoring-neu/details/BackupList.svelte, apps/desktop/ui/src/mockups/monitoring-neu/details/TrendChart.svelte, apps/desktop/ui/src/mockups/monitoring-neu/fixtures.test.ts
Änderung: Fixtures je Zustand nach Konzept §4.1–§4.3: Platte HDD/SATA-SSD/NVMe/SAS (gesund, umgelagert steigend bzw. unverändert, zu heiß mit Hysterese, Medienfehler, NVMe-Reserve, schläft, nicht lesbar, ausgeblendet mit wertgebundener Ausnahme), Pool (gesund, beeinträchtigt, fast voll, Scrub überfällig, angehalten), Gast-Backup (gesichert, veraltet, nie, Lauf fehlgeschlagen, kein Job, Verifizierung, gestoppt/Ausnahme), Backup-Job. Schubladen-Abschnitte: SMART-Attributtabelle mit Exit-Bits im Klartext, vdev-Baum, Backup-Liste, Trendkurve (SVG aus Tokens) mit Schwellenlinie. `fixtures.test.ts` prüft die Grammatik-Invarianten über alle Fixtures (wächst mit T3/T4).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: → T11
Abhängt von: T1

### T3 — Objektarten Host und Betriebssystem: host, cpu, memory, mount, sensor, reboot, updates, clock, service (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/fixtures/host.ts, apps/desktop/ui/src/mockups/monitoring-neu/details/LogLines.svelte, apps/desktop/ui/src/mockups/monitoring-neu/details/ProcessTable.svelte, apps/desktop/ui/src/mockups/monitoring-neu/fixtures.test.ts
Änderung: Fixtures nach Konzept §4.7–§4.12: Host (meldet sich, seit 47 min still, noch nie gemeldet, Lastschonung), CPU/RAM mit Load und OOM-Ereignis, Mount mit Prognose („voll in ~9 Tagen“, Warnung unter 24 h) und 20-GB-Regel im Klartext, Sensor mit Hardware-Grenze, Neustart nötig seit, Updates mit Paketlisten-Alter, Uhr, Dienst (fehlgeschlagen seit, Neustart-Schleife, entfernt); Zustände „nicht erhoben“ und „veraltet“ sichtbar anders als ok. Schublade mit Journal-Auszug und Top-Prozessen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: → T11
Abhängt von: T2

### T4 — Objektarten Container, Netz und Katalog-Module (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/fixtures/workloads.ts, apps/desktop/ui/src/mockups/monitoring-neu/fixtures/network.ts, apps/desktop/ui/src/mockups/monitoring-neu/fixtures/modules.ts, apps/desktop/ui/src/mockups/monitoring-neu/fixtures.test.ts
Änderung: Container und Compose-Projekt (läuft seit, ungesund seit, abgestürzt mit Code, Speicher erschöpft, Neustart-Schleife, gestoppt grau, verschwunden), Zertifikat (eine Bewertung aus mehreren Quellen), Domain, Endpunkt mit optionaler Latenz-Regel; je Katalog-Familie (Web/Proxy, Apps, Datenbanken, Mail, Backup-Module, Windows-Rollen, Verzeichnis, Virtualisierung, Netz, Host-Hardware, Generisch) ein Beispiel mit Ebene 1 im Klartext statt `field = value (op soll)`, Kennzahlen mit Schwelle und je Familie die Variante mit und ohne benannte Unterobjekte (Spec, offene Frage 7).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: → T11
Abhängt von: T3

### T5 — Ansichten Lage, Server, Objekte und Querschnitte (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/views/Lage.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/ServerView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/ObjectsView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/CrossView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/cross.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/views.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/MockupApp.svelte
Änderung: Lage: nur offene Probleme (schlechteste zuerst, seit, bestätigt von), Grünes in einer Zeile, veraltete Hosts mit ihren Objekten zusammengefasst. Server: Identität, Probleme, Objekte je Art gruppiert, Abdeckungs-Kurzzeile. Objekte: Tabelle über alle Server mit Filtern (Art, Zustand, Server, ausgeblendet ja/nein) und Suche. Querschnitte aus derselben Objektliste mit Spalten je Art (Konzept §5: Platten, Backups, Pools, Container, Zertifikate, Updates & Neustart, Mounts, Dienste). Ein Klick auf ein Objekt öffnet überall dieselbe Schublade. Tests: Lage zeigt kein ok-Objekt einzeln, Filter und Sortierung, Spaltenzahl je Querschnitt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: → T11
Abhängt von: T4

### T6 — Ausnahme-Dialog, Liste Ausgeblendet und Abdeckung (R-1558, R-1515)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/views/ExceptionDialog.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/HiddenView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/CoverageView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/exceptions.ts, apps/desktop/ui/src/mockups/monitoring-neu/exceptions.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/MockupApp.svelte, apps/desktop/ui/src/mockups/monitoring-neu/ObjectDrawer.svelte
Änderung: Ausnahme-Dialog aus der Schublade: Geltung (Objekt, Regel, Check, Check-Typ, Server, Tag, Cluster), Wirkung (nicht prüfen, prüfen und nicht bewerten, nicht melden, nur für mich still), Dauer (dauerhaft, bis, wiederkehrendes Fenster mit Zeitzone), optional an den aktuellen Wert gebunden, optional „solange Check X Zustand Y meldet“ (R-1515), Grund optional, Vorschau „betrifft N Objekte“, Rückfrage. `exceptions.ts` wendet Ausnahmen auf die Fixtures an (grau ans Ende, Grund, wer, bis; wertgebundene erlischt bei Wertänderung). Liste Ausgeblendet (alle Ausnahmen mit Geltung, Wirkung, Grund, wer/wann, Ablauf; alte zur Prüfung vorgelegt; migrierte als „unbekannt (migriert)“). Abdeckung je Server: überwacht, gefunden und nicht überwacht, ausgeblendet; Profile an Tags mit Fund-Politik. Tests für `exceptions.ts`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/mockups/monitoring-neu
Doku: → T11
Abhängt von: T5

### T7 — Regel-Prototyp: Schlüssel, Overrides, Drei-Wege-Merge, Delta, Hysterese, Instanz-Bedingung (R-1558, R-1515)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/rule_model_prototype.py, apps/monitoring/tests/test_rule_model_prototype.py
Änderung: Prototyp (nur Tests, P1 ersetzt ihn): Regel mit stabilem `key`, Operatoren wie heute (`app/checkers/probe.py:125`) plus „steigt“ über den Vorwert je Objekt und Hysterese (`clear` je Regel: Entwarnung erst unter/über einem eigenen Wert); Overrides als eigene Schicht je Check (`key` → Wert/Stufe/an-aus); Drei-Wege-Merge beim Katalog-Update (alt, neu, Overrides; Konflikte benannt, eigene Änderung überlebt, entfernte Regel nimmt ihr Override mit, Hash der Katalog-Definition stabil); wertgebundene Ausnahme; Bedingung über einen anderen Check derselben Instanz in beiden Formen (Regel-`when` und Ausnahme mit Bedingung). Tests je Eigenschaft, darunter der heutige Fall „Katalog-Update überschreibt eigene Regel“ (`app/module_sync.py:432-434`) als Merge-Szenario.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_model_prototype.py
Doku: → T9

### T8 — Differenzial-Test: SMART, ZFS und Docker als Regeln gegen die heutigen Checker (R-1558)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_rule_model_differential.py, apps/monitoring/tests/rule_model_prototype.py
Änderung: Die Bewertungen von `SmartHealthChecker` (`app/checkers/smart.py:239`), `ZfsHealthChecker` (`app/checkers/plugins.py:276`) und `_rate_container` (`app/checkers/plugins.py:401`) als Regelsätze des Prototyps je Objekt; parametrisierte Szenarien fahren beide Wege und vergleichen Stufe je Objekt und Gesamtstufe. Was die Regelform nicht ausdrücken kann (etwa Bitfelder, Zustandsautomaten, Vorwert über die Container-ID), steht als benanntes Szenario mit erwarteter Abweichung und Begründung; diese Liste geht in ADR 0004.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_rule_model_differential.py tests/test_rule_model_prototype.py
Doku: → T9
Abhängt von: T7

### T9 — ADR 0004: Zielmodell, Schlüssel je Objektart, Regelmodell, Migrationsplan (R-1558, R-1515)  [ ]
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md
Änderung: Status „vorgeschlagen“. Zielmodell (Objekt, Regel, Ausnahme, Problem, Abdeckung) und Darstellungs-Grammatik; Tabelle stabiler Schlüssel je Objektart mit Rückfall und Instabilitäts-Markierung; Objektzustand (`monitor_object_state`, Statuswechsel-Log) und Problem-Schlüssel; Regelmodell mit Ergebnis aus T7/T8 (was Regel wird, was Code bleibt, Empfehlung zu R-1515); Migrationsplan je heutigem Mechanismus (Ignorierlisten, `enabled`, Wartung, Mutes, Alarmregeln, Tombstones, Messreihen nach Gerätename) mit Reihenfolge, Kompatibilität alter Desktops und Rückweg; Datenlücken im Agent; Phasen P1–P5.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/adr/0004-monitoring-neuordnung.md
Task-Review: am Ende
Abhängt von: T8

### T10 — Experimente und Ergebnisse (R-1558)  [ ]
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md
Änderung: Experimente lokal (Test-DB, Docker, VictoriaMetrics-Container, pytest-Ebene mit Wegwerf-Proben außerhalb des öffentlichen Baums): Hub-Fehler beim Melden, Deaktivieren eines kritischen Checks (Vorfall, Summary), Monitoring 20 min gestoppt (agent_ping), 400 Objekt-Upserts je Report (Sperrdauer), Sammelabruf über 50 Reihen (Latenz), Schlüssel bei neu angelegtem Container (Compose-Nummer); `smartctl -n standby` mit Messweg für eine echte HDD als „nicht verifiziert“. Je Experiment Verfahren, Messwert, Folgerung im ADR; belegte Fehler als Roadmap-Zeilen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/adr/0004-monitoring-neuordnung.md
Task-Review: am Ende
Abhängt von: T9

### T11 — Entwickler-Doku: Mockup-Einstieg und Verweis auf ADR 0004 (R-1558)  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Änderung: `DEVELOPMENT.md` nennt den Mockup-Einstieg (`npm --prefix apps/desktop/ui run dev`, dann `/mockup.html`; nicht im Build). Die Entwickler-Seite zum Monitoring-Stack DE+EN verweist auf ADR 0004 als vorgeschlagene Neuordnung.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: DEVELOPMENT.md, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Abhängt von: T10

### T12 — Kevins Entscheidungen festhalten (R-1558, R-1515)  [?] (Kevin: Entscheidungen 1–11 der Spec „Offene Fragen“, Unterobjekte mit Namen je Familie, Form von R-1515)
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md
Änderung: Kevins Antworten wörtlich mit Datum im ADR (Abschnitt Entscheidungen) und unter `## Entscheidungen` dieses Ledgers; Folgen für P1–P5 im ADR nachziehen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/adr/0004-monitoring-neuordnung.md
Task-Review: am Ende
Abhängt von: T11

### T13 — Abnahme der Screens durch Kevin (R-1558)  [?] (Kevin: Abnahme der Mockups je Ansicht und Objektart)
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md
Änderung: Screenshots je Ansicht und Objektart (headless Chromium gegen den Vite-Dev-Server) an Kevin, dazu die Mockup-Seite als privates Artefakt mit fiktiven Daten; Kevins Abnahme und Änderungswünsche im ADR, Status „angenommen“. Änderungswünsche, die die Mockups betreffen, baut die Session vorher als Nachbesserung in T1–T6 (eigener Commit, Prüfer fortgesetzt).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/adr/0004-monitoring-neuordnung.md
Task-Review: am Ende
Abhängt von: T12

## Entscheidungen
