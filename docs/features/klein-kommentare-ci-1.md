<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-ci-1 — ci.yml: drei veraltete Kommentare

Roadmap R-0847, R-0877, R-0927. Alle drei ändern nur Kommentare in `.github/workflows/ci.yml`, kein Schritt, keine
Bedingung. Weil die Datei ein Workflow ist, merged Kevin den PR (CLAUDE.md §2). `overlap.sh` ohne Treffer.

## Problem / Motivation
- **R-0847 / R-0877 (Teil 1):** Der Kommentar am Schritt `go vet (windows)` (Job `agent`) nennt als
  `//go:build windows`-Dateien nur den sc-query-Collector. Es sind inzwischen Dienst, Event-Log, Config-Pfade,
  Secure-Dir, Enroll-Lock, frpc-Plattform und der Collector (`apps/agent/**/*_windows.go`). Soll: der Kommentar
  nennt die Gruppen statt einer Einzeldatei.
- **R-0877 (Teil 2):** Der Schritt `No test skipped` zählt jedes `<skipped>` der JUnit-XML, auch einen `xfail`
  (pytest schreibt ihn als `skipped` mit `type="pytest.xfail"`). Heute gibt es in `apps/server` keinen `xfail`; das
  Verhalten ist aber unbeschrieben. Soll: der Kommentar nennt es und sagt, dass ein `xfail` den Schritt rot macht
  (bewusst, kein stilles Durchwinken). Der Exit-75-Anteil der Zeile (Keyring-Prüfung ohne automatischen Test) ist
  keine Kommentarfrage und fährt nicht mit.
- **R-0927:** Der Kommentar am Schritt `Shared API types in lockstep` nennt vier gemeinsame Typen samt `Server`;
  seit R-0723 sind es drei (`FrpConfig`, `FrpStatus`, `FrpStatusProxy`, siehe `apps/desktop/ui/scripts/sync-from-web.sh`).

## Ziel & Nicht-Ziele
- Drei Kommentare an den Stand bringen. Nicht-Ziel: ein Schritt, eine Bedingung oder ein Skript ändert sich; ein
  Gate für `xfail`.

## Betroffene Komponenten & Dateien
`.github/workflows/ci.yml` (Kommentare im Job `agent`, im Server-Job und im Job `desktop-ui`).

## Trade-offs
Ein `xfail` getrennt zählen wäre eine Verhaltensänderung des Gates und gehört in eine eigene Zeile; der Kommentar
hält den Ist-Stand fest.

## Risiken & Rollback
Kein Laufzeitrisiko; die CI lädt die Datei, ein YAML-Fehler fiele sofort auf. Rollback: Revert.

## Doku-Impact
Keine. `docs/developer/cicd.html` nennt weder die Typenzahl noch die Windows-Dateien (vor dem Bau gegrept).

## Offene Fragen
Keine.
