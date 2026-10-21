<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Workspaces, Teil Live-E2E — Task-Ledger
Status: erledigt · Branch: feature/desktop-workspaces-e2e · Review: pro Task
Spec: docs/features/desktop-workspaces.md (Roadmap R-0431, R-0524)
Heavy: none — Teil-Ledger von `tasks/desktop-workspaces.md`; die schweren Läufe fährt das Vorhaben dort
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-20: R-0431 baut in drei Spuren mit je eigenem Teil-Ledger, Branch und Worktree, damit die disjunkten Blöcke parallel laufen: Windows-RDP und Doku in `tasks/desktop-workspaces.md` (`feature/desktop-workspaces`), Oberfläche in `tasks/desktop-workspaces-ui.md` (`feature/desktop-workspaces-ui`), Live-E2E in `tasks/desktop-workspaces-e2e.md` (`feature/desktop-workspaces-e2e`). Die Teil-Branches werden in `feature/desktop-workspaces` gemergt, nie direkt in `main`; je Ledger höchstens ein Bauer.

Reihenfolge in dieser Spur: zuerst T25, T27, T29, T30, T44 (hängen nur an Block A/B und an dieser Spur); T31 (braucht T19/T20), T26 (braucht T22) und T28 (braucht T20) erst, wenn die Oberfläche in `feature/desktop-workspaces` gemergt und hierher geholt ist; T32 zuletzt.

## Block E — Live-E2E

### T25 — WebDriver startet Launcher oder Workspace nach AH_E2E_WORKSPACE  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/test/lib/app-args.js, apps/desktop/e2e/test/unit/app-args.test.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @cfb61271 2026-10-20T12:59:23+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T25.verdict.json)
Änderung: `tauri:options.args` (`wdio.conf.js:62-66`) kommt aus einer reinen Funktion in `test/lib/app-args.js` (SPDX-Header): `AH_E2E_WORKSPACE` gesetzt und nicht leer → `['--workspace', <id>]` (Id gegen dieselbe Regel wie in Rust geprüft, sonst Fehler beim Laden der Config), sonst `[]` (Launcher; der smoke-Spec läuft damit unverändert gegen den Launcher und prüft die Übergabe beim zweiten Start). Unit-Test unter `node --test` (SPDX-Header): gesetzt, leer, ungesetzt, ungültig. Das Verify ist Lint plus Unit-Tests; der echte Beweis kommt aus dem Sammellauf.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T10

### T27 — Orchestratoren starten den Standard-Workspace  [x]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/box_desktopbox.sh, scripts/tests/desktop_e2e_crud.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dc0319f4 2026-10-20T13:21:56+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T27.verdict.json)
Änderung: `lib_e2e_stack.sh` exportiert neben den WebKit-Variablen (`:33`) `AH_E2E_WORKSPACE=standard` (alle `desktop_e2e_*.sh` sourcen sie), `box_desktopbox.sh` (`:41-43`) ebenso; das Seeden der alten `settings.json` bleibt und testet damit die Migration. `desktop_e2e_crud.sh` (`:45-84`): der Nachweis der Vertrauens-Zustimmung liest `workspaces/standard/workspace.json` statt `settings.json`; vor dem erneuten Seeden löscht das Skript `workspaces.json`, `workspaces/` und `prefs.json` unter `$XDG_DATA_HOME/com.admincave.adminhelper` mit vollem Pfad, damit die Migration erneut läuft. `lib_e2e_stack_test.sh` prüft den Export.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Test)
Abhängt von: T25

### T29 — E2E-Stack: zwei Installationen nebeneinander  [x]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, docker-compose.test.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dd0f8824 2026-10-20T13:58:25+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T29.verdict.json)
Änderung: `e2e_init` (`lib_e2e_stack.sh:93`) bekommt einen optionalen Stack-Schlüssel (`a`/`b`) mit eigenem Projekt, Arbeitsverzeichnis, Ports (Daten-, Postgres-, Redis-Port mit Versatz), Bind-Adresse (`a` = `127.0.0.1`, `b` = `127.0.0.2`; ohne Schlüssel wie heute), `FRP_BIND_PORT`/`FRP_HTTPS_PORT` (`b`: 7001/7444) und `E2E_SERVER_URL`; `e2e_stack_use <a|b>` schaltet die globalen Variablen um, der Teardown räumt beide Stacks ab. `docker-compose.test.yml` (Gateway-Ports `:55-60`) veröffentlicht unter `${ITEST_BIND_IP:-0.0.0.0}`, damit beide Stacks die feste Enrollment-Ebene :8444 auf ihrer eigenen Loopback-Adresse halten. Bestehende Orchestratoren bleiben unverändert. `lib_e2e_stack_test.sh` (ohne Docker): zwei Stacks haben disjunkte Ports, Projekte, Arbeitsverzeichnisse und URLs; ohne Schlüssel bleibt alles wie bisher. Nicht gefahren: Veröffentlichung auf `127.0.0.2`.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Test)
Abhängt von: T27

### T30 — WebDriver mit zwei Workspace-Prozessen gleichzeitig  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/wdio.workspaces.conf.js, apps/desktop/e2e/test/lib/app-args.js, apps/desktop/e2e/test/unit/app-args.test.js, apps/desktop/e2e/eslint.config.js, apps/desktop/e2e/wdio.conf.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @bbda5dfa 2026-10-20T16:00:29+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T30.verdict.json)
Änderung: Neue Config `wdio.workspaces.conf.js` (SPDX-Header, Build und Hooks wie `wdio.conf.js`) für WebdriverIO-Multiremote: zwei Sitzungen `wsA`/`wsB` mit Args aus `AH_E2E_WORKSPACE_A`/`_B` (über `app-args.js`), zwei tauri-driver auf 4444/4445 und 4446/4447, beide beim Ende beendet. `app-args.js` liefert dazu die Port-Paare; Unit-Tests dafür. Spec-Glob nur `*.workspaces.js`, damit `npm test` (smoke) ihn nicht greift; ESLint kennt die Multiremote-Namen. Nicht verifiziert: zwei WebKitWebDriver-Sitzungen unter einem Xvfb gleichzeitig; scheitert das im Sammellauf, `[?]` an Kevin (Rückfall: nacheinander, der Port des ersten hält ein Listener).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T25

### T44 — E2E-Stack: Schlüssel zuerst prüfen, gemischte Nutzung ablehnen  [x]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, docker-compose.test.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c31695eb 2026-10-20T17:27:30+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T44.verdict.json)
Änderung: Aus den Reviews von T29: `e2e_init` prüft den Stack-Schlüssel, bevor es irgendeine globale Variable setzt (heute setzt es `E2E_BIND_IP` und die FRP-Ports vor der Ablehnung, die Globals eines bestehenden Stacks passen danach nicht mehr zusammen); es lehnt einen zweiten `e2e_init` mit demselben Schlüssel und das Mischen eines Stacks ohne Schlüssel mit einem mit Schlüssel ab (sonst bleiben Projekt und Arbeitsverzeichnis beim Teardown liegen). Der Kopfkommentar in `docker-compose.test.yml` nennt die frps-Ports 7001/7444 von Stack b. Tests: unbekannter Schlüssel nach `e2e_init a` lässt die Globals von a unverändert; doppeltes `a` und gemischte Nutzung ergeben rc 1 ohne neues Verzeichnis.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Test)
Abhängt von: T29

### T31 — Live-Specs: zwei Installationen, derselbe Visitor-Port  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/workspace-add-server.live.js, apps/desktop/e2e/test/specs/two-installations.workspaces.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @b57924d3 2026-10-20T20:29:45+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T31.verdict.json)
Änderung: `workspace-add-server.live.js` (SPDX-Header, Launcher): legt den Server-Workspace „Kunde B“ mit `AH_E2E_SERVER_URL_B` an und schreibt seine Id in die Datei aus `AH_E2E_WS_B_FILE`. `two-installations.workspaces.js` (SPDX-Header, Multiremote): `wsA` (Standard, Stack A) und `wsB` (Kunde B, Stack B) registrieren sich je mit ihrem Token (`AH_ENROLL_TOKEN_A`/`_B`), melden sich an und starten den Tunnel; `tunnel_status` beider zeigt denselben Server-Port und verschiedene lokale Ports; jeder öffnet seine SSH-Verbindung; `wsB` findet vor der Registrierung keine Identität (`is_device_enrolled` false), obwohl `wsA` registriert ist; ein zweiter Start `--workspace standard` aus Node endet mit Exit 3, während `wsA` läuft. Verify ist der Lint; Beweis im Sammellauf (T32). Nachtrag (2026-10-20): Der Spec `workspace-add-server.live.js` legt den Workspace über den Picker und den Editor der Oberfläche an (T19, T20 in `tasks/desktop-workspaces-ui.md`); T31 baut deshalb erst, wenn die Oberfläche in `feature/desktop-workspaces` gemergt und hierher geholt ist, und steht hinter T44.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T30

### T26 — Live-Helfer und Specs mit fester Workspace-URL  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/lib/live.js, apps/desktop/e2e/test/specs/login-error.live.js, apps/desktop/e2e/test/specs/enroll-form.live.js, apps/desktop/e2e/test/specs/enroll-trust-dialog.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @de14e7a4 2026-10-20T20:36:47+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T26.verdict.json)
Änderung: `login()` (`live.js:65-89`) füllt die URL nur, wenn das Feld da ist (nach dem ersten erfolgreichen Login ist sie fest), Benutzer und Passwort über den Feldtyp statt über die Position; ein Helfer `fillServerUrlIfAsked()` für die Specs mit URL-Feld (`login-error.live.js:14-16`, `enroll-form.live.js:27-35`, `enroll-trust-dialog.live.js:25-26`). Die Specs prüfen, dass die angezeigte URL die erwartete ist, wenn kein Feld da ist. Verify ist der Lint; Beweis im Sammellauf. Nachtrag (Bauer T22): Die feste URL steht als `[data-testid="workspace-url"]`; „Ohne Server fortfahren“ gibt es nicht mehr, an seiner Stelle `[data-action="open-launcher"]` („Workspaces…“). `login-error.live.js` liest die Felder heute nach Position (`[0]` = URL) und muss bei fester URL über Feldtyp bzw. die Testid gehen.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T22

### T28 — Live-E2E: Picker ersetzt den Moduswechsel  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/workspace-picker.live.js, apps/desktop/e2e/test/specs/settings-mode.live.js, scripts/tests/desktop_e2e_crud.sh, apps/desktop/ui/src/components/Picker.svelte, apps/desktop/ui/src/components/Picker.test.ts, apps/desktop/e2e/test/specs/workspace-add-server.live.js, apps/desktop/e2e/test/specs/enroll-form.live.js, apps/desktop/e2e/test/specs/enroll-trust-dialog.live.js, apps/desktop/e2e/README.md, apps/desktop/e2e/test/specs/settings-enroll.live.js
Evidenz: run.sh[quick] desktop-e2e scripts desktop-ui: 8 passed, 0 failed, 10 skipped @06b0cd4b 2026-10-20T21:14:09+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T28.verdict.json)
Änderung: Neuer Spec (SPDX-Header), läuft im Launcher (`AH_E2E_WORKSPACE` leer): der Picker zeigt „Standard“ als Server-Workspace und einmal den Migrationshinweis; „Neuer Workspace“ Lokal „E2E Lokal“ mit Farbe anlegen, umbenennen, löschen (die Bestätigung nennt den Namen; Datenverlust-Hinweis). `desktop_e2e_crud.sh` ruft ihn statt `settings-mode.live.js` (`:84`) als eigenen wdio-Lauf mit leerem `AH_E2E_WORKSPACE` am Ende. Öffnen aus dem Picker (abgekoppelter Prozess außerhalb von WebDriver) beweisen T12 und T32. Nachtrag (Bauer T31): „Neuer Workspace“ und die übrigen Picker-Aktionen bekommen `data-action`-Hooks (`Picker.svelte`, Dateien per set-files), und `workspace-add-server.live.js` (T31) wechselt vom ersten Button in `.picker-actions` auf den Hook. Nachtrag (T26-Review, Nits): `enroll-form.live.js` (~:28) wartet auf `input[type="text"]` erst nach dem Verschwinden des Passwortfelds (sonst erfüllt das Benutzerfeld die Bedingung), wie `enroll-trust-dialog.live.js`; dessen Kopfkommentar nennt `workspaces/standard/workspace.json` statt `settings.json` (Dateien per set-files).
Verify: bash scripts/dev/verify.sh desktop-e2e scripts desktop-ui --strict
Doku: keine (Test)
Abhängt von: T20, T27
Test-Löschung: apps/desktop/e2e/test/specs/settings-mode.live.js::* — der Moduswechsel in den Einstellungen entfällt, ersetzt durch workspace-picker.live.js

### T32 — Suite desktop_e2e_workspaces: zwei Stacks, zwei PKIs  [x]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_workspaces.sh, apps/desktop/e2e/test/specs/workspace-picker.live.js, apps/desktop/e2e/test/specs/workspace-add-server.live.js, scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/e2e_api.py, apps/desktop/e2e/README.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts desktop-e2e: 7 passed, 0 failed, 11 skipped @8db9e863 2026-10-20T22:06:07+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T32.verdict.json)
Änderung: Neuer Orchestrator (SPDX-Header) nach dem Muster von `desktop_e2e_connect_tunnel.sh`: `e2e_require` wie dort, SKIP mit Exit 75 ohne tauri-cli (`desktop_e2e_skip_test.sh` prüft das per Glob mit); zwei Stacks (T29) je mit Gateway, frps, geseedetem Server, FRP-Konfiguration, SSH-Ziel (Host-Port 2222 bzw. 2223), verknüpfter Verbindung und STCP-Tunnel, vom Agent provisioniertem frpc und Enrollment-Token; prüft über die API, dass beide Installationen dem Tunnel denselben Visitor-Port gegeben haben. Seedet `settings.json` mit der URL von Stack A (Standard), führt `workspace-add-server.live.js` im Launcher und dann `two-installations.workspaces.js` mit `wdio.workspaces.conf.js` aus; danach: das SSH-Ziel A sah genau die Verbindung von `wsA`, Ziel B die von `wsB`; `workspaces/standard/` und `workspaces/<id B>/` enthalten nur die Verbindungen ihres Servers. `run.sh` und `heavy.sh` bleiben unberührt (Glob). Nachtrag (Bauer T31, Vertrag der Specs): Der Orchestrator seedet `settings.json` mit Modus server und der URL von Stack A (so entsteht `standard` als Server-Workspace); in beiden Stacks heißen Tunnel `e2e-ssh-tun` und Verbindung `ssh-tunnel` (wie `desktop_e2e_connect_tunnel.sh`); `workspace-add-server.live.js` läuft mit leerem `AH_E2E_WORKSPACE`; der Multiremote-Lauf bekommt `AH_E2E_WORKSPACE_A=standard`, `AH_E2E_WORKSPACE_B=<Id aus AH_E2E_WS_B_FILE>`, `AH_E2E_SERVER_URL_A/_B`, `AH_ENROLL_TOKEN_A/_B`, `AH_ADMIN_USER`, `AH_ADMIN_PASS_A/_B` (Passwörter je Stack verschieden). Nachtrag (Review T31): Pro Lauf ein frisches `XDG_DATA_HOME` und ein eigener Keyring (`dbus-run-session`), weil der Spec `is_device_enrolled` für A zu Beginn als false voraussetzt; das Gateway-Zertifikat von Stack B trägt 127.0.0.2 als SAN (sonst scheitern Registrierung und Anmeldung bei B; gehört zu T29/T32, nicht verifiziert); die Prüfung am SSH-Ziel zählt nur die Öffnung durch die Oberfläche (keine nackte TCP-Verbindung als Öffnung werten). Nachtrag (T28-Review, Nits): `workspace-picker.live.js` (~:110) und `workspace-add-server.live.js` (~:54) warten auf `'.picker-list, .login-card'` und prüfen dann `workspace_context`, damit ein gesetztes `AH_E2E_WORKSPACE` mit der benannten Meldung scheitert; `translations()` in `workspace-picker.live.js` findet auch Werte in doppelten Anführungszeichen und prüft, dass je Sprache ein Text gefunden wurde; der Kopfkommentar von `workspace-picker.live.js` sagt nicht, dass der Lauf das Öffnen aus dem Picker live beweist (Multiremote startet per `--workspace`; das Öffnen aus dem Picker ist nur in Rust getestet) — im PR-Text als nicht live bewiesen nennen. Dateien per set-files.
Verify: bash scripts/dev/verify.sh scripts desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T29, T31

### T52 — Live: Server-Workspace löschen widerruft das Gerät  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/workspace-delete-server.live.js, scripts/tests/desktop_e2e_workspaces.sh, scripts/tests/e2e_api.py, apps/desktop/e2e/README.md, DEVELOPMENT.md
Evidenz: run.sh[quick] desktop-e2e scripts: 7 passed, 0 failed, 11 skipped @5fb28c28 2026-10-21T05:53:04+02:00
Review: approve (.ah-out/review/desktop-workspaces-e2e/T52.verdict.json)
Änderung: Aus der Branch-Prüfung (Reviewer, Nit, von der Session aufgenommen): Kein Test beweist, dass das Löschen eines Server-Workspace mit echtem Widerruf funktioniert (Purge-Kind, `block_on(enrollment::reset_identity)` in `main.rs`, Exit 10). Neuer Launcher-Spec (SPDX-Header): nach dem Multiremote-Lauf (beide Fenster geschlossen) „Kunde B“ im Picker löschen (`[data-action="workspace-delete"]`), die Rückfrage bestätigen, `revoked` (kein `localOnly`) erwarten, Workspace weg aus Liste und Bridge. Die Suite prüft danach über die API von Stack b, dass das Gerät widerrufen ist (Geräteliste/`revoked`), und dass `workspaces/<id B>/` fehlt. Läuft mit leerem `AH_E2E_WORKSPACE` in eigenem `dbus-run-session` mit demselben Keyring wie der Multiremote-Lauf (die Identität von B muss auffindbar sein).
Verify: bash scripts/dev/verify.sh desktop-e2e scripts --strict
Doku: keine (Test)
Abhängt von: T32
