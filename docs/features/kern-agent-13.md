# kern-agent-13: Agent Linux und FreeBSD, Ordner-Overrides nur in Testläufen

Roadmap: R-1655 (wie R-1645 unter Windows), R-1656 (Nit aus kern-windows-3).

## Problem / Motivation
`apps/agent/internal/config/paths_linux.go` und `paths_freebsd.go` nehmen `ADMINHELPER_MONITOR_DIR`,
`ADMINHELPER_FRP_DIR` und `ADMINHELPER_LOG_DIR` aus der Umgebung. Sie gibt es nur für die Unit-Tests. Unter Windows
gelten sie seit kern-windows-3 nur noch in Testläufen; Linux und FreeBSD sollen sich gleich verhalten
(Kevin 2026-11-19).

## Ziel & Nicht-Ziele
- **Ziel (T1):** Auf allen Plattformen liest der Agent die Overrides nur in einem Testbinary (`testing.Testing`).
  Der Seam (`overridesAllowed`, `override`) zieht dafür aus `paths_windows.go` nach `paths.go`.
- **Ziel (T1, R-1656):** Der Kommentar an `EnsureDataDir` (`securedir_windows.go`) nennt den Ordner außerhalb der
  Wurzel als Testfall.
- **Doku:** Der Satz zu gesetzten Overrides bei `--purge` in `docs/developer/agent.html` (DE+EN) ist seit
  kern-windows-3 falsch und entfällt.
- **Nicht-Ziel:** andere Umgebungsvariablen des Agents (`LOG_LEVEL`).

## Betroffene Komponenten & Dateien
`apps/agent/internal/config/paths.go`, `paths_linux.go`, `paths_freebsd.go`, `paths_windows.go`,
neuer Test `paths_override_test.go` (SPDX), `securedir_windows.go` (Kommentar),
`docs/developer/agent.html`, `docs/en/developer/agent.html`, `changelog.d/kern-agent-13.md`.

## Datenmodell / API / Migrationen
Keine. Kein Skript, Workflow oder Paket startet ein gebautes Binary mit diesen Variablen (geprüft per
`git grep` über `scripts/`, `.github/`, `*.sh`, `*.yml`); die Tests setzen sie per `t.Setenv` im Testbinary.

## Externe Integrationen
`testing.Testing`: <https://pkg.go.dev/testing#Testing>.

## Trade-offs & Alternativen
Ein gemeinsamer Seam in `paths.go` statt dreier Kopien. Alternative Build-Tag: siehe kern-windows-3.

## Risiken & Rollback
Wer unter Linux oder FreeBSD die Ordner per Variable umgelenkt hat, bekommt die festen Pfade. Rollback ist ein
Revert.

## Doku-Impact
`docs/developer/agent.html` DE+EN, CHANGELOG.

## Offene Fragen
Keine.
