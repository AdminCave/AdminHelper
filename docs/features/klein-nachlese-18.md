<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-18

## Problem / Motivation
Sieben Nits aus Abschlusspruefungen (alle REF: Testluecken, ein Anzeigefehler, Doku und Fragmente):
- R-1673: `apps/monitoring/tests/test_catalog_windows_server.py` (Tabelle ab Zeile 155) und
  `test_catalog_windows_roles.py` (Defender) pinnen zwei Entscheidungen von kern-agent-15 nicht: ein DHCP-Server
  ohne Scope sendet nur `scopes: 0`, der Check ist `unknown`; eine nie aktualisierte Signatur
  (`signature_age_d` 65535) ist `critical`.
- R-1674: `TestRPMScriptletsPassWithoutSystemd` (`apps/agent/cmd/adminhelper-agent/packaging_rpm_test.go`) prueft
  nur Exit-Codes. Dass `%postun` das Scheitern von `systemctl daemon-reload` still hinnimmt, belegt er nicht: die
  Stub-Meldung duerfte nicht in der Scriptlet-Ausgabe stehen.
- R-1675: Die Server-Kachel des Desktop-Dashboards (`Dashboard.svelte:109`) haengt an `monitoringKnown` (Checks),
  die Zahl kommt aber aus `loadServers`. Scheitert nur `/servers`, setzt `loadServers` `servers = []` und zeigt die
  Kachel 0 statt `-`.
- R-1669: `docs/developer/monitoring.html` DE+EN (Zeile 296) haengt zwei Klammern hintereinander an
  `history.server_events`; `changelog.d/kern-monitoring-53.md:12` sagt "desselben Objekts" statt "desselben Checks";
  `docs/features/ci-19.md:33` hat eine Zeile mit 145 Zeichen.
- R-1676: `changelog.d/kern-agent-17.md` und `kern-dashboard-1.md` sind englisch und ohne fetten Titel; die Form
  ist deutsch, umlautfrei, `- **Bereich: Titel:** Text` (`changelog.d/README.md`, `CHANGELOG.md`).
- R-1677: `docs/developer/agent.html` DE+EN nennen `internal/selfupdate`, `self-update-apply` und die
  Gesund-Marke des Windows-Self-Updates nicht.
- R-1685: `docs/features/kern-desktop-e2e-2.md:30` sagt, `waitUntil` breche beim ersten abgelehnten Aufruf ab;
  wdio wiederholt eine werfende Bedingung bis zum Timeout (`Timer._checkCondition`, belegt an 9.29.0).

## Ziel & Nicht-Ziele
Ziel: Tests pinnen das gewollte Verhalten, die Kachel zeigt `-` statt einer falschen 0, Doku und Fragmente
stimmen mit Code und Konvention ueberein. Nicht-Ziele: Agent- oder Katalogverhalten aendern, neue Features.

## Betroffene Komponenten & Dateien
monitoring (Tests), agent (Test), desktop-ui (Dashboard, Store, Test), docs, changelog.d.

## Datenmodell / API / Migrationen
Keine. Kein Vertrag aendert sich.

## Externe Integrationen
wdio (`waitUntil`; installiert 9.29.0, Lockfile 10.1.0): die Aussage in R-1685 wird gegen den Quelltext des
installierten Pakets belegt, nicht aus dem Gedaechtnis geschrieben.

## Trade-offs & Alternativen
R-1675: ein eigenes "Server-Liste geladen"-Signal im Store (`servers` bleibt `[]` bei Fehler, ein Zaehler traegt
nicht) statt die Kachel an `$monitoringError` zu haengen, weil dieser Fehler Checks meint. Empfehlung: kleines
Flag im Store, gesetzt von `loadServers`.

## Risiken & Rollback
Gering. Je Task einzeln zuruecknehmbar. R-1675 ist die einzige sichtbare Aenderung (Kachel `-` im Fehlerfall, wie
das Fragment `kern-dashboard-1.md` es schon beschreibt).

## Doku-Impact
`docs/developer/agent.html` DE+EN (Self-Update), `docs/developer/monitoring.html` DE+EN (Satzbau), zwei Specs,
drei Changelog-Fragmente. Kein eigenes Fragment: R-1675 erfuellt den Wortlaut von `kern-dashboard-1.md`.

## Offene Fragen
Keine.
