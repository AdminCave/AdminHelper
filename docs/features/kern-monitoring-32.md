<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-32 — Windows-Ansichten: leerer Bestand und Defender im Passivmodus

Roadmap: R-1475, R-1480. Stand `origin/main@30721a8bd`.

## Problem / Motivation
- **R-1475:** Drei Windows-Checks stehen bei leerem Bestand dauerhaft auf `unknown`. Der Agent lässt das Feld weg,
  wenn es nichts zu bewerten gibt, und `_rate` (`apps/monitoring/app/checkers/probe.py:168`) wertet eine Regel ohne
  Wert als `unknown`:
  - `windows-ad` / `replication`: ein einzelner DC ohne eingehende Verbindung meldet kein `oldest_success_age_s`
    (`repadminValues`, `apps/agent/internal/probe/winviews.go`).
  - `windows-host` / `certs`: ein leerer Speicher LocalMachine\My meldet kein `min_days_left` (`machineCertValues`).
  - `windows-rds` / `licenses`: ohne gezählte Packs fehlt `used_pct`, ohne ablaufendes Pack `min_days_left`
    (`rdsValues`).
  Kevin 2026-11-16 (Triage): leerer Bestand ist ok, nicht unknown.
- **R-1480:** `defender` / `status` wird kritisch, sobald `realtime_on` false ist. Im Passivmodus (Defender neben
  einem anderen Virenscanner) blockiert der Echtzeitschutz laut Microsoft nicht; ohne Endpoint DLP heißt er dort
  „Disabled“ (learn.microsoft.com/en-us/defender-endpoint/microsoft-defender-antivirus-compatibility, Tabelle mit
  Note 1). Welchen Wert `MSFT_MpComputerStatus.RealTimeProtectionEnabled` dann meldet, sagt keine Microsoft-Seite
  (nicht verifiziert). Der Agent meldet `passive` schon, wenn `AMRunningMode` „Passive“ enthält.

## Ziel & Nicht-Ziele
**Ziel:**
1. Eine Katalog-Regel kann sagen, dass ein fehlender Wert ok ist (`if_absent: "ok"`). Die drei Felder oben nutzen das.
2. Eine Katalog-Regel kann sagen, dass sie nicht gilt, solange ein anderes Feld desselben Ergebnisses einen Wert hat
   (`unless: {"field": …, "value": …}`). Die Echtzeitschutz-Regel von `defender` gilt nicht bei `passive` = true.
3. Beides wirkt mit den Agenten, die heute laufen: der Agent bleibt unverändert.

**Nicht-Ziele:**
- Kein neutraler Wert vom Agenten (wie `last_success_age_s` = 0 bei Samba, R-1491): ein „0 Tage“ für `min_days_left`
  wäre kritisch, und alte Agenten blieben unknown.
- Andere Module mit demselben Muster (etwa `caddy` / `certs`) bleiben wie sie sind; Folgezeile, falls ein Fund es zeigt.
- Kein eigener Zustand „passiv“ im Agenten; die Karte zeigt weiter `realtime_on`.

## Betroffene Komponenten & Dateien
**Monitoring** (`apps/monitoring`):
- `app/catalog/model.py`: `Rule` :135 (`_value_fits_op` :145), Prüfung der Regelfelder :278.
- `app/checkers/probe.py`: `_rule_holds` :125, `_rate` :168.
- `app/check_configs.py`: `ProbeConfig.rules` :207 nimmt `Rule` aus dem Katalog, die Optionen kommen mit.
- Module `windows_ad.py`, `windows_host.py`, `windows_rds.py`, `defender.py`: Regeln, Version +1, Docstring.
- Tests: `tests/test_catalog.py`, `tests/test_probe_checker.py`, `tests/test_catalog_windows_server.py`,
  `tests/test_catalog_windows_roles.py`.

Agent, Server, Desktop, Web: unverändert.

## Datenmodell / API / Migrationen
Keine Migration. `Rule` bekommt zwei optionale Felder; beide fehlen in der Serialisierung, solange sie nicht gesetzt
sind (Muster `Credential._optional_only_when_set`), damit die Hashes der übrigen Module gleich bleiben. Die Check-API
nimmt sie über `ProbeConfig.rules` mit; `tests/openapi.snapshot.json` enthält das Regelschema nicht (geprüft).
Die Modulversionen steigen, `module_sync` zieht angenommene Instanzen nach.

## Trade-offs & Alternativen
- **Regel-Option statt Agent-Wert (gewählt):** wirkt sofort mit allen Agenten; der Preis: fällt ein Feld aus einem
  anderen Grund weg (Agent-Fehler), bleibt die Regel stumm. Der Agent meldet bei einem Fehler aber einen
  Fehlerstatus statt eines Ergebnisses ohne Feld, und `if_absent` steht nur an den drei Feldern, deren Fehlen
  „nichts zu bewerten“ heißt.
- **`unless` statt eines neuen Agent-Feldes:** ein Feld `realtime_enforced` bräuchte einen neuen Agenten und ließe
  alte unknown.

## Risiken & Rollback
Gering; Rollback per Revert. Ein Passivmodus, den der Agent nicht erkennt (`AMRunningMode` fehlt bei alten
Defender-Versionen), bleibt kritisch wie heute.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN: Zeilen `windows-ad`, `windows-host`, `windows-rds`, `defender`; Abschnitt zu den
Regeln des Katalogs, falls er die Bewertung ohne Wert beschreibt. `changelog.d/kern-monitoring-32.md`.

## Offene Fragen
Keine. R-1391 (wartet auf R-1413, arch-monitoring-ui-4) und R-1479 (Frage an Kevin zum Instanzschlüssel) fahren
nicht mit.
