<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-server-7 — Spec

## Problem
Alle drei Zeilen betreffen `apps/server/tests/test_frps_supervisor.py`.
- **R-1307:** Das Warten auf die Proxy-Listen nach einem Dashboard-Poll (`_with_dashboard`, Z. 1554) und weitere
  Poll-Waits (Z. 1602, 1643, 1829) haben die 10-s-Standardfrist `WAIT`; auf einem langsamen Runner scheiterte das mit
  einem Timeout (R-1293 liefert dafür die Diagnose `dashboard requests seen`).
- **R-1356:** Z. 1181 wartet nach `box.write_input()` mit der 10-s-Standardfrist auf `running`, derselbe
  Übernahmeweg, den R-1308 für den Nachbartest auf 30 s hob.
- **R-1357:** `test_no_process_carries_the_password_of_the_dashboard_on_its_command_line` fiel in der CI (Lauf
  43169329319) an `assert all(... /api/proxy/ in call ...)`: Der Plugin-Check `curl … --output /dev/null
  http://127.0.0.1:<port>/healthz` blieb im Aufrufprotokoll. **Ursache:** `_without_plugin_checks` erwartet den Port
  `box.policy_port`. `_free_port()` gibt den Port frei, und der Dashboard-Stub bindet danach womöglich dieselbe Nummer;
  dann hebt der Supervisor den Plugin-Port um eins (`plugin_port`, `apps/frps/frps-supervisor.sh` Z. 305: kein Port von
  `webServer.port`), und der Check läuft auf `policy_port + 1` am Filter vorbei (im Log: Dashboard 34397, Check 34398).

## Ziel / Nicht-Ziele
- Die genannten Waits bekommen eine Obergrenze von 30 s (`3 * WAIT`, Abfrage bleibt kurz getaktet, `testing.md`).
- `_without_plugin_checks` erkennt den Plugin-Check am Pfad (`--output /dev/null http://127.0.0.1:<Port>/healthz`),
  nicht an einer Portnummer. Die Prüfung auf Zugangsdaten in den übrigen Aufrufen bleibt unverändert.
- Kein Produktcode, `WAIT` bleibt.

## Dateien
`apps/server/tests/test_frps_supervisor.py`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Statt des Filters könnte der Test einen freien Port erzwingen, der nicht der des Dashboards ist; das verlangt einen
Eingriff in die Fixtures. Der Pfad ist das stabile Merkmal des Plugin-Checks (`plugin_answers` im Supervisor).

## Risiken & Rollback
Wackler-Fixes gelten nach 50 grünen Läufen (`testing.md`), Beleg im Commit-Body. Je Task ein Commit, per Revert
rückgängig.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
