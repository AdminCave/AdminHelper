<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-49 — Glocke: Entwarnung gelöschter Checks, Schweregrad im Nachholjob

Zug aus R-1601 und R-1619 (beide BUG, Kevin 2026-11-19 Triage: angenommen).

## Problem / Motivation

- **R-1601:** `delete_check` und `toggle_check` schließen seit R-1571 den Vorfall der Glocke. Die übrigen Wege, auf
  denen Checks verschwinden, tun es nicht: Template löschen (`routers/templates.py` `delete_template`), Zuweisung
  entfernen (`template_sync.remove_template`, auch über den Tag-Sync), eine Definition fällt beim Template-Sync weg
  (`_sync_checks_for_server`) und Server löschen (`server_cleanup.cleanup_server`). Der Vorfall bleibt offen, bis
  jemand ihn von Hand schließt. Ein „gone“-Fund schaltet seine Checks ab (`module_sync._adopt`); dort sendet der
  Nachholjob aus kern-monitoring-47 die Entwarnung binnen einer Minute (abgeschalteter Check mit Problem in der
  Glocke), ein Test fehlt.
- **R-1619:** `bell_catch_up.lag_target` vergleicht `bell_record(notified_status, severity)` mit `hub_status`. Ändert
  jemand den Schweregrad bei offenem Alarm, weicht die gedeckelte Stufe ab, und der Job sendet ein Ereignis ohne
  Statuswechsel: Anheben eskaliert den Vorfall und pingt, Senken stuft ihn herab.

## Ziel & Nicht-Ziele

**Ziel R-1601** (Kevin 2026-11-19: alle Lösch-Wege mitnehmen): Jeder Weg, der Checks löscht, sendet nach dem Commit
für jeden gelöschten Check, dessen Glocke ein Problem zeigt, die Entwarnung wie `delete_check` (Betreff `…: check
deleted`, Stufe = `hub_status`); ein gescheiterter POST wird geloggt, nicht nachgeholt (die Zeile ist weg, bis zur
Outbox R-1561). Für „gone“ ein Test, dass der Nachholjob die Entwarnung sendet.

**Ziel R-1619** (Kevin 2026-11-19: Variante A, nur Richtung): Ein eingeschalteter Check hinkt nur, wenn die Glocke
Problem/ok anders zeigt als gemeldet, oder wenn sie critical zeigt und warning gemeldet ist (die gedeckelte Stufe ist
nie höher als der Status bei ihrer Aufnahme, also ist das eine echte Herabstufung). Zeigt sie warning bei gemeldetem
critical, ist das nicht unterscheidbar (Schweregrad angehoben oder Eskalations-POST gescheitert) und gilt nicht als
Rückstand.

**Nicht-Ziele:** keine neue Spalte, keine Migration; keine Outbox (R-1561); `delete_check`/`toggle_check` bleiben,
wie sie sind.

## Betroffene Komponenten & Dateien

Nur `apps/monitoring`: `app/bell_catch_up.py` (`lag_target`, ein Helfer für die Entwarnung gelöschter Checks),
`app/routers/templates.py`, `app/template_sync.py`, `app/server_cleanup.py`, Tests unter `apps/monitoring/tests/`.

## Datenmodell / API / Migrationen

Keine Migration, keine API-Änderung. Neue Hub-Ereignisse nur dort, wo heute ein Vorfall offen bliebe.

## Externe Integrationen

Keine neuen: der Hub-POST (`alerter.emit_to_hub`) wie bei `delete_check`.

## Trade-offs & Alternativen

1. **R-1619 Variante B** (Spalte mit dem ungedeckelten Status der Glocke): exakt, kostet eine Migration. Kevin wählte
   A: eine gescheiterte Eskalation warning→critical holt der Job nicht nach; der Vorfall bleibt offen, die Mails
   der Regeln laufen unabhängig von der Glocke.
2. **R-1601 Entwarnung nach dem Commit, synchron:** wie `delete_check`. Bei Hub-Ausfall kostet jeder gelöschte Check
   mit offenem Alarm einen POST-Timeout (5 s); betroffen sind nur Checks, deren Glocke ein Problem zeigt.

## Risiken & Rollback

- Ein Lösch-Weg mit vielen offenen Alarmen bei Hub-Ausfall dauert entsprechend länger (siehe 2).
- Rollback: Revert des Branches.

## Doku-Impact

`docs/admin/monitoring.html` (DE+EN): Löschen über Template, Zuweisung und Server schließt den Vorfall wie das
Löschen eines Checks; ein Wechsel des Schweregrads bei offenem Alarm ändert die Glocke nicht.
`docs/developer/monitoring.html` (DE+EN): Nachhol-Regel und Lösch-Wege. `changelog.d/kern-monitoring-49.md`.

## Offene Fragen

Keine: beide hat Kevin am 2026-11-19 entschieden.
