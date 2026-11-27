<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->
# kern-monitoring-56 — Cooldown, Scheduler-Phase, Nachlese P1b/P1d

Zug aus R-1690, R-1696, R-1792, R-1827, R-1828 (alle Monitoring, `apps/monitoring/`).

## Problem je Zeile
- **R-1690:** `_is_in_cooldown` (`apps/monitoring/app/alerter.py:681`) zählt jede erfolgreich gesendete Zeile des
  Alert-Logs, auch eine Recovery. Ein zweiter Ausfall kurz nach der Entwarnung geht deshalb auf keinem Push-Kanal
  der Regel raus. Kevin 2026-11-27: eine Recovery startet den Cooldown nicht neu (Variante a); der Hub bleibt.
- **R-1696:** `add_check` (`apps/monitoring/app/scheduler.py:88`) ersetzt den Job immer; ein neuer `IntervalTrigger`
  startet bei jetzt + Intervall. Jedes PUT, jeder Template-Sync und jeder Neustart schiebt den nächsten Lauf um ein
  volles Intervall; ein 24h-Check auf einem täglich neu startenden Host läuft nie.
- **R-1792, R-1827:** Prüfer-Hinweise der Nachlese P1b/P1d (Einzelheiten `tasks/private/`): ein Test, dass jede
  Route ohne Internal-Key 401 gibt; Längengrenzen für Server-IDs und Regelwerte in `schemas.py`;
  `record_rule_layers` bricht bei einer nicht speicherbaren Zeile nicht den ganzen Durchgang ab.
- **R-1828:** `sync_catalog` (`apps/monitoring/app/module_sync.py:849`) überspringt jede markierte Zeile ohne
  Regel-Schicht, auch zentrale Modul-Checks, die nie eine Schicht bekommen. Kevin 2026-11-27: die Ausnahme gilt
  nur für `check_type == "probe"`, mit Test.

## Ziel & Nicht-Ziele
Ziel: die fünf Zeilen wie oben. Nicht-Ziel: der Hub (`apps/server/.../incidents.py`) und die Intervall-Hooks des
Servers nach einem Neustart (eigene Zeile, falls gewünscht); der 101-Zeichen-Kommentar einer schon ausgerollten
Migration (R-1792, Stil) bleibt, eine ausgerollte Migration ändert der Zug nicht.

## Entwurf R-1696
- Ein Job, dessen Intervall gleich bleibt, behält seinen nächsten Lauf (wie `hooks/scheduler.py:add_hook`).
- Beim Laden (`load_all_checks`) beginnt die Phase bei `MonitorState.last_check` + Intervall; liegt das in der
  Vergangenheit, läuft der Check in der ersten Minute an zufälliger Stelle: nach einem langen Stillstand feuerten
  sonst alle zugleich, und ein Lauf, der länger als `misfire_grace_time` im Pool wartet, verfällt für eine volle
  Periode. Zentrale Checks ohne bekannten Lauf behalten die zufällige Phase (R-1224).

## Datenmodell / API / Migrationen
Keine Migration. API: `server_id`/`match_server_id` höchstens 255 Zeichen, Regelwerte (Zeichenketten) höchstens
255, Listen höchstens `MAX_FIELDS` — vorher unbegrenzt, nur Admins hinter dem Internal-Key; ein längerer Wert gibt 422.

## Risiken & Rollback
Scheduler: ein Fehler in der Phasenberechnung verschiebt Läufe; Tests pinnen Behalten, Ableiten und Überfälliges.
Jede Task einzeln revertierbar.

## Doku-Impact
`docs/admin/monitoring.html` und EN: Cooldown-Absatz (eine Entwarnung startet ihn nicht), Intervall-Phase nach
Neustart und Ändern; CHANGELOG über `changelog.d/kern-monitoring-56.md`.
