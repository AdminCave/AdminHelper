# kern-monitoring-40 — benannte SQL-Server-Instanzen

Roadmap: R-1479 (R-1501 wanderte nach kern-monitoring-43: baut auf R-1406 auf, das bis nach 0.47.0 ruht).

## Problem
Das Modul `mssql` findet nur die Standardinstanz (Dienst `MSSQLSERVER`). Eine benannte Instanz läuft als Dienst
`MSSQL$<name>`; das `$` passt nicht in den Instanzschlüssel (`_INSTANCE_KEY` in
`apps/monitoring/app/discovery.py`), und die Erkennung nimmt Windows-Dienste nur beim exakten Namen.
Der Agent kann die Instanz schon fragen: `mssqlServiceRe` (`apps/agent/internal/probe/winviews.go`) und die
Dienstabfrage nehmen `MSSQL$<name>`.

## Ziel und Nicht-Ziele
- Ziel: jede benannte Instanz wird eine eigene Instanz des Moduls mit Dienst- und Ereignis-Check.
- Kevin 2026-11-17: Ersatzform statt `$` im Schlüssel. Der Dienst `MSSQL$<name>` wird zum Schlüssel
  `MSSQL-<name>`; Schlüsselregel, Credential-Referenz und Agent bleiben unverändert. Die Checks fragen weiter den
  echten Dienstnamen (`summary["unit"]`).
- Nicht-Ziel: Datenbankzustand, msdb-Backups, Express-Grenze (wie bisher).

## Betroffene Dateien
- `apps/monitoring/app/discovery.py`: suffixlose Dienste (Windows, rc.d) auch über ein Muster des Moduls
  (`MSSQL$*`); Schlüssel einer Unit-Instanz ohne `$` (Ersatz `-`), der Dienstname bleibt in der Summary.
- `apps/monitoring/app/module_sync.py`: das Ziel einer Instanz der eigenen Art kommt aus der Summary
  (`summary.get(kind, key)`), nicht mehr aus dem Schlüssel.
- `apps/monitoring/app/catalog/modules/mssql.py`: `detect.units` + `MSSQL$*`, Version 2, Docstring.
- Tests `apps/monitoring/tests/test_catalog_windows_roles.py`.
- Doku `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html` (Zeile `mssql`), `changelog.d/kern-monitoring-40.md`.

## Datenmodell / API
Keine Migration, keine API-Änderung. Bestehende Findings der Standardinstanz behalten ihren Schlüssel
`MSSQLSERVER`.

## Trade-offs
- Ersatzform (gewählt) gegen `$` im Schlüssel: kleiner, keine Validierung an drei Stellen weiten; Preis: der
  angezeigte Instanzname weicht vom Dienstnamen ab (`MSSQL-SHOP`).
- Ein Windows-Dienst `MSSQL-<x>` könnte theoretisch kollidieren; SQL Server vergibt solche Namen nicht.

## Risiken und Rollback
Muster für suffixlose Dienste greifen auch für rc.d-Skripte; heute nennt nur `pm2-*.service` ein Muster (systemd).
Rollback: Revert des Task-Commits. Nicht auf einem SQL Server verifiziert.

## Doku-Impact
Modultabelle (DE+EN) Zeile `mssql`: Erkennung nennt benannte Instanzen und die Schlüsselform. CHANGELOG-Fragment.

## Offene Fragen
Keine (Kevin 2026-11-17).
