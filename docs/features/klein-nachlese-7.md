<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-7

## Problem / Motivation
Zwei Nachlese-Zeilen aus Reviews von `klein-nachlese-3` und `arch-monitoring-apps-1`:
- R-1403: `_top_processes` (`apps/monitoring/app/checkers/agent.py`) und `_oom_processes`
  (`apps/monitoring/app/checkers/system.py`) schneiden mit `capped_objects(...)[:N]` vor dem Filter. Ein Eintrag ohne
  pid oder Namen belegt dadurch einen der N Plätze, obwohl er nie angezeigt wird.
- R-1405 (Kevin 2026-11-13, Triage: angenommen inkl. jicofo-Regel): (1) `jicofo.service` ist ein sysv-generierter Unit
  mit `RemainAfterExit=yes` und bleibt nach einem Absturz `active (exited)`; nur der Health-Check sieht es. Regel
  `sub_state eq exited -> critical` am Check `service`. (2) `tasks/arch-monitoring-apps-1.md` T7 nennt die nicht
  existierende `modules/jitsi.py`. (3) Das Docstring von `onlyoffice.py` nennt `onlyoffice/documentserver-ie` nicht unter
  „Not covered“. (4) Die Tabellenzeile Rocket.Chat in `docs/admin/monitoring.html` (DE + EN) nennt nicht, dass ein
  JSON ohne die drei `checks`-Felder (etwa ein Fehler mit 404/500) `unknown` ergibt, nicht `critical`.

## Ziel & Nicht-Ziele
Ziel: die vier Punkte und R-1403, je mit Test, wo Verhalten wechselt. Nicht-Ziele: andere Module, andere Regeln,
weitere Listen in den Checkern.

## Betroffene Komponenten & Dateien
`apps/monitoring/app/checkers/agent.py`, `system.py`; `apps/monitoring/app/catalog/modules/jitsi_jicofo.py`,
`onlyoffice.py`; Tests `test_agent_resources_checker.py`, `test_system_state_checker.py`, `test_catalog_jitsi.py`;
`docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`; `tasks/arch-monitoring-apps-1.md` (Dateiname).

## Datenmodell / API / Migrationen
Keine. Die jicofo-Regel ändert die Katalog-Definition: `version` 1 → 2, übernommene Instanzen bekommen das Update als
Angebot (R-1223), nichts wird ungefragt umgeschrieben.

## Externe Integrationen
Keine neuen. systemd: `sub_state` einer Unit mit `RemainAfterExit=yes` nach dem Ende ist `exited`.

## Trade-offs & Alternativen
R-1403: Der Titel nennt zwei Ziele, die sich widersprechen (unbrauchbare Einträge nicht mitzählen, und `limit=` wie in
`plugins.py`). `capped_objects(limit=N)` schneidet die ersten N Roh-Einträge und zählte unbrauchbare weiter mit.
Empfehlung (umgesetzt): erst filtern, dann auf N begrenzen (Schleife mit Abbruch nach N brauchbaren Einträgen über die
schon auf 500 begrenzte Liste); der Docstring bleibt dabei wahr. Sichtbare Wirkung: bei Müll-Einträgen zeigt die Detail-
Ansicht bis zu N brauchbare statt weniger.

## Risiken & Rollback
Revert je Task. Die jicofo-Regel ist ein Katalog-Update mit Angebot, kein Zwang; ein `exited`-Unit, das Kevin dauerhaft
so betreibt, gibt es bei Jicofo nicht (der Dienst läuft dauerhaft).

## Doku-Impact
`docs/admin/monitoring.html` + EN: Zeile jitsi-jicofo (Unit-Regel statt „bleibt active“) und Zeile rocketchat
(Antwort ohne `checks` ist `unknown`); `changelog.d/klein-nachlese-7.md`.

## Offene Fragen
Keine.
