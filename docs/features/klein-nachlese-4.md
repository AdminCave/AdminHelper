<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-4

## Problem / Motivation
R-1414 (Nachlese der Pruefer von arch-monitoring-ui-3), vier Nits:
- `apps/monitoring/app/server_cleanup.py`: die Docstring-Zeile mit der Aufzaehlung der Tabellen ist 142 Zeichen lang, der Rest bricht frueher um.
- `ServiceList.test.ts` und `ConnectionEditor.tabs.test.ts`: `waitFor` wartet bis 30 s (testing.md, Fristen), vitest bricht den Test aber nach `testTimeout` (5 s) ab. Die Frist greift nie.
- `ServiceList.svelte`: bei leerem Inventar mit SSH-Verbindung stehen der Hinweis auf "Mehr Log" und die Verbindungswahl neben dem Leer-Zustand, obwohl es keine Zeile gibt, die den Knopf traegt.
- `monitoring-services.live.js` kopiert `setTheme`, `shot`, `fixtureAgentConf`, `createCheck`, `postReport` aus `monitoring-server-page.live.js`.

## Ziel & Nicht-Ziele
Ziel: je Nit der Zeile behoben. Nicht-Ziel: das Verhalten der Specs aendern (die Helfer ziehen nur um), ein neues Thema-Verhalten.

## Betroffene Komponenten & Dateien
`apps/monitoring/app/server_cleanup.py` (Kommentar); `apps/desktop/ui/src/components/monitoring/section/ServiceList.svelte` + `.test.ts`, `apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts`; `apps/desktop/e2e/test/specs/monitoring-services.live.js`, `monitoring-server-page.live.js`, neu `apps/desktop/e2e/test/lib/monitoring-live.js`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- Timeouts: je Test eine dritte Argumentfrist waere an 25+ Stellen noetig; ein `vi.setConfig({ testTimeout: 60_000 })` je Datei ist eine Zeile und haelt die 30-s-Regel. Empfehlung: setConfig.
- Helfer: die zwei Fassungen weichen ab (`setTheme`-Frist 5 s gegen WAIT, Praefix von `shot`, `createCheck` mit und ohne `config`). Der gemeinsame Helfer nimmt Praefix und Frist als Parameter; `createCheck` nimmt `config` optional. Die Specs behalten ihr heutiges Verhalten.

## Risiken & Rollback
Der E2E-Umzug laeuft nur auf einer GUI-Box (kein Display hier): er ist nicht lokal verifizierbar und geht in den naechtlichen Sammellauf (`Heavy: linux-full`). Rollback: Revert des Task-Commits.

## Doku-Impact
Keine (interne Tests, Kommentar, ein Hinweis, der nur bei leerem Inventar entfaellt).

## Offene Fragen
Keine. R-1429 (Dateien nur auf `feature/arch-monitoring-app-collector`) fuehrt der Zug nicht mit; sie wandert in klein-nachlese-5.
