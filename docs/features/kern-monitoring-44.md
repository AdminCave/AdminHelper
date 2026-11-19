<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-44 — Top-5-Prozesse bei hoher Last (R-1389)

## Problem / Motivation
Der Ressourcen-Check zeigt bei hoher CPU- oder RAM-Last nur die Zahl, nicht den Verursacher. Monitoring-Dienst
(`apps/monitoring/app/checkers/agent.py` `_top_processes`) und Desktop (`SecLive.svelte`) nehmen `top_processes` schon
an (R-1227, arch-monitoring-ui-2); der Agent sendet es noch nicht (dort T6 verschoben).

## Ziel & Nicht-Ziele
- Liegt `cpu_percent` oder `memory_percent` des Berichts bei 80 % oder darüber (Auslöser A, feste Schwelle im Agenten,
  Kevin 2026-11-12), sendet der Agent im Block `resources` `top_processes: {cpu: [{pid, name, cpu_pct}], memory:
  [{pid, name, rss}]}`, je höchstens fünf, absteigend. Darunter fehlt der Schlüssel.
- Nur `comm` (gopsutil `Name()`), nie Kommandozeile, Pfad oder Umgebung.
- Auf Linux, FreeBSD und Windows (gopsutil `process`).
- Nicht unter dem Last-Tor (`loadgate.go`): die Liste ist gerade bei hoher Last gefragt; sie läuft im Kern-Block
  `resources`.
- Nicht-Ziele: kein Plan-Feld, keine Konfig-Option, keine Änderung an Monitoring, API-Schemas oder Desktop.

## Betroffene Komponenten & Dateien
- `apps/agent/internal/monitor/processes.go` (neu, SPDX) und `processes_test.go` (neu, SPDX).
- `apps/agent/internal/monitor/report.go` (`collectResources`).

## Datenmodell / API / Migrationen
Nur ein hinzugefügter Schlüssel im Bericht (`report_version` bleibt 4); der Dienst liest ihn heute schon optional.
Keine Migration.

## Externe Integrationen
gopsutil `process` (schon Abhängigkeit des Agents): `Processes`, `Name`, `Times`, `MemoryInfo`.

## Trade-offs & Alternativen
- **CPU-Anteil:** zwei Stichproben der Prozesszeiten im Abstand von etwa einer Sekunde (ctx-begrenzt) statt
  `Percent(interval)` je Prozess, das je Prozess schläft. Empfehlung: zwei Stichproben über alle Prozesse.
- **Kosten bei hoher Last:** die Liste läuft nur über der Schwelle; ein Prozess, der zwischen den Stichproben endet
  oder unlesbar ist, fällt weg, ohne den Bericht zu stören.

## Risiken & Rollback
Mehr Arbeit des Agents genau bei Last: eine Liste der Prozesse und zwei Lesungen je Prozess, höchstens alle
Berichtsintervalle. Rollback: Revert; der Dienst kommt ohne den Schlüssel aus.

## Doku-Impact
`docs/admin/monitoring.html` (DE+EN), Abschnitt Ressourcen: Top-5-Prozesse ab 80 %, nur Name und PID;
`changelog.d/kern-monitoring-44.md`.

## Offene Fragen
keine (Auslöser A von Kevin 2026-11-12). R-1413 und R-1391 aus diesem Zug sind wegen Überlappung mit
`feature/kern-monitoring-18` bzw. `feature/kern-windows-1` nach `kern-monitoring-48` verschoben.
