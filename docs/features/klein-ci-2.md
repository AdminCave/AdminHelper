<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ci-2 — Spec

## Problem
**R-1328:** Am 2026-11-11 scheiterten apt-Schritte der PR-CI an einem DNS-Ausfall der Runner (`Temporary failure
resolving` für `*.ubuntu.com`). Die Schritte „Tauri system dependencies“ und „Install Playwright browsers“ laufen
inzwischen mit `Acquire::Retries`, `Acquire::http::Timeout` und `.github/scripts/retry.sh` (R-1130, R-1160). Im Job
der Shell-Tests (`.github/workflows/ci.yml`) sind es noch „Install minisign“ (`apt-get update -qq && apt-get install
-y -qq minisign`) und „Install gnome-keyring“: ein Fehlversuch dort rottet den Job ohne zweiten Anlauf.

## Ziel / Nicht-Ziele
- Beide Schritte holen ihre Pakete wie die übrigen apt-Schritte der Datei: `apt_opts` mit `Acquire::Retries=3` und
  `Acquire::http::Timeout=30`, `update` und `install --download-only` unter `retry.sh 3 180`, das Installieren selbst
  (dpkg) ohne `retry.sh` (ein Kill darf dpkg nie treffen, Kommentar im Kopf von `retry.sh`).
- Kein neues Skript, keine Änderung an `release.yml` (anderer Workflow, nicht Teil der Zeile).

## Dateien
`.github/workflows/ci.yml` (ohne CHANGELOG-Eintrag: CI-Interna).

## Doku-Impact
Keine: CI-Interna. Der Merge ist Kevins (ändert `.github/workflows/`, CLAUDE.md §2).

## Risiken
Ein Syntaxfehler im Workflow rottet alle Jobs; die PR-CI zeigt das sofort. Rollback: Revert des Commits.
