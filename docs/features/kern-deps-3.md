<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-3 — npm-Abhängigkeiten von Web, Desktop-UI und Desktop-E2E auf aktuell

Zug `tasks/kern-deps-3.md` mit R-1039 und R-1040 (Kevin 2026-11-02: alles auf aktuelle LTS/Stable).

## Problem / Motivation

`npm outdated` am 2026-11-05 (Worktree auf `origin/main` @af8165ea):

| Paket | web | desktop/ui | aktuell |
|---|---|---|---|
| vitest, @vitest/coverage-v8, @vitest/ui | 4.1.11 | 4.1.11 | 5.1.0 |
| jsdom | 29.1.1 | 29.1.1 | 30.1.3 |
| @testing-library/jest-dom | 6.9.1 | 6.9.1 | 7.0.1 |
| @playwright/test | 1.60.0 | — | 1.64.1 |
| vite | 8.0.16 | 8.0.16 | 8.3.5 |
| svelte | 5.56.2 | 5.56.2 | 5.57.3 |
| eslint / typescript-eslint | 10.4.1 / 8.60.1 | gleich | 10.14.0 / 8.72.1 |
| @types/node | 25.9.2 | 25.9.2 | 26.6.6 |
| typescript | 6.0.3 | 6.0.3 | 7.0.2 (bleibt 6.0, Zeile) |

Dazu die Minors von prettier, svelte-check, eslint-plugin-svelte, globals, @sveltejs/vite-plugin-svelte,
@testing-library/svelte und den Geist-Schriften. In `apps/desktop/ui/package.json` stehen die Tauri-JS-Pakete schon
auf dem Stand der Rust-Crates (`@tauri-apps/api ^2.12.4` zu `tauri 2.12.5`, Plugins dialog 2.8.4, notification
2.8.0, shell 2.6.0 in `Cargo.lock`). Die Lizenztabelle in `THIRD_PARTY_LICENSES.md` nennt aber noch 2.11.0/2.7.1/
2.3.3/2.3.5 und @lucide/svelte 1.66.0, und die beiden Geist-Schriften (Laufzeit-`dependencies`) fehlen ganz.

`apps/desktop/e2e`: WebdriverIO 9 → 10.1.0 (R-1040), `@wdio/junit-reporter` ist auf 9.29.0 gepinnt. R-1040 verlangt,
das `undici`-Override aus R-1122 (`overrides.webdriver.undici ^8.12.3`) mit wdio 10 zu prüfen und, wenn es nicht
mehr nötig ist, zu entfernen.

## Ziel & Nicht-Ziele

Ziel:
- Jedes direkte npm-Paket der drei Manifeste steht auf dem aktuellen Release; TypeScript bleibt 6.0 (Zeile).
- Locks mit `npm install` neu erzeugt; `npm ci` läuft.
- Lint, Typprüfung und Tests jeder Komponente grün; die Lizenztabelle stimmt mit den ausgelieferten Paketen.

Nicht-Ziele:
- TypeScript 7.
- Der CI-Job `frontend-e2e` auf `ubuntu-26.04` (Notiz von R-1039): er ändert `.github/workflows/ci.yml`, das der
  offene PR #387 (`feature/ci-3`) ändert und Kevin merged. Er wird eine eigene Zeile im Zug `ci-4`, der ohnehin
  `.github/workflows/` ändert; Voraussetzung ist Playwright ≥ 1.61 aus diesem Zug.
- Node selbst (CI fährt 26, die Dev-Box 22.23.1, R-1086).

## Betroffene Komponenten & Dateien

- web: `apps/web/package.json`, `apps/web/package-lock.json`, Test-Setup (`apps/web/vitest.config.ts`,
  `apps/web/vitest.setup.ts`) und Tests nur, wo ein Release es verlangt.
- desktop-ui: `apps/desktop/ui/package.json`, `package-lock.json`, Test-Setup und Tests ebenso.
- desktop-e2e: `apps/desktop/e2e/package.json`, `package-lock.json`, `wdio.conf.js` und Specs nur, wo wdio 10 es
  verlangt.
- `THIRD_PARTY_LICENSES.md` (Abschnitt 4), `changelog.d/kern-deps-3.md`.

## Datenmodell / API / Migrationen

Keine. Kein API-Vertrag, keine Migration, kein sichtbares Verhalten.

## Externe Integrationen

- **Vitest 5** (vitest.dev/guide/migration): Node ≥ 22.12, Vite ≥ 6.4 als Peer; `clearMocks` steht jetzt auf
  `true`; `coverage.include/exclude` relativ zur Projektwurzel; json/junit-Reporter schreiben in Dateien; Configs
  werden nicht mehr in Elternverzeichnissen gesucht; `vitest/*`-Unterpfade (`vitest/environments` u. a.) sind weg;
  unawaited `expect.poll`/async-Assertions schlagen fehl. Beim Bau: Setup und Configs gegen diese Liste prüfen.
- **jsdom 30** (GitHub-Releases): nur Node `^22.22.2 || ^24.15.0 || >=26`.
- **jest-dom 7** (GitHub-Releases): `@testing-library/dom` ist Pflicht-Peer, Node ≥ 22.
- **WebdriverIO 10** (Release v10.0.0): Node ≥ 22.19, Mocha 12, `$` wirft bei mehreren Treffern, `executeAsync`
  entfernt, `browser.uploadFile` → `element.setFiles`, alte Command-Signaturen und Reporter-Globals entfernt.
  undici wird nicht erwähnt: das Override prüft T3 am Lock (`npm ls undici`).
- **Playwright 1.64**: Release-Notes beim Bau; die Specs laufen in der PR-CI (`frontend-e2e`).

## Trade-offs & Alternativen

- **Eine Komponente je Task:** jede Suite für sich, jeder Lock einzeln zurücknehmbar. Alternative: alle Majors in
  einem Commit — ein roter Lauf ließe offen, welches Paket schuld ist.
- **`clearMocks: true` (Vitest 5):** Tests, die sich auf Aufrufzähler über Tests hinweg verlassen, werden rot.
  Empfehlung: die Tests korrigieren statt den alten Standard zu setzen, wenn es wenige sind; sonst `clearMocks:
  false` mit Begründung unter `## Entscheidungen`.

## Risiken & Rollback

- Der Desktop-GUI-Lauf mit wdio 10 zeigt sich erst im Sammellauf (`Heavy: linux-full`); lokal laufen Lint und
  Unit-Tests von `apps/desktop/e2e`.
- Playwright 1.64 und die Web-E2E prüft die PR-CI.
- Rollback: ein Commit je Komponente, Revert genügt.

## Doku-Impact

`THIRD_PARTY_LICENSES.md` Abschnitt 4 (Versionen, Geist-Schriften mit ihrer Lizenz), `changelog.d/kern-deps-3.md`
(`### Changed`). Die Doku unter `docs/` nennt keine dieser Versionen (`grep` nach vitest/wdio/jsdom/playwright).

## Offene Fragen

Keine aus Kevins Bereich.
