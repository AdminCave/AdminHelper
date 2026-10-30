<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Abhängigkeiten: npm-Audit wieder grün

Zug `kern-deps-1` (Roadmap R-0922). Stand: `origin/main@33295e76`.

## Problem / Motivation

Der wöchentliche `audit.yml`-Lauf vom 2026-10-26 ist rot: der Job „npm audit (web + desktop-ui)“ scheitert an
`npm audit --audit-level=high` (`.github/workflows/audit.yml:99`, `:103`, `:109`). Ursache in allen drei Lockfiles
ist `undici` (high, mehrere Advisories, behoben ab 7.30.1 bzw. 6.29.1): in `apps/web` und `apps/desktop/ui` über
`jsdom@29.1.1` → `undici@7.30.0`, in `apps/desktop/e2e` über `webdriverio@9.29.0` → `cheerio` (`undici@7.30.0`)
und `webdriver` (`undici@6.29.0`). Dazu moderate Funde mit Fix innerhalb der Semver-Grenzen: `vitest`,
`@vitest/mocker`, `@vitest/coverage-v8` (behoben in 4.1.12) und `ip-address` (e2e). Die übrigen Funde sind `low`
und ohne Fix im Semver-Rahmen (`deepmerge`, `@sveltejs/vite-plugin-svelte`; `serialize-javascript` über `mocha`
nur mit dem Major-Sprung von `@wdio/mocha-framework`).

## Ziel & Nicht-Ziele

Ziel: `npm audit --audit-level=high` ist in allen drei Verzeichnissen grün; moderate Funde mit Fix im
Semver-Rahmen gleich mit. Nicht-Ziele: Major-Sprünge (`@wdio/mocha-framework` 10), die `low`-Funde ohne Fix,
Änderungen an `audit.yml`.

## Betroffene Komponenten & Dateien

Nur Lockfiles: `apps/web/package-lock.json`, `apps/desktop/ui/package-lock.json`,
`apps/desktop/e2e/package-lock.json`. `package.json` bleibt, die Bereiche (`^4.1.11`, `^29.0.2`, `^9.29.0`)
erlauben die Fix-Versionen.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

npm-Registry; Advisories GHSA-4qv8-2p9j-2685, GHSA-2m5v-pch6-74hx u. a. (undici), GHSA-qxg6-89mg-rqv8 (vitest).

## Trade-offs & Alternativen

`npm audit fix` ohne `--force` je Verzeichnis (nur Patch-/Minor-Sprünge im Lockfile). Alternative: `overrides`
in `package.json` — verworfen, solange der normale Semver-Rahmen den Fix trägt; ein Override veraltet still.

## Risiken & Rollback

Testwerkzeuge (vitest, jsdom-Unterbau, webdriverio-Unterbau) wechseln Patch-Versionen; die Suiten der Komponenten
zeigen Brüche, die GUI-E2E der Sammellauf. Jede Task ein Commit, einzeln zurücknehmbar.

## Doku-Impact

Keine (nur Lockfiles von Test- und Build-Werkzeugen, kein dokumentiertes Verhalten).

## Offene Fragen

Keine.
