<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-E2E unter Node 26: undici von webdriver 9 (2026-11-04) — Task-Ledger
Status: aktiv · Branch: feature/ref-node26-e2e-undici · Review: am Ende
Spec: Roadmap R-1122 · Quelle: Sammellauf 2026-11-03-1503 und 2026-11-04-0628, Teil gui
Heavy: linux-full — die GUI-Specs des nächsten Sammellaufs über `main` sind der Box-Beweis (alle scheitern heute beim Sessionstart); vor dem Merge beweist der Unit-Test unter Node 26 in der CI (Job Desktop, `E2E eslint`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### R1 — webdriver 9 öffnet unter Node 26 wieder eine Session  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json, apps/desktop/e2e/test/unit/session.test.js
Review: am Ende (Branch-Review)
Änderung: Ursache: webdriver 9.29 bringt undici 6.29 mit. Unter Node 26 (eingebautes undici 8.12) liefert dessen `getGlobalDispatcher()` Nodes `Dispatcher1Wrapper`; `FetchRequest.getDispatcher` nimmt jeden Dispatcher, der nicht `Agent` heißt, als Proxy-Dispatcher und gibt ihn an `fetch` aus undici 6, und das bricht mit `UND_ERR_INVALID_ARG` ab (`webdriver/build/node.js` `getDispatcher`). Seit d9120d94 (Node 26 auf den Testboxen, wie CI) scheitert damit jede GUI-Spec vor dem ersten Schritt. Fix: `overrides` hebt das undici von webdriver auf `^8.12.3` (wie webdriver 10; Engines `node >=22.19.0`); unter undici 8 heißt der globale Dispatcher wieder `Agent`. Die Hebung auf wdio 10 bleibt R-1040 (kern-deps-3) und nimmt den Override dann mit. Neuer Unit-Test: `WebDriver.newSession` gegen einen lokalen HTTP-Stub, unter Node 26 vor dem Fix rot (Gegenprobe mit dem Node-26-Binary 26.13.0), danach grün; in der CI läuft er unter Node 26 im Schritt `E2E eslint`.
Semantik: keine Stelle in docs/ — Testinfrastruktur; gewollt ist laut d9120d94 „bootstrap the test boxes with Node 26, as CI“, also Node 26 behalten und die Abhängigkeit passend machen.
Beweis: main@80541105 · `.ah-out/weekly/2026-11-04-0628/all-gui.log`: `WebDriverError: Request failed with error code UND_ERR_INVALID_ARG when running "http://localhost:4444/session" with method "POST"` in jedem GUI-Schritt, ebenso auf dem Basis-Commit e74aab15 derselben Box; lokal nachgestellt mit Node 26.13.0 (rot) gegen Node 22.23.1 (grün), mit undici 7.30.1 und 8.12.3 unter Node 26 grün
Dedup-Key: ref:desktop-e2e:node26:undici
HEAD: 68c55f09
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testinfrastruktur, kein sichtbares Verhalten)

## Entscheidungen
- Override statt wdio 10: der kleinste Eingriff, der die Ursache trifft (zu altes undici unter Node 26); wdio 10 ist ein Major-Sprung mit eigener Zeile R-1040 in kern-deps-3, den die Kern-Session baut. Node-Pin auf 24 verworfen: Kevin 2026-11-02 „alles auf aktuelle LTS/Stable“, CI läuft schon auf 26.
