# kern-windows-3: Agent Windows, Ordner-Overrides nur in Testläufen

Roadmap: R-1645 (Härtung nach kern-windows-2).

## Problem / Motivation
`apps/agent/internal/config/paths_windows.go` nimmt `ADMINHELPER_MONITOR_DIR`, `ADMINHELPER_FRP_DIR` und
`ADMINHELPER_LOG_DIR` aus der Umgebung. Sie gibt es, damit die Unit-Tests gegen ein `t.TempDir()` laufen. Ein
Agent-Lauf außerhalb der Tests soll die Ordner nur aus der Known-Folder-API nehmen (kern-windows-2).

## Ziel & Nicht-Ziele
- **Ziel:** Unter Windows gelten die Overrides nur in Testläufen (Kevin 2026-11-19). Ein gebautes Binary ignoriert
  sie, ob erhöht oder nicht.
- **Nicht-Ziel:** Linux und FreeBSD (Pfade dort fest, Overrides unverändert).

## Betroffene Komponenten & Dateien
- `apps/agent/internal/config/paths_windows.go`: Overrides nur, wenn `testing.Testing()` wahr ist (Go 1.21+).
- `apps/agent/internal/config/paths_windows_test.go`: Test mit abgeschaltetem Testseam.
- `apps/agent/internal/service/service_windows.go`: Der Hinweis in `Purge` auf gesetzte Overrides entfällt.
- `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`: Der Satz zu den Overrides beim
  Deinstallieren entfällt.
- `changelog.d/kern-windows-3.md`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
`testing.Testing`: <https://pkg.go.dev/testing#Testing>. Es ist nur in einem von `go test` gebauten Binary wahr.

## Trade-offs & Alternativen
- **Empfehlung:** `testing.Testing()` über eine Paketvariable `overridesAllowed`. Die Tests der anderen Pakete
  (`frpc`, `logging`, `enroll`, `cmd`) setzen die Variablen weiter mit `t.Setenv`, ohne Umbau.
- Ein Build-Tag müsste in jedem Testlauf mitgegeben werden (CI, `verify.sh`). Ein Seam in `export_test.go`
  wäre nur im Paket `config` sichtbar.

## Risiken & Rollback
Wer unter Windows die Ordner per Variable umgelenkt hat, bekommt nach dem Update die Systemordner. Das ist
gewollt. Rollback ist ein Revert.

## Doku-Impact
`agent-deployment.html` DE+EN (Abschnitt Deinstallieren), CHANGELOG.

## Offene Fragen
Keine (Kevin 2026-11-19).
