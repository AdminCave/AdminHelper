<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p0-abnahme — Task-Ledger
Status: geplant · Branch: feature/arch-monitoring-neu-p0-abnahme · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p0-abnahme.md (Roadmap R-1558, R-1515)
Heavy: none — nur das Mockup im Vite-Dev-Server (nicht im Desktop-Build, `isolation.test.ts`) und ADR 0004; kein Stack-, Gateway-, PKI-, Agent- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@1d699f0af`. Quelle der Code-Tasks ist der von Kevin abgenommene Entwurf der Runden 1–5 (2026-11-18/19, privates Artefakt), gebaut in einer Wegwerf-Kopie außerhalb des Baums; die Tasks übernehmen ihn Datei für Datei mit Tests. Grenzen „Wie im Mockup“ (Kevin 2026-11-19): Lagekarte 20 Server, 24 Karten (8 mit Kennzahlen), Objekte 200 und Querschnitte 150 je Seite, Objektart-Gruppen 60, ruhige Server ab 25 eingeklappt, Flotten-Teppich ab 40 Servern. Regeln wie in P0: fiktive Daten (RFC-5737-Adressen, Beispielnamen), deutsche Texte ohne `t()`, nur Tokens aus `styles/app.css` und Komponenten aus `components/ui/`, keine nackten globalen Klassen (`.card .chip .list .hidden .filters .btn .field .counter .editor`), jede Animation mit `prefers-reduced-motion`-Abschaltung, SPDX-Header in jeder neuen Datei (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`). jsdom-Lücken (`matchMedia`, `Element.scrollTo`) stubben die Mockup-Tests lokal per `vi.hoisted`, `vitest.setup.ts` bleibt unverändert. Pfade unten relativ zu `apps/desktop/ui/src/mockups/monitoring-neu/`, wo nicht anders genannt; `Dateien:` nennt sie voll.

### T1 — Grammatik, Kennzahl-Balken und Objektzeile (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/grammar.ts, apps/desktop/ui/src/mockups/monitoring-neu/grammar.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/exceptions.ts, apps/desktop/ui/src/mockups/monitoring-neu/Meter.svelte, apps/desktop/ui/src/mockups/monitoring-neu/ObjectRow.svelte, apps/desktop/ui/src/mockups/monitoring-neu/ObjectRow.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/ObjectDrawer.svelte
Änderung: `grammar.ts` bekommt `objectLabel` (Art nicht doppelt: „CPU“ statt „CPU CPU“; `exceptions.ts` nimmt es) und `meterOf` (Lage einer Kennzahl zu ihren Schwellen, Prozent bis 100, sonst ein Viertel über dem Größten). Neu `Meter.svelte` (SPDX): Balken mit Warn- und Kritisch-Marke. `ObjectRow` zeigt ihn an jeder Kennzahl mit Schwelle, heißt ausgeblendet `is-hidden` statt `hidden` (globale `.hidden` aus `app.css`) und stellt auf dem Handy eine Kennzahl je Zeile; die Schublade gleitet ein. Tests: `objectLabel`, `meterOf` (Prozent, Absolutwert, ohne Schwelle, Grenzen 0/100) und der Balken in der Zeile.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts src/mockups/monitoring-neu
Doku: keine (Mockup nur im Vite-Dev-Server; die Abnahme hält T7 im ADR fest)

### T2 — Zusammenfassung je Server, Statusbalken und große Flotte (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/views/servers.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/servers.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/StatusBar.svelte, apps/desktop/ui/src/mockups/monitoring-neu/fixtures/scale.ts, apps/desktop/ui/src/mockups/monitoring-neu/fixtures/scale.test.ts
Änderung: Neu `views/servers.ts` (`serverSummaries`: je Server schlechtester Zustand, Zählungen, offene Probleme, schlechteste zuerst; `lageByServer`; `BAR_ORDER`), `views/StatusBar.svelte` (eine Zählung als gestapelter Balken mit Text für Screenreader) und `fixtures/scale.ts` (deterministische große Flotte, 292 Server, 10 510 Objekte, fiktive Namen). Alle neuen Dateien mit SPDX. Tests: Summen je Server gegen die Objektliste, Reihenfolge, Grammatik-Invarianten, eindeutige Schlüssel und Determinismus der großen Fixture.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts src/mockups/monitoring-neu
Doku: keine (Mockup nur im Vite-Dev-Server)
Abhängt von: T1

### T3 — Objektart-Gruppen, Objekte, Querschnitte, Abdeckung: Seiten, faule Zeilen, Handy (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/views/KindGroups.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/KindsView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/ObjectsView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/CrossView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/CoverageView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/limits.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/views.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/ExceptionDialog.test.ts
Änderung: Neu `views/KindGroups.svelte` (SPDX): Gruppen je Objektart, schlechteste zuerst; Zeilen entstehen erst beim Öffnen und kommen in Seiten zu 60, ab 42 Objekten Statusbalken statt Punkten; `KindsView` nutzt sie. `ObjectsView` (200 je Seite) und `CrossView` (150 je Seite) blättern, Tabellen scrollen auf dem Handy in ihrem Kasten, ausgeblendete Zeilen heißen `is-hidden`; `CoverageView` legt ihre Tabellen in einen Scroll-Kasten. Neu `views/limits.test.ts` (SPDX) prüft die Grenzen mit der großen Flotte (geschlossene Gruppe ohne Zeilen, offene mit 60, „weitere“, Objekte 200, Querschnitte 150).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts src/mockups/monitoring-neu
Doku: keine (Mockup nur im Vite-Dev-Server)
Abhängt von: T2

### T4 — Serverliste und „Alle Server“: Lagekarte, Flotten-Teppich, Karten (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/views/ServerNav.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/Lagekarte.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/AllServers.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/overview.test.ts, apps/desktop/ui/src/mockups/monitoring-neu/views/limits.test.ts
Änderung: Neu (je SPDX) `ServerNav.svelte` (Serverliste wie heute: „Alle Server“, mit/ohne Probleme, schlechteste zuerst, Suche „/“, Pfeiltasten, gleitende Auswahl; ab 25 ruhigen Servern eine Zeile „N Server ohne Probleme zeigen“), `Lagekarte.svelte` (Server × Objektart, die 20 schlimmsten, „alle zeigen“; ab 40 Servern Flotten-Teppich mit Vorschau und Klick) und `AllServers.svelte` (Kopfzahlen, Lagekarte, Karten-Board mit 24 Karten, davon 8 mit Kennzahlen, „N weitere Server zeigen“, offene Probleme als Liste). Tests: Inhalte und Reihenfolge, Falten und Suche, Pfeiltasten, Teppich-Klick wählt den Server, Grenzen 20/24/8/25 mit der großen Flotte.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts src/mockups/monitoring-neu
Doku: keine (Mockup nur im Vite-Dev-Server)
Abhängt von: T3

### T5 — Rahmen: Serverliste, Server-Seite, Handy-Schublade, Datenumschalter; Reiter „Lage“ entfällt (R-1558)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/mockups/monitoring-neu/MockupApp.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/ServerView.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/Lage.svelte, apps/desktop/ui/src/mockups/monitoring-neu/views/views.test.ts
Änderung: `MockupApp` setzt die Serverliste links und „Alle Server“ als Start ein, die Reiter verlieren „Lage“; auf dem Handy (≤ 760 px) ist die Serverliste eine Schublade (Knopf, Escape, Auswahl schließt), jeder Reiter- und Serverwechsel beginnt oben, ein Umschalter wählt „Normal“ oder „Groß“. `ServerView` folgt der Auswahl der Serverliste statt eines eigenen Selects, mit Vitalwerten und Objektart-Gruppen. `views/Lage.svelte` entfällt; ihre Render-Tests in `views.test.ts` laufen mit denselben Aussagen gegen „Alle Server“, der Server-Test gegen die neue Server-Seite. Layout-Beweis (390 px ohne seitliches Überstehen, eine Spalte, Reiterwechsel mit großer Flotte) per headless Chromium gegen den Worktree, Summary im Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/styles/tokens.test.ts src/mockups/monitoring-neu
Doku: keine (Mockup nur im Vite-Dev-Server; die Abnahme hält T7 im ADR fest)
Test-Löschung: apps/desktop/ui/src/mockups/monitoring-neu/views/views.test.ts::Lage: a click opens the drawer of that object — der Reiter „Lage“ entfällt (Runde 1, Kevin 2026-11-18: Serverliste wie heute, „Alle Server“ ersetzt ihn); derselbe Fall läuft im selben `it.each` als „Alle Server“
Abhängt von: T4

### T6 — ADR 0004 §14: Kevins Antworten 1–11 (R-1558, R-1515)  [ ]
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md
Änderung: Kevins Antworten auf die Fragen 1–11 wörtlich mit Datum (2026-11-18, per Ask: alle nach Empfehlung; Frage 11 mit R-1515 als `when` im Katalog-Modul `nextcloud-aio`) unter §14; aus „Offen, je mit Empfehlung“ wird „Entschieden“. Übernommen aus `arch-monitoring-neu-p0` T12.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/adr/0004-monitoring-neuordnung.md
Task-Review: am Ende
Abhängt von: T5

### T7 — ADR 0004: Abnahme der Screens, Status „angenommen“ (R-1558)  [ ]
Komponente: scripts · Dateien: docs/adr/0004-monitoring-neuordnung.md
Änderung: Frage 12 mit Kevins Worten je Runde (1–5) und der Abnahme vom 2026-11-19 samt Grenzen; ein kurzer Abschnitt nennt die abgenommene Struktur (Serverliste, „Alle Server“ mit Lagekarte und Karten, Server-Seite, Reiter, Handy, Mengenverhalten). §13 zieht P2/P3 nach („Lage-Ansicht“ wird „Alle Server“), der Kopf wechselt auf „angenommen“ mit Datum. Übernommen aus `arch-monitoring-neu-p0` T13.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/adr/0004-monitoring-neuordnung.md
Task-Review: am Ende
Abhängt von: T6

## Entscheidungen
