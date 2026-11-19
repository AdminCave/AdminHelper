# kern-windows-2: Agent Windows, Datenpfade aus der Known-Folder-API

Roadmap: R-1605 (Härtung nach kern-windows-1).

## Problem / Motivation
`apps/agent/internal/config/paths_windows.go` baut `MonitorDir`, `FrpDir` und `LogDir` aus der
Umgebungsvariablen `ProgramData`. Die Ordner des Agents sollen aus derselben Quelle kommen, die
`service uninstall --purge` schon nimmt (`service_windows.go`, `Purge`): `windows.KnownFolderPath`.
Die Umgebung bestimmt sie nicht.

## Ziel & Nicht-Ziele
- **Ziel (T1):** Die Vorgabe-Pfade unter Windows kommen aus `KnownFolderPath(FOLDERID_ProgramData)`.
- **Frage an Kevin (T2):** Wie verhalten sich die Overrides `ADMINHELPER_*_DIR` unter Windows? Sie sind
  dokumentiert (`docs/admin/agent-deployment.html`, Abschnitt Deinstallieren), eine Änderung ist also
  sichtbares Verhalten.
- **Nicht-Ziel:** Linux und FreeBSD. Dort sind die Pfade fest und hängen nicht an der Umgebung.

## Betroffene Komponenten & Dateien
`apps/agent/internal/config/paths_windows.go` und ein neuer Test `paths_windows_test.go`.

## Datenmodell / API / Migrationen
Keine. Auf einem normalen Windows liefert die Known-Folder-API denselben Pfad wie `%ProgramData%`.

## Externe Integrationen
`SHGetKnownFolderPath` / `FOLDERID_ProgramData`:
<https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid>, in Go über `golang.org/x/sys/windows`.
Das Paket nutzt `service_windows.go` schon.

## Trade-offs & Alternativen
Der Pfad wird einmal je Prozess bestimmt. Scheitert die API, was praktisch nicht vorkommt, nimmt der Agent den
festen Windows-Standard `C:\ProgramData` und nicht die Umgebung. Alternative wäre ein Fehler, aber die
Pfad-Funktionen liefern heute einen String an rund zwanzig Aufrufer; eine Fehler-Signatur wäre ein großer Umbau ohne
Gewinn.

## Risiken & Rollback
Ein Host, auf dem `ProgramData` absichtlich umgebogen war, nimmt nach dem Update den Systemordner.
Rollback ist ein Revert.

## Doku-Impact
`docs/admin/agent-deployment.html` (DE+EN): ein Satz, dass die Datenordner unter Windows über die
Windows-Ordnerpfade bestimmt werden. Dazu `changelog.d/kern-windows-2.md`.

## Offene Fragen
- T2: Overrides `ADMINHELPER_*_DIR` unter Windows (siehe Ledger).
