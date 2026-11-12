<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ci-4 — Spec

## Problem
- **R-1396**: Seit kern-harness-8 fährt `scripts/tests/run.sh` die vier Tests `.github/scripts/{retry,apt_archives_verify,
  tauri_cli_pins,cache_settings}_test` im `scripts`-Block (`AH_SCRIPT_TESTS_DEFAULT`). Der Job `Hermetic shell tests`
  in `.github/workflows/ci.yml` ruft sie danach noch einmal einzeln auf: vier Schritte, die dasselbe ein zweites Mal
  laufen lassen.

## Ziel / Nicht-Ziele
Die vier Einzelschritte (`retry.sh test`, `apt_archives_verify.sh test`, `tauri_cli_pins.sh test`,
`cache_settings.sh test`) fallen aus `ci.yml`; der Aggregator-Schritt deckt sie weiter ab. Keine weitere Änderung am
Workflow.

## Dateien
`.github/workflows/ci.yml` (Kevin merged den PR).

## Datenmodell / API / Migrationen
Keine.

## Doku-Impact
Keiner: `cicd.html` (DE+EN) nennt `cache_settings_test.sh` als Test des Wächters, nicht als CI-Schritt.

## Risiken & Rollback
Gering. Fehlt einer der vier Tests in `AH_SCRIPT_TESTS_DEFAULT`, liefe er in CI gar nicht mehr; die Task prüft das
vor dem Löschen an `run.sh` und an einem `--strict`-Lauf des `scripts`-Blocks. Rollback: Revert der Task.

## Offene Fragen
Keine.
