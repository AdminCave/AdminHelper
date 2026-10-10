<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-E2E: ein Launcher-Test hält fest, dass ein gescheiterter Build den wdio-Lauf stoppt — Task-Ledger
Status: aktiv · Branch: feature/e2e-launcher-test · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-10 (kleines Fund-Paket aus R-0260, aus Kevins Triage 2026-10-10; nur ein Test und eine README-Zeile, kein sichtbares Verhalten; Bau durch Worker B statt den Loop, Umsetzungsweg der Aufsicht; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0260 (Kurz-Ledger ohne Spec)
Heavy: none — ein neuer Test in `npm run lint`. Er startet den wdio-Launcher mit einem falschen `cargo` und braucht weder Display noch Rust noch Netz: Er endet, bevor ein Worker startet, die Probe lief in einem Netz-Namespace ohne Netz. Kein Code der App, keine Desktop-Journey und kein Live-Spec ändern sich.
DoD je Task: CLAUDE.md (Tests grün, ESLint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-10 als
Loop-Futter triagiert hat. Sie stammt aus dem Opus-Review von R-0259 (Nit 2). Die private Roadmap ist in diesem
Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@128b7fb5.

### T1 — `test/unit/launcher.test.js`: ein gescheiterter Build stoppt `wdio run`, bevor ein Worker startet (R-0260)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/unit/launcher.test.js, apps/desktop/e2e/README.md
Änderung: `test/unit/onprepare.test.js` (R-0259) hält nur die eigene Seite fest: `onPrepare` wirft eine
`SevereServiceError` aus derselben `webdriverio`-Kopie, die `@wdio/cli` lädt (`:40`, `:57`). Dass der Launcher genau
diese Klasse weiterwirft und dann keinen Worker startet, steht im Quelltext von `@wdio/cli` 9.29.0. Ein künftiges
`@wdio/cli` könnte das ändern, und der Test bliebe grün. Heute pinnt das Lockfile 9.29.0.

Ein zweiter Test fährt deshalb den echten Launcher:
- `node node_modules/@wdio/cli/bin/wdio.js run wdio.conf.js --spec test/specs/smoke.e2e.js` per `spawnSync` mit
  `process.execPath`, im e2e-Verzeichnis. Kein `npx`, damit nichts nachgeladen wird.
- Ein falsches `cargo` steht vorn im `PATH` und endet mit 1. `onPrepare` startet es über die Shell
  (`wdio.conf.js:102-116`).
- `TAURI_DRIVER_BIN` zeigt auf ein falsches tauri-driver, das beim Start eine Marker-Datei anlegt und mit 1 endet
  (`wdio.conf.js:124-125`).
- `AH_OUT_DIR` zeigt in ein eigenes Temp-Verzeichnis, das der Test am Ende mit vollem Pfad löscht. Dazu eine Frist von
  60 s.

Der Test prüft dreierlei:
- Exit 1.
- Die Ausgabe nennt `HookError [SevereServiceError]: tauri build failed (1)`.
- Kein Worker startet: keine Zeile mit `[0-0]`, und die Marker-Datei des tauri-driver gibt es nicht.

Exit 1 allein beweist nichts: Ohne den Fix endet der Lauf ebenfalls mit 1, aber erst, nachdem der Worker gestartet ist
und der tauri-driver scheitert (siehe Beweis).

Der Test liegt unter `test/unit/` und läuft damit in `npm run lint` mit (`package.json:10-11`, Glob
`test/unit/*.test.js`), also im Schritt `desktop-e2e-lint` von `run.sh quick` und im CI-Schritt „E2E eslint“. Er
braucht nur die installierten `node_modules`.

Gegenprobe im Bau: in einem Wegwerf-Worktree `throw new SevereServiceError` → `throw new Error` in `wdio.conf.js:116`.
Der neue Test muss dort rot sein. Nichts davon wird committet; der Worktree wird mit vollem Pfad entfernt.

README `apps/desktop/e2e/README.md:119-120`, Abschnitt CI: „runs the unit test under `test/unit/`“ heißt künftig „the
unit tests“. Ein Halbsatz nennt den Launcher-Lauf mit falschem `cargo`.

Kein CHANGELOG-Eintrag: Nur ein Test kommt dazu, am Verhalten ändert sich nichts.
Beweis: feature/e2e-build-fails-red@870f3f2d (Opus-Review R-0259, Nit 2; lokal lieferte `npx wdio run` mit falschem
cargo rc=1). Frisch auf origin/main@128b7fb5: `unshare -rn` (ohne Netz) `node node_modules/@wdio/cli/bin/wdio.js run
<cfg> --spec test/specs/smoke.e2e.js`, falsches `cargo` (exit 1), falscher tauri-driver mit Marker:
- `wdio.conf.js` (mit Fix): `rc=1 secs=2 driver_started=no worker_lines=0 severe=1`.
- Probe-Kopie mit `throw new Error` (ohne Fix, danach gelöscht): `rc=1 secs=4 driver_started=yes worker_lines=4
  severe=0`.
- Kein Netzfehler (`ENOTFOUND`/`EAI_AGAIN`/`ENETUNREACH`) in beiden Läufen.
Dedup-Key: ref:desktop-e2e:wdio.conf.js:launcher-test
HEAD: 128b7fb5
Semantik: `apps/desktop/e2e/README.md:105-107` (seit R-0259): „A failed build stops the run (exit 1) before any spec
starts: `onPrepare` throws a `SevereServiceError`, the only error wdio does not just log and run past, so the specs
never drive an older binary.“ Der neue Test prüft genau diese Aussage am echten Launcher.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: apps/desktop/e2e/README.md (Abschnitt CI)
