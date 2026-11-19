<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-41 — Last-Schonung: gehaltene Checks werden nach einer Grenze unknown

Roadmap: R-1400 (Kevin 2026-11-18: beides)

## Problem / Motivation
Setzt das Last-Tor des Agenten Sammler aus (Docker, Proxmox, ZFS, SMART, Proben), behalten deren Checks ihren letzten
Status, solange die Schonung dauert, ohne Grenze. Dauert sie lange, zeigt ein Check mit `ok` einen Zustand, der nicht
mehr gemessen wird. `agent_resources` warnt erst nach 30 min.

## Ziel & Nicht-Ziele
- `agent_resources` warnt ab Beginn der Schonung („Load shedding since …“).
- Ein Check, den die Schonung hält, behält seinen Status höchstens 15 min ab Beginn der Schonung; danach wird er
  `unknown` mit der Meldung „Not measured: load shedding since <Zeit> UTC“, über dieselbe Übergangs- und
  Alarm-Pipeline wie jede Bewertung (`apply_result`). Endet die Schonung, bewertet der nächste Report ihn wieder.
- Nicht-Ziel: das Last-Tor des Agenten selbst, die Selbstdrosselung (`_spared_by_throttle`), konfigurierbare Grenzen.

## Betroffene Komponenten & Dateien
- `apps/monitoring/app/routers/agent.py` (`_spared_by_load_shed`, Report-Schleife)
- `apps/monitoring/app/checkers/agent.py` (`_LOAD_SHED_WARN_MINUTES`, `_grade_load_shed`)
- `apps/monitoring/tests/test_agent_load_shed.py`
- Doku: `docs/admin/monitoring.html#last-schonung`, `docs/en/admin/monitoring.html#load-shedding`,
  `docs/developer/monitoring.html` DE+EN (falls die 30 min dort stehen), `changelog.d/kern-monitoring-41.md`

## Datenmodell / API / Migrationen
Keine. Kein neues Feld im Report; die Grenze rechnet ab `self.load_shed.since`.

## Trade-offs & Alternativen
- Grenze ab Beginn der Schonung (nicht ab der letzten Bewertung des Checks): eine Uhr für alle Checks des Hosts,
  dieselbe wie die Warnung; empfohlen.
- `unknown` über `apply_result` statt still gesetzt: Verlauf und Alarmregeln gelten wie bei jedem Übergang.

## Risiken & Rollback
Mehr `unknown`-Übergänge auf dauerhaft belasteten Hosts (gewollt). Rollback: Revert des Task-Commits.

## Doku-Impact
Admin-Doku „Schonung unter Last“ DE+EN (Warnung ab Beginn, `unknown` nach 15 min), Changelog.

## Offene Fragen
Keine (Kevin 2026-11-18).
