<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-3 — Spec

## Problem
- **R-1380** (Nits aus arch-monitoring-module-2): README nennt den Check-Typ `central` und
  `MONITOR_PUBLIC_RESOLVERS`/`MONITOR_SPAMHAUS_DQS_KEY` nicht (Typenliste, Env-Tabelle, `checkers/`-Zeile im Baum);
  die Monitoring-Doku (Admin und Entwickler, DE+EN) nennt `days_left`/`lifetime_pct` nur bei tls, smtp und imap
  liefern sie auch; `MonitorCheckModal.svelte` übernimmt die Partnerliste einer verspäteten `fetchStatus`-Antwort
  eines früheren Öffnens; `test_check_engine.py` schreibt U+FFFD als Escape statt als Literalzeichen.
- **R-1390** (Nits aus arch-monitoring-ui-2): DE `monitoring.docker.upFor` ergibt „läuft seit 5 Tage“; EN
  `monitoring.zfs.scrubErrors` ergibt „1 errors“; `SecDocker.svelte` sortiert eine kritische Gruppe ohne Projekt
  vor gesunde Projekte (Ledger sagt „zuletzt“, kein Test); `capped_objects` in `checkers/plugins.py` filtert vor dem
  Slice, Nicht-Objekte belegen anders als bei den Ports keinen Platz; E2E-Screenshots in
  `monitoring-server-page.live.js` verdecken Alarm-Toasts unten rechts; Kommentar `checkers/agent.py` („at most
  five processes per list“) greift R-1389 vor; `changelog.d/arch-monitoring-ui-2.md` hat ein gerades schließendes
  Anführungszeichen nach „Updates & Neustarts“.
- **R-1377:** die Monitoring-Doku sagt, der Agent „prüfe“ relativ oder abstrakt gebundene Unix-Sockets nicht; er
  weist sie ab.
- **R-1371:** erledigt auf `main` (0e8bf9d24, kern-monitoring-22 T9; `dictionaries.ts` sagt „Der Agent hat das Ziel
  abgewiesen“). Die Zeile wird geschlossen, keine Task.
- **R-1386** (Cosign-Regex, `cicd.html`) fährt nicht mit: `feature/ci-13` ändert dieselben Dateien (`overlap.sh`);
  die Zeile wandert in `tasks/klein-ci-3.md`.

## Ziel / Nicht-Ziele
Nur die genannten Stellen. Entscheidungen im Zuschnitt: `SecDocker` behält „schlimmste Gruppe zuerst“ (die
Reihenfolge wird durch einen Test festgeschrieben, der Wortlaut „zuletzt“ steht nur im alten Ledger); die
Plural-/Kasus-Texte wählen eine Formulierung, die ohne Pluralregel stimmt, wenn das Wörterbuch keine kennt.
`capped_objects` zählt Nicht-Objekte künftig in die Grenze, wie bei den Ports.

## Dateien
`README.md`; `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `docs/developer/monitoring.html`,
`docs/en/developer/monitoring.html`; `changelog.d/arch-monitoring-ui-2.md`;
`apps/desktop/ui/src/components/monitoring/MonitorCheckModal.svelte` (+ Test), `section/SecDocker.svelte` (+ Test),
`apps/desktop/ui/src/lib/i18n/dictionaries.ts`; `apps/monitoring/app/checkers/plugins.py`, `checkers/agent.py`,
`apps/monitoring/tests/test_check_engine.py`; `apps/desktop/e2e/test/specs/monitoring-server-page.live.js`.

## Datenmodell / API / Migrationen
Keine. Kein API-Vertrag, kein Schema.

## Doku-Impact
README (Typenliste, Env-Tabelle, Baum) und die vier Monitoring-Seiten (`days_left`/`lifetime_pct`, Unix-Socket-
Wortlaut), DE+EN.

## Risiken & Rollback
Gering; je Task einzeln zurücknehmbar. `capped_objects` ändert, welche Einträge eines überlangen Agent-Arrays
erscheinen (nur über der Grenze).

## Offene Fragen
Keine.
