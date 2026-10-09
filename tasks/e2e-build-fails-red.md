<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-E2E: ein gescheiterter Build macht den Lauf rot — Task-Ledger
Status: geplant · Branch: feature/e2e-build-fails-red · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0259 (Kurz-Ledger ohne Spec)
Heavy: linux-full — der Start jedes Desktop-E2E-Laufs ändert sich (`onPrepare` in `wdio.conf.js`); auf einer Pool-VM `run.sh e2e` mit `desktop_e2e_tunnel`: der Build gelingt, die Specs laufen wie bisher. Dazu eine Gegenprobe auf derselben Box: ein Wegwerf-Stand, der nicht kompiliert (eine unbenutzte Variable in der UI, wie im Beweis), muss den Schritt rot machen; im Log steht `tauri build failed`, kein Spec meldet `PASSED`. Der Wegwerf-Worktree bekommt nur Links und Kopien, dort wird nichts committet, danach wird er mit vollem Pfad entfernt.
DoD je Task: CLAUDE.md (Tests grün, ESLint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die aus der Gegenprobe von
R-0246 stammt. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@33cf47b6, wdio-Quelltext `@wdio/cli` 9.29.0 (die installierte Version, `package-lock.json`).

### T1 — `onPrepare`: ein gescheiterter `cargo tauri build` bricht den wdio-Lauf ab (R-0259)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/test/unit/onprepare.test.js, apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json, apps/desktop/e2e/README.md, CHANGELOG.md
Änderung: `onPrepare` (`wdio.conf.js:101-113`) baut die App und wirft bei Exit ≠ 0 `new Error("tauri build failed …")`
(`:112`). wdio fängt das ab und läuft weiter:
- `runLauncherHook` (`@wdio/cli/build/index.js:354-370`) schreibt jeden Fehler als „Error in hook“ ins Log. Weiter
  wirft es ihn nur, wenn er eine `SevereServiceError` aus `webdriverio` ist (Import `:28`).
- Das gilt für `onPrepare` der Config (`:867`). Ein gewöhnlicher Fehler geht also verloren, die Worker starten mit dem
  Binary, das noch von einem früheren Lauf unter `src-tauri/target/debug/` liegt.
- Eine `SevereServiceError` dagegen wirft der Launcher weiter (`:900-904`), und `launch()` endet mit `process.exit(1)`
  (`:1544-1556`).
- Die Doku sagt dasselbe für Service-Hooks (webdriver.io/docs/customservices, „Service Error Handling“): „An Error
  thrown during a service hook will be logged while the runner continues.“ Eine `SevereServiceError` aus `webdriverio`
  „can be used to stop the runner“. Für die Hooks der Config sagt die Doku nichts, dort gilt der Quelltext oben.

Der Plan folgt der Empfehlung zu offener Frage 1, Weg (a):
- `onPrepare` wirft bei gescheitertem Build eine `SevereServiceError` (`import { SevereServiceError } from
  'webdriverio'`), mit dem bisherigen Text.
- `wdio run` endet dann mit Exit 1, bevor ein Worker startet. Jeder Orchestrator wertet diesen Exit schon aus, etwa
  `desktop_e2e_tunnel.sh:75-76` (`… npx wdio run … && ok … || bad …`), `run.sh` den Schritt `desktop-e2e-smoke` über
  `npm test`. Keiner von ihnen ändert sich.
- `webdriverio` kommt heute nur transitiv über `@wdio/cli`. Es wird direkte devDependency mit demselben Bereich wie die
  `@wdio`-Pakete (`^9.19.0`); im Lockfile ändert sich nur der Wurzel-Eintrag, die Version bleibt 9.29.0.

Test (neu, SPDX-Header), `test/unit/onprepare.test.js` mit `node:test`, ohne Display und ohne Rust:
- Ein falsches `cargo` steht vorn im `PATH` (`onPrepare` startet über die Shell); `AH_OUT_DIR` zeigt in ein eigenes
  Temp-Verzeichnis, das der Test am Ende mit vollem Pfad löscht.
- `cargo` endet mit 1: `config.onPrepare()` wirft, der Fehler ist `instanceof SevereServiceError` aus `webdriverio`
  und nennt `tauri build failed (1)`. Rot vor dem Fix: heute ist es ein gewöhnlicher `Error`.
- `cargo` endet mit 0: `onPrepare` wirft nicht.
- `@wdio/cli` lädt dieselbe `webdriverio`-Kopie wie die Config: unter `node_modules/@wdio/cli/` liegt kein eigenes
  `node_modules/webdriverio`. Sonst wäre die Klasse eine andere, `instanceof` schlüge fehl, und der Lauf liefe still
  weiter wie heute.

Der Test läuft in `npm run lint` mit (offene Frage 2, Weg (a)): `"test:unit": "node --test …"`, `"lint": "eslint . &&
npm run test:unit"`. Damit fahren ihn der Schritt `desktop-e2e-lint` in `run.sh quick` und der CI-Schritt „E2E
eslint“, ohne Änderung an `run.sh` oder `ci.yml`.

Doku: Der README-Absatz zu `onPrepare` (`README.md:101-105`) bekommt einen Satz: Ein gescheiterter Build bricht den
Lauf ab, die Specs laufen nie gegen ein älteres Binary. CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis: feature/desktop-e2e-reenroll@a1f66cbc, Wegwerf-Stand ohne `stopTunnel()` in `onEnroll`, der Import blieb
stehen. Auf einer Pool-VM `iter.sh e2e --step desktop_e2e_tunnel`, Log der Gegenprobe vom 2026-10-09:
- `Error: 'stopTunnel' is declared but its value is never read. (ts)`: der Build scheitert;
- `2026-10-09T16:42:43.558Z ERROR @wdio/cli:utils: Error in hook: Error: tauri build failed (1)`, ebenso vor dem
  zweiten Spec;
- `[0-0] PASSED in undefined - file:///test/specs/settings-enroll.live.js`;
- `desktop_e2e_tunnel: 9 passed, 0 failed` und `run.sh[e2e]: 1 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns`.

Die Specs liefen mit dem Binary aus dem echten Lauf davor. Auf HEAD zeigt es der neue Test aus T1 ohne VM: rot vor dem
Fix.
HEAD: 33cf47b6
Semantik: `docs/developer/cicd.html:82-84`: „Ein blankes `exit 0` wäre ein grünes PASS, obwohl nichts lief – so
blieben die sieben Desktop-GUI-Suiten und `agent_install_test.sh` monatelang unsichtbar.“ Hier lief etwas, aber nicht
der Stand, der geprüft werden sollte. Die Komponenten-Doku `apps/desktop/e2e/README.md:101-105`: „`wdio.conf.js`
(`onPrepare`) runs `cargo tauri build --debug --no-bundle --config tauri.e2e.conf.json` in `../src-tauri` (…), so the
binary tauri-driver launches (`../src-tauri/target/debug/adminhelper`) is always current.“ Weitere Stellen zur
Desktop-E2E unter docs/ gibt es nicht (gesucht: `wdio`, `onPrepare`, `desktop_e2e`, `.live.js`).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: apps/desktop/e2e/README.md (onPrepare-Absatz) · CHANGELOG.md (Fixed)
