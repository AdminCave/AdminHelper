<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-7 — FreeBSD: rc.d-Dienste als Units im Inventar

Roadmap: R-1448. Stand `origin/main@30721a8bd`.

## Problem / Motivation
Die Discovery des Agenten meldet unter FreeBSD keine Units: `collectUnits`
(`apps/agent/internal/discovery/discovery.go:226`) gibt außerhalb von Linux und Windows eine leere Liste zurück.
Module, die über eine Unit erkannt werden (`haproxy`, `php_fpm`), binden auf FreeBSD/OPNsense deshalb nie, obwohl
der Unit-Sensor dort schon rc.d-Dienste misst (`measureRC`, `apps/agent/internal/probe/unit_rcd.go:94`).
Offen war die Namensregel zwischen Discovery und den Unit-Namen der Module (verschoben aus kern-agent-6).

## Ziel & Nicht-Ziele
**Ziel:**
1. Unter FreeBSD meldet die Discovery die eingeschalteten rc.d-Skripte (`service -e`) als Units: Name = Dateiname
   des Skripts, ohne Suffix; `active`/`running`, wenn `service <name> onestatus` einen Prozess nennt, sonst
   `inactive`/`dead`. Ein Skript ohne lesbaren Status fehlt in der Liste.
2. **Namensregel:** wie bei Windows. Ein Unit-Name ohne Punkt passt nur genau auf den Katalogeintrag
   `<name>.service` (`_listed_unit_wanted`, `apps/monitoring/app/discovery.py:329`). Die Instanz behält den bloßen
   Namen, und der Unit-Check fragt damit `service(8)`.
3. `haproxy` bindet damit ohne Änderung, denn das rc.d-Skript des Ports heißt `haproxy` (net/haproxy:
   `USE_RC_SUBR=haproxy`). `php_fpm` bekommt den Eintrag `php_fpm.service`, denn lang/php83 setzt
   `USE_RC_SUBR+=php_fpm`.

**Nicht-Ziele:**
- Die App-Checks von `haproxy` und `php_fpm` (Socket-Pfade, Status-Seite) auf FreeBSD-Pfade anpassen. Auf einem
  FreeBSD-Host können sie `unknown` melden, bis ein Fund es zeigt (dann eine eigene Zeile).
- Ausgeschaltete Skripte (`service -l`) melden: Module binden nur an laufende Units.
- Container, Pakete und vHosts unter FreeBSD.

## Betroffene Komponenten & Dateien
**Agent** (`apps/agent`):
- `internal/discovery/discovery.go` (`collectUnits` :226 und die Plattform-Schalter :75): neuer FreeBSD-Zweig.
- `internal/discovery/discovery_other.go`: Seam für die rc.d-Liste.
- `internal/probe/unit_rcd.go`: exportierte Liste `RCUnits` (`service -e` plus onestatus); `rcStatus` :52 teilt das Lesen der pids mit ihr.
  `internal/monitor` importiert `discovery` (`report.go`); den Parser von `internal/monitor/rcservice.go` (`parseRCEnabled`) kann `discovery` deshalb nicht nutzen, die Liste in `probe` ist eigenständig (Ledger, Entscheidungen).
- Tests: `internal/discovery/discovery_test.go`, `internal/probe/unit_rcd_test.go`.

**Monitoring** (`apps/monitoring`):
- `app/discovery.py` `_listed_unit_wanted` :329: Der Kommentar nennt FreeBSD neben Windows, die Logik bleibt.
- `app/catalog/modules/php_fpm.py`: `php_fpm` kommt in `_UNITS`, Version +1.
- Tests: `tests/test_discovery_match.py`.

Server, Desktop, Web: unverändert.

## Datenmodell / API / Migrationen
Keine Migration. Der Inventar-Vertrag bleibt (`units[] {name, state, sub}`), und Namen ohne Suffix gibt es seit
Windows. Ein alter Agent meldet unter FreeBSD weiter keine Units.

## Externe Integrationen
- service(8), https://man.freebsd.org/cgi/man.cgi?query=service&sektion=8: `-e` listet die eingeschalteten
  Skripte in rcorder-Reihenfolge. Das Ausgabeformat steht nicht in der Manpage. Der vorhandene Parser liest ganze
  Pfade und nimmt den Basisnamen; geprüft gegen releng/14.3 in kern-agent-4.
- Port-Makefiles: net/haproxy `USE_RC_SUBR=haproxy`, lang/php83 `USE_RC_SUBR+=php_fpm` (cgit.freebsd.org, gelesen
  2026-11-17).

## Trade-offs & Alternativen
- **Bloßer Name wie bei Windows (gewählt):** Der Server kennt die Regel schon, nur ein Katalogeintrag kommt dazu.
- **Agent hängt `.service` an:** Der Unit-Sensor bekäme dann `haproxy.service` und müsste es wieder abschneiden.
  Außerdem würden die systemd-Muster (`pm2-*.service`) auf rc.d-Namen greifen.
- **Eigenes Katalogfeld `rc_units`:** wäre ein Vertrag mehr und eine Modelländerung für einen einzigen
  abweichenden Namen.
- **Kosten:** ein `onestatus` je eingeschaltetem Skript und Discovery-Lauf. Das macht der Services-Check heute
  schon alle 5 min, und die Discovery läuft seltener. Ein Aufruf, der nicht antwortet, beendet die Liste
  (partial), so wie in `rcServiceHealth`.

## Risiken & Rollback
Gering, Rollback per Revert. Risiko: Das Inventar eines FreeBSD-Hosts bekommt Units, und Module mit gleichnamigem
Eintrag binden neu. Gemeint ist das so.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN, Absatz zu den Units des Inventars (:348): FreeBSD neben Windows.
`changelog.d/kern-agent-7.md`.

## Offene Fragen
Keine.
