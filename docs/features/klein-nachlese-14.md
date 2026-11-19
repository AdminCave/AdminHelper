<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-14 — Spec

## Problem
Neun Nachlese-Zeilen (REF) aus Prüfer-Nits der Monitoring-Züge, ohne gemeinsame Funktion:
- **R-1546**: Docstring von `module_sync.py` hat eine Zeile über 100 Zeichen; `catalog/model.py` parst `min_interval`
  von Hand, obwohl `scheduler.interval_timedelta` es kann.
- **R-1549**: `central/fetch.py` `_deadline` nennt in der Meldung die verbleibende Zeit, nicht den Rahmen, den der
  Aufrufer bekam.
- **R-1550**: `resolve.classify` läuft vor dem Watchdog; die RDAP-Abfrage kann `QUERY_DEADLINE_S` um die DNS-Zeit
  überschreiten, ohne dass das irgendwo steht.
- **R-1551**: Doc-Kommentar von `discovery.Run` (Agent) hat Zeilen von rund 125 Zeichen.
- **R-1574**: `smart.py` zählt `smart_disks_warning/critical` nach Meldungen statt nach Platten; die Sortierfunktion in
  `SecBackups.svelte` liest nur ein Argument; der Schlüssel `check_restarts` ist tot und sein Kommentar veraltet; der
  Agent liefert SMART-Platten in Goroutinen-Reihenfolge.
- **R-1590**: `docs/developer/monitoring.html` (DE+EN) nennt für `_origin` den Port-Fund nur mit `ports`, es braucht
  auch `sockets`; ein Fund ohne eigene Instanzart braucht `containers`, `units`, `sockets`, `markers`.
- **R-1591**: Der Agent-Kommentar und die Entwickler-Doku sagen als Tatsache, ein Timeout beende ein in NFS/CIFS
  hängendes `stat -f`; an einer echten hängenden Freigabe ist das nicht geprüft.
- **R-1593**: Ein Webhook-Body, an dem `json.loads` mit `RecursionError` scheitert, wird zu `{}` und das Skript läuft;
  ab 33 Ebenen antwortet derselbe Pfad mit 422.
- **R-1603**: `SecZfs.svelte` hat einen Kommentar zur Pool-Gesundheit, der nicht mehr stimmt, und einen toten
  `warn`-Zweig; das `zfs_health`-Formular bietet `scrub_warn_days`/`scrub_crit_days` nicht an.

## Ziel / Nicht-Ziele
Jede Zeile genau wie beschrieben beheben. Verhaltensänderungen: R-1574 (Zähler je Platte, Reihenfolge der Platten),
R-1593 (Body mit zu tiefer Verschachtelung wird abgelehnt statt zu `{}`), R-1603 (zwei neue Formularfelder).
R-1591 wird nicht an einer echten hängenden Freigabe geprüft (keine Infrastruktur dafür): die Aussage wird in Kommentar
und Doku auf das beschränkt, was belegt ist. Nicht-Ziel: der Schlüssel `check_restarts` wird nicht aus dem Schema
entfernt (gespeicherte Konfigurationen würden 422).

## Betroffene Komponenten & Dateien
`apps/monitoring` (`module_sync.py`, `catalog/model.py`, `central/fetch.py`, `central/rdap.py`,
`checkers/smart.py`, `check_configs.py`), `apps/agent` (`discovery`, `monitor/smart.go`, `probe/net_share.go`),
`apps/server` (`modules/hooks/router.py`), `apps/desktop/ui` (`SecBackups.svelte`, `SecZfs.svelte`,
`CheckConfigFields.svelte`, `dictionaries.ts`), Doku `developer/monitoring.html` und `developer/agent.html` (DE+EN).

## Datenmodell / API / Migrationen
Keine Migration. Webhook-Trigger: der Statuscode für einen zu tief verschachtelten Body entspricht dem bestehenden 422
(derselbe Pfad wie ab 33 Ebenen); OpenAPI-Snapshot bleibt, solange kein Docstring der Route sich ändert.

## Trade-offs & Alternativen
R-1591: Prüfen an einer echten hängenden NFS-Freigabe wäre belastbarer, kostet aber eine VM mit absichtlich
blockiertem Mount; empfohlen ist, die Aussage einzuschränken und die Prüfung als Wunsch zu notieren.

## Risiken & Rollback
Gering; jede Task ist ein eigener Commit und einzeln zurücknehmbar.

## Doku-Impact
`developer/monitoring.html` und `developer/agent.html`, DE+EN (R-1590, R-1591). Changelog über
`changelog.d/klein-nachlese-14.md`.

## Offene Fragen
Keine.
