<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-11

## Problem / Motivation
Nachlese-Zeilen aus den Reviews von `kern-monitoring-14` (Windows-Ansichten des Agents und Katalog):
- R-1460: `machineCerts` parst jedes Zertifikat mit dem x509-Parser; ein Zertifikat, das Go ablehnt, fällt still aus dem
  Ergebnis. `CertInfo` des Windows-Speichers trägt `NotBefore`/`NotAfter` ohnehin.
- R-1461: `name` (UTF-16-Zeiger) wird als `uintptr` an `CertOpenStore` gegeben; ohne `runtime.KeepAlive` darf der GC ihn
  währenddessen freigeben.
- R-1466, R-1483: `oleutil.GetProperty` liefert ein VARIANT, das `Clear()` freigeben muss (`MsrcSeverity` je Update,
  `Count`, `RebootRequired`, `LastSearchSuccessDate`): ein BSTR-Leck je Lauf.
- R-1467: `win_updates` teilt `wmiSlot` mit den WMI-Ansichten; eine hängende WUA-Suche blockiert `dhcp_scopes` und
  `rds_licenses`.
- R-1468: `TestTheHostSensorTakesTheWindowsViews` ruft `hostSensor` unter Windows wirklich auf (echte WUA-Suche, echter
  Ereignislog), um nur die Namen zu prüfen.
- R-1478: `windows-dns` trägt kein `detect.port_hints`; Port 53 erscheint neben dem Modul zusätzlich als Port-Fund.

## Ziel & Nicht-Ziele
Ziel: die sieben Zeilen. Nicht-Ziele: Werte, Regeln, Schwellen und Timeouts der Windows-Checks (R-1465, R-1476, R-1477,
R-1481, R-1484 sind Kevins Entscheidung bzw. brauchen eine Windows-Messung und stehen auf `blockiert` mit Frage).

## Betroffene Komponenten & Dateien
`apps/agent/internal/probe/certstore_windows.go`, `winviews_windows.go`, `winviews_test.go`;
`apps/monitoring/app/catalog/modules/windows_dns.py`, `apps/monitoring/tests/test_catalog_windows_server.py`,
`changelog.d/klein-nachlese-11.md`.

## Datenmodell / API / Migrationen
Keine. Die Agent-Werte bleiben gleich; `port_hints` ist ein vorhandenes Feld des Katalogs.

## Trade-offs & Alternativen
- R-1467: ein eigener Slot für die WUA-Suche (`wuaSlot`) statt eines gemeinsamen: eine hängende Suche kostet eine
  Goroutine, blockiert aber keine WMI-Ansicht. Alternative (Timeout der Suche) hängt an R-1484.
- R-1460: `CertInfo` statt x509-Parser; ein Zertifikat, das Go ablehnt, zählt jetzt mit.

## Risiken & Rollback
Die Windows-Dateien laufen nur auf Windows; lokal belegt sind `go vet`, die Linux-Tests und der Windows-Cross-Build
(`run.sh` Schritt go-agent). Die Laufzeitwirkung (Speicher, COM) ist hier nicht gemessen: nicht verifiziert auf Windows.

## Doku-Impact
Keine Seite beschreibt diese Interna; `changelog.d` für die Port-Entdeckung von `windows-dns`.

## Offene Fragen
Fünf Zeilen warten auf Kevin (Roadmap, `blockiert`): R-1465, R-1476, R-1477, R-1481, R-1484.
