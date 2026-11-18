<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Zug 45: Bewertungs- und Zustandsfehler (kern-monitoring-45)

Roadmap: R-1525, R-1565, R-1566, R-1567, R-1568, R-0518, R-1570, R-1571, R-1572, R-1573. Kevin 2026-11-18 Triage:
angenommen. R-1569 fährt nicht mit (ändert `allowlist.go` wie das offene `feature/kern-monitoring-18` und braucht
erst den Beleg auf einer Testbox); es geht in den Zug `kern-monitoring-47`.

## Problem je Zeile

- **R-1525 — Anfrageprüfung im Server.** Die Prüfung gespeicherter Werte im Server
  (`apps/server/app/core/bounds.py`) soll der Monitoring-Kopie (`apps/monitoring/app/core/bounds.py`) gleichen.
- **R-1565 — disk_forecast.** Eine volle Platte (≥ 100 %) bekommt kein `hours_left` und meldet „stabil“
  (`app/checkers/forecast.py`, Zweig `last_pct >= 100`). Die Vorhersage ignoriert außerdem `ignore_mounts`,
  `disk_overrides` und die 20-GB-Grenze (`disk_min_free_gb`) der Ressourcen-Prüfung desselben Hosts.
- **R-1566 — Status-Zusammenfassung.** `GET /status/summary` (`app/routers/checks.py`, `get_status_summary`) zählt
  die Zustände aller Checks, auch abgeschalteter, mit ihrem eingefrorenen Status; der Docstring meint nur aktive.
- **R-1567 — Katalog-Update.** `_update` (`app/module_sync.py`) übernimmt von einer geänderten Modul-Definition alles
  außer `interval_s` und `timeout_s`; eigene Regeln des Admins (per API geänderte Schwellen) gehen still verloren.
  Zwischenlösung laut Zeile: geänderte Regeln erkennen und das Update mit Grund überspringen.
- **R-1573 — Rückkehr einer Instanz.** Kehrt eine verschwundene Instanz zurück (Fund `new` nach `gone`), schaltet
  `_adopt` alle ihre Checks wieder ein, auch die, die der Admin selbst abgeschaltet hat. Kevin 2026-11-18: nur die
  wieder einschalten, die `gone` abgeschaltet hat.
- **R-1568, R-0518 — SMART dreiwertig.** `smart_absent` mit `scan_failed` ergibt heute `ok`
  (`app/checkers/smart.py`, `_absent_result`). Liefert smartctl für eine Platte kein `smart_status` (SMART
  abgeschaltet, Exit-Bit 2), meldet der Agent `smart_passed: false` (`apps/agent/internal/monitor/smart.go`,
  `querySmartDevice`), und der Dienst zeigt „SMART FAILED“. Künftig: „nicht erhoben“ und „nicht lesbar“ statt `ok`
  bzw. `critical`.
- **R-1570 — ZFS.** `SUSPENDED` und `REMOVED` werden nicht bewertet (`app/checkers/plugins.py`, ZFS-Prüfung).
  Scrub-Fehler zeigt der Desktop gelb, bewertet werden sie nicht. Das Scrub-Alter 35/60 Tage steht fest im Code.
  Der Desktop zeigt `DEGRADED` gelb, die Prüfung bewertet es kritisch
  (`apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte`, `healthClass`).
- **R-1571 — Hub-Vorfall bleibt offen.** Abschalten (`toggle_check`) oder Löschen (`delete_check`) eines Checks
  meldet dem Hub nichts; ein offener Vorfall des Checks bleibt vermutlich dauerhaft offen. Erst ein roter Test, sonst
  als nicht reproduziert schließen.
- **R-1572 — Hub-Übergabe.** `_claim` (`app/alerter.py`) setzt `hub_status` vor dem POST; scheitert der POST, wird
  nur der Glocken-Platz zurückgegeben, die Meldung vermutlich nie nachgeholt. Erst ein roter Test, sonst als nicht
  reproduziert schließen. Die Dauerlösung (Outbox) gehört zur Neuordnung, nicht hierher.

## Ziel & Nicht-Ziele

- Jede Zeile bekommt einen Test, der den Fund zeigt (rot vor, grün nach dem Fix); R-1571 und R-1572 werden ohne
  roten Test als nicht reproduziert geschlossen.
- R-1565: Volle Platte ist `critical` („voll“), `hours_left` 0. Die Vorhersage übernimmt die Plattenregeln der
  Ressourcen-Prüfung desselben Hosts: `ignore_mounts` fällt heraus, eine Platte mit mindestens `min_free_gb` frei
  (je Mount aus `disk_overrides`, sonst `disk_min_free_gb`) alarmiert nicht. `free_gb` kommt aus dem letzten
  Ergebnis dieser Prüfung (`_details.disks`), nicht aus einer neuen Metrik.
- R-1570: `SUSPENDED`, `REMOVED` kritisch; Scrub-Fehler `warning`; Scrub-Alter als Konfiguration
  (`scrub_warn_days`, `scrub_crit_days`, Vorgabe 35/60); der Desktop zeigt `DEGRADED` rot wie die Bewertung.
- Nicht-Ziele: die Neuordnung (Regel-Schlüssel, Outbox, Objekt/Problem); `smartctl -n standby` (R-1569).

## Betroffene Komponenten & Dateien

- server: `app/core/bounds.py`, `tests/test_bounds.py` — R-1525
- monitoring: `app/checkers/forecast.py`, `app/check_engine.py` (Regeln anhängen) — R-1565; `app/routers/checks.py`
  — R-1566, R-1571; `app/module_sync.py` — R-1567, R-1573; `app/checkers/smart.py` — R-1568; `app/checkers/plugins.py`,
  `app/check_configs.py` (`ZfsConfig`) — R-1570; `app/alerter.py` — R-1572
- agent: `internal/monitor/smart.go` — R-0518
- desktop-ui: `src/components/monitoring/section/SecZfs.svelte` — R-1570

## Datenmodell / API / Migrationen

- Keine Alembic-Migration. R-1573 liest den Admin-Schalter aus `overridden_fields` („enabled“, gesetzt von
  `toggle_check` über `mark_overrides`).
- Wire-Format Agent → Monitoring: `smart_passed` fehlt künftig, wenn smartctl keinen `smart_status` liefert. Ein
  alter Dienst liest ein fehlendes Feld als bestanden (`disk.get("smart_passed", True)`), also nie als „FAILED“.
- `GET /status/summary` zählt nur aktive Checks; Form der Antwort unverändert.

## Trade-offs & Alternativen

- R-1565 `free_gb` aus dem letzten Ergebnis der Ressourcen-Prüfung statt einer neuen Metrik: keine neue Serie, keine
  Historie nötig; ohne Ergebnis (alter Agent, keine Prüfung) gilt die Grenze nicht, wie bei der Ressourcen-Prüfung.
- R-1567 erkennt geänderte Regeln über `overridden_fields` (Feld `config`) bzw. den Vergleich mit der Definition, aus
  der der Check entstand; die Entscheidung fällt beim Bau mit Test, Ergebnis in `## Entscheidungen`.

## Risiken & Rollback

- R-1566 ändert Zahlen auf dem Dashboard (abgeschaltete Checks fallen heraus): gewollt.
- R-1568 ändert, wann die SMART-Prüfung alarmiert; die Stufen fragt das Gate (offene Frage 1).
- Rollback: Commits zurücknehmen; kein Datenformat bleibt zurück.

## Doku-Impact

`docs/admin/monitoring.html` (Vorhersage, SMART, ZFS, Status-Zusammenfassung, Modul-Sync) DE+EN,
`docs/developer/agent.html` (`smart_passed`) DE+EN, `changelog.d/kern-monitoring-45.md`.

## Offene Fragen

1. **SMART-Stufen (R-1568, R-0518):** entschieden, Kevin 2026-11-18: „nicht erhoben“ = `info`, „nicht lesbar“ =
   `unknown`.
