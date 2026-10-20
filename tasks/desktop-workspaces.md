<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Workspaces — Task-Ledger
Status: aktiv · Branch: feature/desktop-workspaces · Review: pro Task
Spec: docs/features/desktop-workspaces.md (Roadmap R-0431, R-0524)
Heavy: linux-full + scenario --agents 1 --tunnel --desktop + windows — der Desktop startet anders (Launcher, Workspace-Prozess, Migration), alle Live-Specs ziehen mit und die neue Suite `desktop_e2e_workspaces` (zwei Stacks) läuft im e2e-Layer, `docker-compose.test.yml` ändert sich: Sammellauf; `scenario`, weil `box_desktopbox.sh` (Capstone `--desktop`) den Standard-Workspace startet und Tunnel-Laufzeitdateien und Portkarten-Besitzer je Workspace wechseln (FRP-Datenpfad); `windows` = CI-Job `rust-windows` (abgekoppelter Prozessstart, Datei-Locks, Keyring-TargetName, TERMSRV); mstsc selbst ist ohne Windows-Vorlage im Pool nicht verifiziert, dafür die Prüfanleitung aus T33 für Kevin
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16 (Konzept, Spike erledigt) und 2026-10-19 (Antworten auf die Plan-Fragen, siehe Spec „Entscheidungen“): ein OS-Prozess je Workspace mit Launcher; der Workspace-Namensraum kommt aus R-0430 hierher, das Single-Instance-Plugin aus R-0429 T7 gilt nur noch im Launcher. Gebaut wird nach dem Merge von R-0430: die Zeilen gelten für `feature/desktop-session-ports@ee47d213` und werden beim Baustart neu gegreppt. Reihenfolge-Pflicht (S1): die Portkarte bekommt den Besitzer je Workspace (T3), bevor das Single-Instance-Plugin auf den Launcher beschränkt wird (T10), sonst teilen zwei Prozesse mit gleichem Visitor-Namen einen lokalen Port. Harness-Pfade (`CLAUDE.md`, `.claude/`, `scripts/dev/*`, `scripts/tests/run.sh`, `scripts/tests/heavy.sh`, `scripts/vm/*`) berührt keine Task: `run.sh` findet die neue Suite `desktop_e2e_workspaces.sh` per Glob und verlangt sie im e2e-Layer. `security`-Prüfer zusätzlich bei T3, T6, T7, T8, T13, T14, T16, T17, T29 (Enrollment, Keyring, FRP, Tunnel-Auflösung, Wire-Typen, Windows-Credentials, Compose; `password.rs` steht nicht in `review-risk.txt`, trägt aber Passwörter). Neue serde-Typen für Dateien (Registry, Metadaten, Prefs, Index) sind `pub(crate)`, sonst verlangt `types.parity.test.ts` ein TypeScript-Gegenstück. Neue Tauri-Commands kommen nur mit Bridge und Command-Tabelle der Entwickler-Doku (`ipc.inventory.test.ts`), deshalb ist T14 breiter als drei Dateien. Neue Rust-Fehlertexte englisch. Windows-Beweise: cfg(windows)-Tests laufen nur im CI-Job `rust-windows`; `ci.yml` läuft nur für PRs, auf `main` und per `workflow_dispatch`, deshalb pusht die Session nach dem Commit von T16 den Branch, startet `gh workflow run ci.yml --ref feature/desktop-workspaces` und wartet auf den grünen `rust-windows`-Job, bevor T17 startet (nach T17 ebenso). Doku gesammelt in T33–T35, weil das Verhalten erst mit T18–T24 zusammen sichtbar ist (wie R-0430 T5).

## Block A — Namensraum, Portkarte, Migration

### T1 — Startmodus, Workspace-Id und Namensraum  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/main.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @b79fc4be 2026-10-19T14:33:48+02:00
Review: approve (.ah-out/review/desktop-workspaces/T1.verdict.json)
Änderung: Neues Modul `workspace.rs` (SPDX-Header): `Mode::{Launcher, Workspace(id), Purge(id)}` aus argv (`--workspace <id>`, zusätzlich `--purge`; alles andere → Fehler mit Nutzungszeile), Id gegen `^[a-z0-9-]{1,32}$` mit ausgeschriebener ASCII-Klasse (keine Locale-Bereiche). `Workspace{id, name, legacy_keys}` mit `data_dir(base)` = `base/workspaces/<id>`, `run_dir`, `lock_path`, `keyring_prefix()` (`""` bei `legacy_keys`, sonst `ws:<id>|`, unter Windows `com.admincave.adminhelper/ws:<id>|`), `log_name()` (`adminhelper-<id>`; Launcher `adminhelper`), `window_title()` („<Name> — AdminHelper“). Prozessglobaler Kontext (`OnceLock`); `current()` ohne Kontext (Launcher) ist ein Fehler; für Tests ein thread-lokaler Guard nach dem Muster von `keyring_store::memory()`. In `main.rs` nur `mod workspace;`. Tests: argv-Varianten (fehlende Id, `../x`, Großbuchstaben, Umlaut, 33 Zeichen, unbekannte Flags → Fehler), Präfix legacy/neu, Titel, Logname, `current()` ohne Kontext → Fehler.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- workspace::
Doku: keine (intern; Doku mit T33)

### T2 — Lock je Workspace, Registry und Metadaten  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/storage.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @88331b95 2026-10-19T14:48:03+02:00
Review: approve (.ah-out/review/desktop-workspaces/T2.verdict.json)
Änderung: `instance.lock` als eigene Sperrdatei (geöffnet mit `read`+`write`, `File::try_lock`): `acquire` versucht es bis 2 s (die kurze Probe des Pickers darf einen startenden Prozess nicht abweisen), `is_open` probt und gibt sofort frei. Lesen/Schreiben von `workspaces.json` (`{workspaces:[{id}], lastUsed, migratedNotice}`) und `workspaces/<id>/workspace.json` (`{kind, name, color, url, intervalMinutes, allowSelfSignedCerts, lastUsername, legacyKeys}`; `kind` ist `SyncMode`) über `storage::write_json_pretty` (`storage.rs:66`, wird `pub(crate)`); feste Farbpalette als Konstante. Tests (Temp-Verzeichnis je Test): zweites `acquire` → belegt, nach Drop frei; `is_open` während gehalten true, danach false; eine Probe während eines laufenden `acquire` lässt es nicht scheitern; Rundreise beider Dateien; kaputte Datei → Fehler statt stiller Vorgabe.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- workspace::
Doku: keine (intern; Doku mit T33)
Abhängt von: T1

### T3 — Portkarte je Workspace: Besitzer, Obergrenzen, Verwaltung  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/port_registry.rs, apps/desktop/src-tauri/src/frpc.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @2dd3f118 2026-10-19T15:05:37+02:00
Review: approve (.ah-out/review/desktop-workspaces/T3.verdict.json)
Änderung: `assign_ports` (`frpc.rs:864`) gibt die Workspace-Id (`workspace::current()`) statt `DEFAULT_OWNER` (`:872`) als Besitzer; die Portkarte bleibt im App-Datenordner (`PortRegistry::new`, `:1040`). `PortRegistry::assign` lehnt mehr als 500 Visitors je Besitzer und mehr als 250 Ausweichports (`FALLBACK_PORTS`) je Besitzer ab (Konstanten). Neu unter der Sperre der Karte: `local_ports_of_others(owner)`, `rename_owner(from, to)`, `release(owner)`, `retain_owners(&[ids])`. `DEFAULT_OWNER` bleibt nur für die Migration (T4). Tests: zwei Besitzer mit demselben Visitor-Namen und Server-Port bekommen verschiedene lokale Ports; 501 Visitors → Fehler, Karte unverändert; der 251. Ausweichport eines Besitzers → Fehler, ein anderer Besitzer bekommt weiter einen; `local_ports_of_others` ohne die eigenen; Umbenennen, Freigeben, `retain_owners` lässt nur die genannten; ohne Workspace-Kontext startet kein Abgleich.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- port_registry
Doku: keine (intern; Doku mit T33)
Abhängt von: T1

### T4 — Migration in das Workspace-Layout  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/migration.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/port_registry.rs, apps/desktop/src-tauri/src/workspace.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @cd957e0a 2026-10-19T15:47:12+02:00
Review: approve (.ah-out/review/desktop-workspaces/T4.verdict.json)
Änderung: Neues Modul `migration.rs` (SPDX-Header), `migrate(base)` unter `migrate.lock` (blockierendes `File::lock`), idempotent: `workspaces.json` vorhanden → nichts. Sonst aus `settings.json` (fehlt sie: `Settings::default()`, also „Standard“ lokal): `standard` („Standard“, Art = bisheriger `mode`, URL, Intervall, self-signed, `lastUsername`, `legacyKeys: true`) in `standard.partial/` aufbauen (Verbindungsdateien je Art; die Vor-Split-Regel über `migrate_between`, `storage.rs:152`, wird `pub(crate)`) und umbenennen; nicht leere `connections.local.json` bei `mode` ≠ local → `lokal` („Lokal“); Sync-URL bei `mode` ≠ sync → `sync` („Sync“); Server-URL bei `mode` ≠ server → `server` („Server“, URL, `lastUsername`, self-signed); alle drei mit `legacyKeys: true`. Dann `prefs.json` (Sprache, Passwörter, RDP, OS-Benachrichtigungen), dann die Portkarte: Einträge von `DEFAULT_OWNER` gehen an den migrierten Server-Workspace (`standard` oder `server`), gibt es keinen, `release` (T3). Zuletzt `workspaces.json` atomar (`lastUsed: standard`, `migratedNotice: true`). Altdateien bleiben unverändert; Reste eines abgebrochenen Laufs (`*.partial`, Verzeichnisse der Migrations-Ids ohne Registry) werden neu aufgebaut. In `main.rs` nur `mod migration;`. Tests: je Ausgangslage (server/sync/local, mit und ohne Zusatzdaten, ohne `settings.json`); Abbruch nach jedem Schritt über einen Schritt-Hook, dann zweiter Lauf → dasselbe Ergebnis wie ohne Abbruch; zweiter Lauf nach Erfolg ändert nichts; Altdateien byte-gleich; zwei gleichzeitige Läufe (zwei Threads) → ein Ergebnis; Portkarte umbenannt bzw. geleert. Hinweis (T2): unter Windows schreibt `write_json_pretty` in place; den Commit-Marker `workspaces.json` atomar schreiben oder eine unlesbare Registry als „nicht migriert“ behandeln, sonst scheitert nach einem Abbruch jeder weitere Start. Dazu (Prüfer-Hinweis zu T3): beim Übernehmen der Portkarten-Einträge von `default` höchstens 500 Einträge und 250 Ausweichports (23000–23999) übernehmen, den Rest verwerfen, damit Altbestände den Ausweichbereich nicht für andere Workspaces blockieren; Test dazu. Nit (T3): im Test von `port_registry.rs` (~:938) ein Typ-Alias für das Funktionszeiger-Array (`clippy::type_complexity` unter `--tests`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- migration::
Doku: keine (intern; Doku mit T33)
Abhängt von: T2, T3

### T5 — Einstellungen getrennt: global und je Workspace  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/workspace.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @e1aaf918 2026-10-19T16:15:54+02:00
Review: approve (.ah-out/review/desktop-workspaces/T5.verdict.json)
Änderung: `load_settings` (`storage.rs:169`) liefert die bisherige `Settings`-Form aus `prefs.json` und `workspace.json` des Kontexts (`mode` = Art); im Launcher `prefs.json` plus Vorgaben. `save_settings` (`:174`) schreibt die globalen Felder unter `prefs.lock`: neu lesen, nur die Felder übernehmen, die sich gegenüber dem zuletzt in diesem Prozess geladenen Stand geändert haben, atomar mit pid im Temp-Namen; Lesen von `prefs.json` ebenfalls unter der Sperre (unter Windows schreibt `write_json_pretty` in place). Die Workspace-Felder gehen in `workspace.json`; `mode` nie; `serverUrl`/`url` nur, solange der Workspace keine hat, ein anderer Wert ist `AppError::Validation`. Verbindungsdateien (`:108-131`) liegen im Datenordner des Workspaces, `current_mode` (`:49`) liest die Art; ohne Workspace-Kontext Fehler. Tests über pfadbasierte Kernfunktionen: Rundreise; zwei Handles ändern verschiedene globale Felder nacheinander aus altem Stand → beide Änderungen bleiben; `mode` bleibt; zweite, andere Server-URL abgewiesen, erste gesetzt; Launcher: Verbindungen laden → Fehler. Hinweis (T2): unter Windows schreibt `write_json_pretty` in place; ein gleichzeitiger Leser (Launcher) kann eine halbe `workspace.json` sehen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage::
Doku: keine (intern; Doku mit T33)
Abhängt von: T4

### T6 — Keyring-Präfix für Geräte-Identität und RDP-Passwörter  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/http_client.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @ec74f658 2026-10-20T06:12:11+02:00
Review: approve (.ah-out/review/desktop-workspaces/T6.verdict.json)
Änderung: Die Schlüssel `enroll|key|cert|ca|replaces` (`enrollment.rs:36-42`) und `rdp|…` (`password.rs:17`, `:34`) bekommen `workspace::current()?.keyring_prefix()` vorangestellt; ohne Kontext (Launcher) gibt es keine Identität (`is_enrolled` false, `load_identity` None) und Schreiben ist ein Fehler. `tofu|cert|*` und das Aufräumen alter `auth|*` bleiben ohne Präfix. Index der RDP-Schlüssel je Workspace in `workspaces/<id>/secrets.json` (nur Namen), gepflegt von `save_password` (`:315`) und `delete_password` (`:339`). Der Windows-Weg für RDP-Passwörter folgt in T16/T17. Tests (`workspace_keys_*`, mit `keyring_store::memory()` und Workspace-Guard): Standard (`legacyKeys`) liest die Altschlüssel; zwei neue Workspaces sehen die Identität des anderen nicht; RDP-Schlüssel getrennt; Index nach Speichern und Löschen; Launcher: `is_enrolled` false, Speichern Fehler. Hinweis (T1): der Test-Guard `workspace::enter` gilt nur im eigenen Thread; Code, der in Tests auf anderen Threads läuft (`spawn_blocking`, tokio-Worker), sieht keinen Workspace.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- workspace_keys
Doku: keine (intern; Doku mit T33)
Abhängt von: T2

### T36 — Migration unter Windows: keine Temp-Reste eines abgebrochenen Laufs  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/migration.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @cf0aa589 2026-10-20T06:24:34+02:00
Review: approve (.ah-out/review/desktop-workspaces/T36.verdict.json)
Windows: CI `rust-windows` (Lauf 39369427419, workflow_dispatch @15d6a569, 2026-10-20) grün, `Desktop-Backend (cargo test, Windows)` success
Änderung: Unter Windows bleibt nach `migrate` ein `prefs.json.tmp` aus einem abgebrochenen Lauf liegen: `write_json_pretty` schreibt dort an Ort und Stelle, nur unter Unix überschreibt der Rename den Rest (CI `rust-windows`, `migration::tests::leftovers_of_an_aborted_run_are_built_anew_and_other_workspaces_stay`). `migrate` schreibt `prefs.json` über `write_json_atomic` (`storage.rs:116`) und entfernt vor dem Schreiben die Reste mit festem Namen (`prefs.json.tmp`, `workspaces.json.tmp`) im App-Datenordner; fehlt einer, ist das kein Fehler. Der bestehende Test bleibt unverändert und muss unter Windows grün werden; dazu ein Test, der nur die Temp-Reste pflanzt und nach `migrate` keinen davon mehr findet. Beweis unter Windows: CI-Job `rust-windows` per `workflow_dispatch` auf dem Branch; die Session hält das Ergebnis im Ledger fest.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- migration::
Doku: keine (intern)
Abhängt von: T4

### T7 — Tunnel-Laufzeitdateien je Workspace, nur solange der Tunnel läuft  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @424ab77c 2026-10-20T06:50:21+02:00
Review: approve (.ah-out/review/desktop-workspaces/T7.verdict.json)
Änderung: `visitor.toml` und `identity/` liegen in `workspaces/<id>/run/` statt im App-Datenordner (`VISITOR_CONFIG :640`, `app_data_dir :642`, `write_visitor_config :654`, `AppSidecar :698`); `run/` entsteht unter Unix mit 0700. Die Laufzeitdateien liegen nur, solange der Tunnel läuft: `stop_frpc` (`:819`, auch der Weg über `RunEvent::Exit` und das Abmelden) leert `run/`, und vor dem ersten Schreiben eines Prozesses räumt der Abgleich Reste eines abgebrochenen Laufs ab. Die Portkarte bleibt im App-Datenordner. Tests: der Sidecar schreibt unter `run/` des Kontexts; nach `stop_frpc` ist `run/` leer; eine liegengebliebene Datei aus einem früheren Lauf ist vor dem ersten Start weg; ohne Kontext startet kein Tunnel. Hinweis (T1): der Test-Guard `workspace::enter` gilt nur im eigenen Thread; frpc-Watcher und `spawn_blocking` sehen in Tests keinen Workspace.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc::
Doku: keine (intern; Doku mit T33)
Abhängt von: T1, T3

### T8 — Keine Verbindung auf Ports fremder Workspaces  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/port_registry.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @45789270 2026-10-20T08:17:20+02:00
Review: approve (.ah-out/review/desktop-workspaces/T8.verdict.json)
Änderung: Die Bindings kommen schon je Prozess (`FrpcState`, R-0430 T13), also vom eigenen frpc. Für den Fall ohne eigenen Tunnel eine reine Funktion in `tunnel.rs`: ein Ziel (Host bzw. Host der Web-URL) auf `127.0.0.0/8`, `::1` oder `localhost`, dessen Port in `local_ports_of_others(owner)` (T3) steht und den kein eigenes Binding hält, ist ein Fehler (englischer Text mit dem Hinweis, den Tunnel dieses Workspace zu starten). `resolve_connection` (`commands.rs:385`), `open_connection` (`:212`) und `open_connection_stored` (`:240`) prüfen die aufgelöste bzw. geöffnete Verbindung damit, bevor etwas startet oder ein Passwort geladen wird. Tests (`foreign_port_*`): Loopback auf fremdem Port ohne eigenes Binding → Fehler; derselbe Port mit eigenem Binding → erlaubt; fremder Port auf Nicht-Loopback-Host → erlaubt; Web-URL `http://127.0.0.1:<fremd>` → Fehler; kein Eintrag → erlaubt. Restrisiko benennen (Prüfer zu T3): über `local_ports_of_others` kann ein Server über die Einträge seines Workspace auch lokale Loopback-Ports eines anderen Workspace sperren; das scheitert sicher (Ablehnung statt Umleitung) und steht in der Doku.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- foreign_port
Doku: keine (intern; Doku mit T33)
Abhängt von: T3

### T9 — Prozessnamen: Diagnose, Ansible-Temp, RDP-Fenstertitel  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/diagnostics.rs, apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/connection/rdp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @c7fb3f15 2026-10-19T16:26:14+02:00
Review: approve (.ah-out/review/desktop-workspaces/T9.verdict.json)
Änderung: Die Diagnose liest die Logdatei des eigenen Prozesses (`workspace::log_name`, heute fest `adminhelper.log`, `diagnostics.rs:24`) und nennt die Workspace-Id im Bericht. `write_playbook_temp` (`ansible.rs:95`) hängt pid und Sequenz an wie `generate_inventory` (`:81-87`); das Präfix `adminhelper_ansible` bleibt für `is_confined_ansible_path` (`:113`). Der xfreerdp-Titel (`rdp.rs:265`) beginnt mit `[<Workspace-Name>] `; der Name wird eigens mit `sanitize_window_title` gesäubert, die Klammern kommen danach. Tests (`per_process_*`): zwei Playbooks gleichen Namens → zwei Pfade, beide von `is_confined_ansible_path` angenommen; RDP-Titel mit und ohne Workspace; Diagnose-Logpfad je Logname.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- per_process
Doku: keine (intern; Doku mit T33)
Abhängt von: T1

### T10 — Start: Launcher und Workspace-Prozess  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/tauri.conf.json, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/diagnostics.rs, apps/desktop/src-tauri/src/port_registry.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/migration.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @9e4ea074 2026-10-20T08:44:04+02:00
Review: approve (.ah-out/review/desktop-workspaces/T10.verdict.json)
Windows: CI `rust-windows` (Lauf 39382111120, workflow_dispatch @1851626f, 2026-10-20) grün, Lock-Freigabe in `Drop` und `is_open`
Änderung: `main.rs` liest den Modus (T1) vor dem Builder: das Single-Instance-Plugin (`main.rs:56-68`) nur im Launcher (erst jetzt, nach T3), die Logdatei nach `log_name` (`:79-80`). In `setup` (`:94-115`): Migration (T4) statt `migrate_legacy_local_store` (`:105`; die Funktion in `storage.rs:140` entfällt, `migrate_between` und seine Tests bleiben); im Workspace-Modus Registry-Eintrag prüfen (unbekannt → Logzeile, Exit 2), `acquire` (belegt → Logzeile, Exit 3), Kontext setzen; erst danach entsteht das Fenster `main` per `WebviewWindowBuilder` mit `window_title` (Launcher „AdminHelper“, kleiner). `app.windows` in `tauri.conf.json` (`:14`) wird leer, `enableGTKAppId` bleibt `false`. Die Entscheidung ist eine reine Funktion `startup(mode, registry, lock) -> Plan` in `workspace.rs`; `main.rs` ist Verdrahtung (Framework-Wiring, Beweis: smoke und Live-Specs im Sammellauf). Tests (`startup_*`): Launcher; bekannte Id mit freiem Lock; unbekannte Id; belegter Lock. Dazu (Prüfer-Hinweise zu T1): das modulweite `expect(dead_code)` in `workspace.rs` entfernen (nicht stehen lassen, es verdeckt sonst tote Reste); entscheiden und testen, wohin die Logzeile eines zweiten Starts mit belegtem Lock (Exit 3) geht, ohne in die Logdatei des Halters zu schreiben. Dazu (T2): unter Windows die Sperre ausdrücklich freigeben (`unlock()` in `is_open` und ein `Drop` für `InstanceLock`); gezielte `expect(dead_code)` an Elementen ohne Aufrufer (`is_open` bis T11, `PALETTE` bis T4/T11). Dazu (Prüfer zu T4): `migration::migrate` nicht best-effort aufrufen; scheitert sie, startet kein Prozess weiter (Logzeile, Exit), sonst legt T11 später eine neue Registry an und die Altdaten werden nie übernommen; die Logzeile nennt Datei und Position, keinen Wert. Workspace-Verzeichnisse mit 0700 anlegen; vor dem Aufräumen in `migrate` abbrechen, wenn `<base>/workspaces` ein Symlink oder eine Junction ist; optional `sync_all` vor dem Umbenennen des Commit-Markers. Das `expect(dead_code)` am Migrationsmodul, an `DEFAULT_OWNER` und `rename_owner` entfernen. Nachtrag (T5): `write_json_atomic` (`storage.rs`) ruft `sync_all` auf der Temp-Datei vor dem `rename`, damit nach einem Stromausfall weder `prefs.json` noch `workspace.json` leer ist (sonst den Doc-Kommentar abschwächen); `Registry::store` (`workspace.rs`) schreibt über `write_json_atomic` statt `write_json_pretty`, damit der Launcher unter Windows keine halbe `workspaces.json` liest. Nachtrag (T9): den Kommentar an der Logdatei in `main.rs` (heute „adminhelper.log … the diagnostics report reads it back“) auf `log_name` je Prozess anpassen; die Ausgabe der Diagnose (`diagnostics.rs`, heute `adminhelper-diagnostics-<ts>.txt`) heißt `<log_name>-diagnostics-<ts>.txt`, damit zwei Workspaces in derselben Sekunde sich nicht überschreiben. Nachtrag (T11): Den Aufruf der Waisen-Bereinigung der Portkarte (`launcher.rs`, T11) beim Start im Launcher-Modus setzt T10, weil erst T10 den Modus beim Start kennt. Nachtrag (T11): Mit dem Aufruf von `launcher::drop_orphan_ports` beim Start entfallen die `expect(dead_code)` an `PortRegistry::retain_owners` und `update` (`port_registry.rs`) und an `drop_orphan_ports`; `InstanceLock::drop` ruft unter Windows `unlock()` (Tests prüfen direkt nach `drop`, ob der Lock frei ist). Nachtrag (security T7): Der erste Abgleich eines Prozesses leert `run/` und setzt damit voraus, dass je Workspace genau ein Prozess läuft; den Workspace-Lock (`acquire`) vor `set_current` und vor dem ersten `refresh_tunnel` nehmen, Test dazu.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- startup_
Doku: keine (intern; Doku mit T33)
Abhängt von: T3, T4, T5, T7

## Block B — Launcher

### T11 — Launcher: Liste, Anlegen, Bearbeiten, Waisen der Portkarte  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/main.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @6108bc69 2026-10-19T17:00:28+02:00
Review: approve (.ah-out/review/desktop-workspaces/T11.verdict.json)
Änderung: Neues Modul `launcher.rs` (SPDX-Header). `list(base)`: Workspaces mit Name, Farbe, Art, Host (aus der URL) und `open` (Lock-Probe), `lastUsed`; `migratedNotice` kommt einmal mit und wird dabei zurückgesetzt; Registry-Einträge ohne Verzeichnis fallen mit Logzeile heraus. `save(base, draft)`: neu → Id `w-<8 hex>` (aus Zeit, pid und Zähler über `sha2`, eindeutig gegen vorhandene), `<id>.partial/` mit `workspace.json` (`legacyKeys: false`), umbenennen, dann Registry; Bearbeiten nur geschlossen (Lock für die Dauer gehalten), Art fest; Name, Farbe und URL änderbar. Prüfung an der Grenze: Name 1–40 Zeichen ohne Steuerzeichen, Farbe aus der Palette, URL je Art (Server: `validation::validate_server_url_secure`; Sync: https), kein Netzzugriff. Beim Launcher-Start entfernt `retain_owners` (T3) die Portkarten-Einträge von Besitzern ohne Workspace. In `main.rs` nur `mod launcher;` und der Aufruf beim Start. Tests: Liste mit offenem und geschlossenem Workspace; Hinweis genau einmal; Anlegen je Art; ungültige Eingaben; Bearbeiten eines geöffneten → Fehler; Ids eindeutig; Registry-Eintrag ohne Verzeichnis fällt heraus; Waisen der Portkarte weg, Einträge vorhandener Workspaces bleiben. Hinweis (T2): unter Windows schreibt `write_json_pretty` in place; `list` kann eine halb geschriebene `workspace.json` eines offenen Workspace lesen. Dazu (Prüfer zu T4): keine neue `workspaces.json` anlegen, solange keine existiert (die legt nur die Migration an). Nachtrag (Session, Baustart): In `main.rs` nur `mod launcher;`; die Bereinigung der Waisen ist eine Funktion in `launcher.rs` mit Tests, ihren Aufruf beim Start setzt T10. Der Hinweis (T2) zu halb geschriebenen `workspace.json` ist mit T5 erledigt (`Meta::store` schreibt atomar).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- launcher::
Doku: keine (intern; Doku mit T33)
Abhängt von: T2, T3

### T12 — Launcher: Workspace öffnen und Launcher holen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/launcher.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @21ec585e 2026-10-19T17:24:51+02:00
Review: approve (.ah-out/review/desktop-workspaces/T12.verdict.json)
Änderung: `open(base, id, spawner)`: geöffnet → Fehler ohne Start; sonst `lastUsed` setzen, `current_exe() --workspace <id>` abgekoppelt starten (Unix `process_group(0)`, Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, stdio null), warten, bis der Lock gehalten wird (höchstens 10 s, Probe alle 200 ms); endet das Kind vorher oder läuft die Frist ab → Fehler. `open_launcher(spawner)` startet `current_exe()` ohne Argumente abgekoppelt (die Übergabe an einen laufenden Launcher macht das Plugin). Der Spawner ist ein Trait, damit der Ablauf ohne echten Prozess testbar ist. Tests: geöffneter Workspace → Fehler, kein Spawn; Kind hält den Lock → Ok und `lastUsed`; Kind endet sofort → Fehler; Frist (im Test kurz) → Fehler.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- launcher::
Doku: keine (intern; Doku mit T33)
Abhängt von: T11

### T13 — Workspace löschen mit Self-Revoke  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/migration.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @1851626f 2026-10-20T09:30:48+02:00
Review: approve (.ah-out/review/desktop-workspaces/T13.verdict.json)
Änderung: Launcher-Seite `delete(base, id, spawner)`: nur geschlossen; startet `current_exe() --workspace <id> --purge` und wartet; Exit-Code → `ResetOutcome` (`revoked`/`localOnly`/`notEnrolled`), anderer Code → Fehler; erst danach geht der Registry-Eintrag. Purge-Modus (`main.rs`, kein Fenster): Lock nehmen, Kontext setzen, `purge(ws, revoke)`: bei Server-Workspaces Self-Revoke über `enrollment::reset_identity(url)` (`enrollment.rs:352`, löscht `enroll|*` des Präfixes), die Keyring-Schlüssel aus `secrets.json` löschen (bei `legacyKeys` nicht), Portkarte `release(id)` (T3), Verzeichnis löschen; Exit-Code nach Ergebnis. Tests: Ablauf mit Spawner-Doppel (Exit-Codes → Outcome, Registry erst nach Erfolg, geöffneter Workspace → Fehler ohne Spawn); `purge` mit Temp-Verzeichnis, `keyring_store::memory()` und Revoke-Doppel: Schlüssel weg, Portkarten-Einträge weg, Verzeichnis weg; Lokal-Workspace ohne Revoke; `legacyKeys` behält die RDP-Schlüssel. Nachtrag (T11): Ein Workspace, dessen `workspace.json` fehlt oder nicht lädt, steht nicht in `launcher::list` (Logzeile), behält aber Id, Verzeichnis und Ports; Löschen geht über die Id und darf nicht an `Meta::load` scheitern. Nachtrag (T6): Die migrierten Workspaces (`standard`, `lokal`, `sync`, `server`) tragen alle `legacyKeys` und teilen sich die Schlüssel ohne Präfix (`enroll|*`, `rdp|*`): `purge` eines Workspace mit `legacyKeys` löscht keine geteilten Altschlüssel und setzt keine geteilte Identität zurück, solange ein anderer Workspace mit `legacyKeys` besteht (Test dazu). Namen aus `secrets.json` löscht `purge` nur, wenn sie mit dem eigenen Präfix beginnen; ein Name ohne dieses Präfix bricht ab, statt einen fremden Schlüssel zu löschen (fail closed, Test). Zum Löschen gehört auch `<Präfix>enroll|replaces` (`enrollment.rs:43`), den `reset_identity` nach dem Widerruf schreibt. Nachtrag (T10-Review): `workspace::startup` behandelt `--purge` heute wie das Öffnen (kaputte `workspace.json` → Exit 1, Registry-Eintrag ohne Verzeichnis → Exit 2); für den Purge lockern, damit Löschen über die Id nicht an `Meta::load` scheitert und ein fehlendes Verzeichnis kein Fehler ist (Test: Purge bei kaputter `workspace.json` und bei fehlendem Verzeichnis). Der Platzhalter in `main.rs` („this build does not purge workspaces“, Exit 1) fällt weg.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- launcher::
Doku: keine (intern; Doku mit T33)
Abhängt von: T6, T10, T12

### T14 — Tauri-Commands der Workspaces  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/password.rs
Evidenz: run.sh[quick] desktop-rs desktop-ui: 2 passed, 0 failed, 16 skipped @d2f6dcc2 2026-10-20T10:10:53+02:00
Review: approve (.ah-out/review/desktop-workspaces/T14.verdict.json)
Änderung: Neue Commands `workspace_context` (Launcher oder Workspace mit `WorkspaceInfo`), `list_workspaces`, `save_workspace`, `delete_workspace`, `open_workspace` (nur Launcher; nach Erfolg beendet sich der Launcher) und `open_launcher` (nur Workspace); die Zuständigkeit prüft eine reine Funktion in `workspace.rs`. IPC-Typen `WorkspaceInfo{id, name, color, kind, host, open}`, `WorkspaceList{workspaces, lastUsed, migratedNotice}`, `WorkspaceDraft{id?, kind, name, color, url?}`, `WorkspaceContext{launcher, workspace?}` in `models.rs` und `types.ts` (Parität). Registriert in `generate_handler!` (`main.rs:116`), Bridge-Funktionen in `index.ts`, Zeilen in der Command-Tabelle von `desktop.html` DE+EN (`:80`). Tests: Rust — Launcher-Command im Workspace-Modus und `open_launcher` im Launcher → Fehler; vitest — `ipc.inventory.test.ts` und `types.parity.test.ts` grün. Nachtrag (T5): Das Command `load_settings` ruft `storage::load_settings_for_webview` (setzt die Basis des Drei-Wege-Abgleichs), die Rust-internen Leser bleiben bei `storage::load_settings`; das `#[expect(dead_code)]` an `load_settings_for_webview` entfällt. Nachtrag (T11): `WorkspaceInfo`, `WorkspaceList` und `WorkspaceDraft` aus `launcher.rs` nach `models.rs` verschieben (serde, camelCase) statt neu anlegen; `save_workspace` wartet beim Bearbeiten bis zu 2 s auf den Lock und läuft deshalb nicht auf dem UI-Thread (async Command oder `spawn_blocking`); die `expect(dead_code)` an `list`/`save` und den Typen entfallen. Nachtrag (T12): `open_workspace` wartet bis zu 10 s (`launcher::open(&base, &id, &launcher::AppSpawner::new()?)`) und läuft wie `save_workspace` nicht auf dem Main-Thread; die `expect(dead_code)` an `open`, `open_launcher` und `AppSpawner::new` entfallen. Nachtrag (T13-Reviews): `delete_workspace` wartet bis zu 120 s (`PURGE_TIMEOUT`, `DELETE_GUARD`) und läuft wie `save_workspace`/`open_workspace` nicht auf dem Main-Thread (`launcher::delete(&base, &id, &launcher::AppSpawner::new()?)`); das `expect(dead_code)` an `delete` entfällt; `delete_workspace` nur im Launcher. In `launcher.rs` `purge` liest `hand_over_keys` die Datei `legacy-secrets.json` heute erst nach Widerruf und `purge_identity`: im geteilten Fall vorab lesen (bei leerer Menge gar nicht), wie der Doc-Kommentar sagt; Test mit kaputter Datei → kein Widerruf.
Verify: bash scripts/dev/verify.sh desktop-rs desktop-ui --strict
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Command-Tabelle)
Abhängt von: T10, T13

### T15 — Login und Registrierung an die Workspace-URL gebunden; dieselbe Anmeldung nur einmal  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/enrollment.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @291efa76 2026-10-20T10:32:34+02:00
Review: approve (.ah-out/review/desktop-workspaces/T15.verdict.json)
Änderung: `login` (`commands.rs:295`) und `enroll_with_token` (`:120`) nehmen nur die URL des Workspaces an; hat er noch keine, gilt die übergebene (gespeichert wird sie nach dem Login über `save_settings`, T5). `login` lehnt außerdem ab, wenn ein anderer Workspace derselben normierten Origin (Schema, Host ohne Groß/Klein, Port mit Standardport) denselben `lastUsername` (ohne Groß/Klein) trägt; der Fehlertext nennt den anderen Workspace. Beides als reine Funktionen in `workspace.rs`. Tests (`login_binding_*`): andere URL → abgewiesen; ohne Workspace-URL → angenommen; gleiche Origin und Benutzer in anderem Workspace → abgewiesen; anderer Benutzer → erlaubt; `https://H` und `https://h:443/` gleich. Nachtrag (security T14): Der Launcher darf heute die URL eines schon eingeschriebenen, geschlossenen Workspace ändern; ein späterer Purge schickt den Widerruf dann an die neue URL und meldet bei Erfolg eines fremden Servers `Revoked`, obwohl der ausstellende Server nie widerrufen hat. Mit der Bindung an die Workspace-URL: Ändert sich die Origin eines Workspace mit Geräte-Identität, wird die Identität vorher zurückgesetzt (Widerruf gegen die alte URL) oder die Änderung abgelehnt; Test dazu. Dazu (Nit): `workspace::context` und `launcher::edit` reichen Fehler von `Meta::load` roh weiter; wie `mark_opening` über `workspace::failure` (Datei und Position, kein Wert).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- login_binding
Doku: keine (intern; Doku mit T33)
Abhängt von: T14

### T38 — Widerruf der Geräte-Identität nur über HTTPS und an die Workspace-URL gebunden  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/workspace.rs
Änderung: Kevin 2026-10-20 (Härtung zur Bindung an die Workspace-URL, aus dem security-Review zu T15): Der Widerruf der Geräte-Identität geht nur über HTTPS (`validate_https_url` statt der Prüfung, die Loopback-HTTP zulässt). `reset_device_identity` nimmt die URL nicht mehr aus der Webview, sondern die des Workspace (wie `sign_in_target` in T15); dasselbe für `reset_server_cert_pin` und `check_server_cert`, soweit sie eine Server-URL des Workspace betreffen. Das Speichern der ersten oder einer geänderten Server-URL über die Einstellungen (`storage::meta_with`) wird bei vorhandener Geräte-Identität wie in `launcher::edit` abgelehnt und die URL dort validiert. Fehlertexte nennen höchstens die Origin, nie die ganze gespeicherte URL. Tests: Widerruf gegen eine HTTP-URL wird nicht versucht (kein Revoked); `reset_device_identity` mit fremder URL wirkt auf die Workspace-URL bzw. wird abgelehnt; `meta_with` lehnt einen Origin-Wechsel bei Identität ab; Fehlertext ohne Userinfo. Nachtrag (T15-Review): `sign_in_url` gibt die gespeicherte URL getrimmt zurück (`kept.trim()`); `meta_with` vergleicht die Server-URL per Origin wie `sign_in_url` (heute exakt, dann scheitert das Speichern nach einem Login mit anders geschriebener URL still und `lastUsername` fehlt), Test dazu.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- login_binding
Doku: keine (intern; Doku mit T33)
Abhängt von: T15

## Block C — Windows-RDP-Passwörter

### T16 — Spike: TERMSRV just-in-time für mstsc  [ ]
Komponente: desktop-rs · Dateien: docs/features/desktop-workspaces.md, apps/desktop/src-tauri/src/password.rs
Änderung: Microsoft-Doku nachlesen (`CredWriteW`/`CredDeleteW`, Typ `CRED_TYPE_GENERIC` vs. `CRED_TYPE_DOMAIN_PASSWORD` für `TERMSRV/…`, `CRED_PERSIST_SESSION` vs. `CRED_PERSIST_LOCAL_MACHINE`, wann mstsc den Eintrag liest, Wiederverbindung) und das Ergebnis mit Quellen in den Spec-Abschnitt „Windows-RDP: Ergebnis des Spikes“ schreiben: Typ, Persistenz, Löschzeitpunkt (nach Ende von mstsc oder nach fester Frist), was unverifiziert bleibt. Dazu eine reine Plan-Funktion `termsrv_plan(target, loopback, stored_password) -> Vec<Schritt>` (Schreiben, Starten, Löschen; Loopback ohne Passwort: vorhandenes `TERMSRV` löschen) mit Tests auf allen Plattformen (`termsrv_plan_*`) und ein `cfg(windows)`-Probetest (`termsrv_probe_*`), der einen eindeutigen `TERMSRV/…`-Testeintrag mit Typ und Persistenz aus dem Spike schreibt, liest und löscht. Der Probetest läuft nur im CI-Job `rust-windows` (Lauf per `workflow_dispatch`, siehe Kopfnotiz); die Session hält das Ergebnis im Ledger fest. Unter Windows nicht verifiziert (mstsc).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- termsrv
Doku: docs/features/desktop-workspaces.md (Ergebnis des Spikes)
Abhängt von: T6

### T17 — Windows: RDP-Passwort im App-Namensraum, TERMSRV nur für den Start  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/src-tauri/src/connection/rdp.rs
Änderung: Unter Windows speichert `save_password` (`password.rs:315`) das Passwort im App-Namensraum über `keyring_store` unter dem RDP-Schlüssel des Workspace (T6, aus der Verbindung wie gelistet) und trägt ihn in `secrets.json` ein; `delete_password` löscht ihn (bei `legacyKeys` zusätzlich ein vorhandenes `TERMSRV/<gelistete Adresse>`); `password_state` (`:279`) meldet den Eintrag, bei `legacyKeys` zusätzlich ein vorhandenes `TERMSRV/<gelistete Adresse>` (Stand vor R-0431). `open_rdp_with_stored_password` (`connection/mod.rs:151`) lädt unter Windows nach `check_credential_connection` das Passwort aus dem App-Namensraum; `open_rdp_windows` (`rdp.rs:158-182`) führt `termsrv_plan` (T16) aus: für die aufgelöste Adresse `TERMSRV` schreiben, mstsc starten, nach der Vorgabe des Spikes löschen; bei Loopback-Zielen ohne Passwort ein vorhandenes `TERMSRV` vorher löschen. Tests: `termsrv_plan` je Fall (bleibt aus T16) und `cfg(windows)`-Tests für Speichern, Status und Löschen im App-Namensraum (CI-Job `rust-windows`); unter Unix unverändert (bestehende Tests grün). Unter Windows nicht verifiziert (mstsc); Prüfanleitung in T33. Nachtrag (T9): Bleibt vom Workspace-Namen nach `sanitize_window_title` nichts übrig (nur Emoji oder Symbole), nimmt der RDP-Titel die Workspace-Id als Präfix (`rdp.rs`, Test `per_process_rdp_title_without_a_sanitized_workspace_name_has_no_prefix` anpassen). Nachtrag (T6): `rdp_storage_key` (`password.rs:49`) ist `pub` und liefert den Schlüssel ohne Workspace-Präfix; als Keyring-Schlüssel gilt nur, was `rdp_storage_keys` (`password.rs:72`, heute `cfg(unix)`) liefert. Unter Windows denselben Weg nehmen (das `cfg` aufheben), nie `rdp_storage_key` direkt. Nachtrag (T8): Für RDP prüft `tunnel.rs` bei `host:port` im Host-Feld beide Ports, weil nicht verifiziert ist, welchen mstsc (`full address:s:<host>:<port>:3389`) und FreeRDP (`/v:host:port:port`) nehmen; die Prüfanleitung für Kevin (T33) nimmt den Fall auf.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- termsrv
Doku: keine (intern; Doku mit T33)
Abhängt von: T8, T16

### T37 — RDP-Altschlüssel aus der Zeit vor den Workspaces gehen mit dem letzten migrierten Workspace  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/launcher.rs
Änderung: Kevin 2026-10-20 (Restrisiko aus security T13 nicht hingenommen): Übernimmt `load_password_keyring` einen Schlüssel aus der Zeit vor den Workspaces (`rdp|<conn-id>|…` ohne Präfix), trägt es dessen Namen in den Index (`secrets.json`) des migrierten Workspace ein (die Ladefunktion bekommt dafür `base` bzw. den Workspace). Der Purge des letzten migrierten Workspace löscht zusätzlich die nie geladenen Altschlüssel `rdp|<target>` ohne Id, deren Namen er aus den Verbindungen dieses Workspace ableitet (dieselbe Ableitung wie beim Lesen). Unter Windows gilt dasselbe für den App-Namensraum (T17). Tests: übernommener Schlüssel steht danach im Index und ist nach dem letzten Purge weg; nie geladener Altschlüssel einer Verbindung des letzten migrierten Workspace ist nach dem Purge weg; ein Schlüssel ohne passende Verbindung bleibt (fail safe, nichts Fremdes löschen).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- workspace_keys
Doku: keine (intern; Doku mit T33)
Abhängt von: T13, T17

## Block D — Oberfläche

### T18 — Workspace-Store, Modell und Start der Oberfläche  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/workspace.ts, apps/desktop/ui/src/lib/stores/workspace.test.ts, apps/desktop/ui/src/lib/models/workspace.ts, apps/desktop/ui/src/lib/models/workspace.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/stores/session.test.ts
Änderung: Neuer Store `stores/workspace.ts` (SPDX-Header): `context` aus `workspaceContext()`, `list`, Aktionen `refresh`, `save`, `remove`, `open`, `openLauncher`. Neues Modell `models/workspace.ts` (SPDX-Header): Palette (gleich der Rust-Konstante), `validateDraft` (Name; URL je Art mit den Regeln aus `validateSettings`), `hostOf(url)` für die Namensvorbelegung. `hydrate` (`session.ts:70`) lädt den Kontext mit; `needsLogin` gilt nur im Workspace-Prozess. Tests (beide neuen Testdateien mit SPDX-Header): Store mit gemockter Bridge; `validateDraft` und `hostOf`; `hydrate` im Launcher → kein Login, Server-Workspace ohne Sitzung → Login.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/workspace.test.ts src/lib/models/workspace.test.ts src/lib/stores/session.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T14

### T19 — Workspace-Editor: anlegen und bearbeiten  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/WorkspaceEditor.svelte, apps/desktop/ui/src/components/WorkspaceEditor.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neue Komponente (SPDX-Header): Art (Server/Sync/Lokal; beim Bearbeiten fest), Name (bei Server und Sync mit dem Host vorbelegt, bis der Nutzer ihn selbst ändert), Farbe aus der Palette, URL je Art; beim Ändern einer URL die Warnung, dass Anmeldung und Geräte-Identität zur alten Installation gehören und eine andere Installation ein neuer Workspace ist. Kein Netzkontakt. Texte DE+EN. Tests (SPDX-Header): Name folgt dem Host bis zur eigenen Eingabe; ungültige URL sperrt Speichern; URL-Änderung zeigt die Warnung; Speichern ruft `save` mit dem Entwurf.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/WorkspaceEditor.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

### T20 — Picker im Launcher  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Picker.svelte, apps/desktop/ui/src/components/Picker.test.ts, apps/desktop/ui/src/App.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neue Komponente (SPDX-Header): Liste mit Farbpunkt, Name, Art-Icon, Host bzw. „Lokal“ und „geöffnet“; Vorauswahl `lastUsed`, Pfeiltasten und Enter öffnen; ein geöffneter Workspace lässt sich nicht öffnen (Hinweis); einmaliger Hinweis nach der Migration; „Neuer Workspace“ und „Bearbeiten“ (nur geschlossen) öffnen den Editor (T19); „Löschen“ nur geschlossen, die Bestätigung nennt den Namen, bei Lokal mit Datenverlust-Hinweis, nach `localOnly` der bekannte Hinweis „nur auf diesem Gerät“. `App.svelte` (`:20-28`) zeigt im Launcher den Picker. Texte DE+EN. Tests (SPDX-Header): Vorauswahl und Enter rufen `open(lastUsed)`; geöffneter → kein Aufruf; Löschen fragt mit Namen, `localOnly` → Hinweis; Migrationshinweis genau einmal. Nachtrag (T12): Der Picker sperrt den Öffnen-Knopf, solange `open_workspace` läuft (zwei gleichzeitige Aufrufe derselben Id liefern sonst beide Ok, das zweite Kind endet mit Exit 3).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Picker.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T19

### T21 — Workspace im Fenster kenntlich: Chip, Farbstreifen, „Workspaces…“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/ui/ConfirmDialog.svelte, apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/components/AppShell.workspace.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Ein Chip oben in der Sidebar (Farbpunkt + Name) ersetzt das Modus-Badge (`AppShell.svelte:101`, `:228`); Klick oder „Workspaces…“ ruft `openLauncher`. 4-px-Farbstreifen am Fensterrand in der Workspace-Farbe. Seiten mit `serverOnly` rendern nur bei `isServerMode` (`:87`), sonst das Dashboard (`currentId :91`). `ConfirmDialog` nennt im Workspace-Prozess Farbpunkt und Namen über der Frage. Texte DE+EN. Tests (neue Datei, SPDX-Header): Chip zeigt Name und Farbe, Klick ruft `openLauncher`; `/infrastructure` in einem lokalen Workspace zeigt das Dashboard; `ConfirmDialog` zeigt den Namen, im Launcher nicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.workspace.test.ts src/components/ui/primitives.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

### T22 — Login: „Anmelden bei ● Name“, feste URL, „Workspaces…“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/Login.workspace.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Überschrift „Anmelden bei ● <Name>“; die URL ist Anzeige, ein Eingabefeld gibt es im Login (`Login.svelte:264`) und in der Token-Registrierung (`:354`) nur, solange der Workspace keine URL hat. „Ohne Server fortfahren“ (`useLocal :138`, Knopf `:348`) wird „Workspaces…“ (`openLauncher`); `setMode` (`session.ts:152`) entfällt. Texte DE+EN. Die bestehenden `Login.*.test.ts` bleiben gültig (sie setzen keine URL). Tests (neue Datei, SPDX-Header): mit URL kein URL-Feld, Login nimmt die Workspace-URL; ohne URL das Feld wie heute; „Workspaces…“ ruft `openLauncher`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

### T23 — Einstellungen: „Dieser Workspace“ und „Alle Workspaces auf diesem Gerät“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.workspace.test.ts, apps/desktop/ui/src/lib/stores/settings.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/stores/session.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Das Modus-Radio (`SettingsModal.svelte:349-383`) entfällt. Abschnitt „Dieser Workspace“: Name, Farbe, URL als Anzeige mit dem Hinweis, dass sie im Picker bei geschlossenem Workspace änderbar sind, Abmelden, self-signed, Pin, Identität, Token, Browser-Zertifikat, Benachrichtigungsregeln, bei Sync das Intervall. Abschnitt „Alle Workspaces auf diesem Gerät“: Sprache, Passwörter, RDP, OS-Benachrichtigungen, Diagnose. `saveSettings` (`settings.ts:79-156`) ohne Moduswechsel und ohne erzwungenes Abmelden: prüfen, speichern, neu laden, Sprache setzen, bei Sync den Takt neu starten; Tunnel und Sitzung bleiben unberührt. `serverLogout` (`:158`) und `dropSession` (`session.ts:131`) verlieren ihre Aufrufer und gehen. Der Test `saving in server mode leaves a running tunnel alone (R-0245)` prüft künftig, dass Speichern weder Tunnel noch Abmelden anfasst. Brauchen bestehende `SettingsModal.*.test.ts` Mocks des Workspace-Stores, erweitert die Task `Dateien:` per `ledger.sh set-files`. Texte DE+EN. Tests (neue Datei, SPDX-Header): Abschnitte und Felder je Art; Speichern ruft weder `stopTunnel` noch `logout`; ein geändertes Sync-Intervall startet den Takt neu.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/settings.test.ts src/lib/stores/session.test.ts src/components/SettingsModal
Doku: keine (intern; Doku mit T33)
Abhängt von: T18
Test-Löschung: apps/desktop/ui/src/lib/stores/settings.test.ts::a server-URL change with an active session logs out before saving — im Workspace ist die URL fest, ein URL-Wechsel ist ein neuer Workspace; apps/desktop/ui/src/lib/stores/settings.test.ts::a server-URL change with an active session reloads the window after saving (R-0429) — wie oben; apps/desktop/ui/src/lib/stores/settings.test.ts::a server-URL change without a session saves without a reload — wie oben; apps/desktop/ui/src/lib/stores/settings.test.ts::a failed save after the forced logout does not reload — es gibt kein erzwungenes Abmelden mehr; apps/desktop/ui/src/lib/stores/settings.test.ts::saving in server mode still starts the tunnel when the status call fails — Speichern startet keinen Tunnel mehr, das tut der Start des Workspace-Fensters; apps/desktop/ui/src/lib/stores/settings.test.ts::saving in server mode starts the tunnel when none runs — wie oben; apps/desktop/ui/src/lib/stores/settings.test.ts::switching server->local stops the tunnel and drops the session — der Moduswechsel entfällt, die Art ist je Workspace fest; apps/desktop/ui/src/lib/stores/settings.test.ts::switching server->sync stops the tunnel and drops the session — wie oben; apps/desktop/ui/src/lib/stores/session.test.ts::ends the session in Rust and clears the in-memory one — `dropSession` hat keinen Aufrufer mehr; apps/desktop/ui/src/lib/stores/session.test.ts::still clears the local session when the server logout call fails — wie oben

### T24 — OS-Benachrichtigung mit Workspace-Präfix  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/osNotify.ts, apps/desktop/ui/src/lib/osNotify.test.ts
Änderung: `notifyOs` (`osNotify.ts:33-47`) stellt Einzel- und Sammelmeldung „[<Name>] “ voran, Name aus dem Workspace-Store; im Launcher ohne Präfix. Tests (neue Datei, SPDX-Header, Plugin gemockt): Präfix in beiden Wegen; ohne Workspace kein Präfix.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/osNotify.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

## Block E — Live-E2E

### T25 — WebDriver startet Launcher oder Workspace nach AH_E2E_WORKSPACE  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/wdio.conf.js, apps/desktop/e2e/test/lib/app-args.js, apps/desktop/e2e/test/unit/app-args.test.js
Änderung: `tauri:options.args` (`wdio.conf.js:62-66`) kommt aus einer reinen Funktion in `test/lib/app-args.js` (SPDX-Header): `AH_E2E_WORKSPACE` gesetzt und nicht leer → `['--workspace', <id>]` (Id gegen dieselbe Regel wie in Rust geprüft, sonst Fehler beim Laden der Config), sonst `[]` (Launcher; der smoke-Spec läuft damit unverändert gegen den Launcher und prüft die Übergabe beim zweiten Start). Unit-Test unter `node --test` (SPDX-Header): gesetzt, leer, ungesetzt, ungültig. Das Verify ist Lint plus Unit-Tests; der echte Beweis kommt aus dem Sammellauf.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T10

### T26 — Live-Helfer und Specs mit fester Workspace-URL  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/lib/live.js, apps/desktop/e2e/test/specs/login-error.live.js, apps/desktop/e2e/test/specs/enroll-form.live.js, apps/desktop/e2e/test/specs/enroll-trust-dialog.live.js
Änderung: `login()` (`live.js:65-89`) füllt die URL nur, wenn das Feld da ist (nach dem ersten erfolgreichen Login ist sie fest), Benutzer und Passwort über den Feldtyp statt über die Position; ein Helfer `fillServerUrlIfAsked()` für die Specs mit URL-Feld (`login-error.live.js:14-16`, `enroll-form.live.js:27-35`, `enroll-trust-dialog.live.js:25-26`). Die Specs prüfen, dass die angezeigte URL die erwartete ist, wenn kein Feld da ist. Verify ist der Lint; Beweis im Sammellauf.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T22

### T27 — Orchestratoren starten den Standard-Workspace  [ ]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/box_desktopbox.sh, scripts/tests/desktop_e2e_crud.sh
Änderung: `lib_e2e_stack.sh` exportiert neben den WebKit-Variablen (`:33`) `AH_E2E_WORKSPACE=standard` (alle `desktop_e2e_*.sh` sourcen sie), `box_desktopbox.sh` (`:41-43`) ebenso; das Seeden der alten `settings.json` bleibt und testet damit die Migration. `desktop_e2e_crud.sh` (`:45-84`): der Nachweis der Vertrauens-Zustimmung liest `workspaces/standard/workspace.json` statt `settings.json`; vor dem erneuten Seeden löscht das Skript `workspaces.json`, `workspaces/` und `prefs.json` unter `$XDG_DATA_HOME/com.admincave.adminhelper` mit vollem Pfad, damit die Migration erneut läuft. `lib_e2e_stack_test.sh` prüft den Export.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Test)
Abhängt von: T25

### T28 — Live-E2E: Picker ersetzt den Moduswechsel  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/workspace-picker.live.js, apps/desktop/e2e/test/specs/settings-mode.live.js, scripts/tests/desktop_e2e_crud.sh
Änderung: Neuer Spec (SPDX-Header), läuft im Launcher (`AH_E2E_WORKSPACE` leer): der Picker zeigt „Standard“ als Server-Workspace und einmal den Migrationshinweis; „Neuer Workspace“ Lokal „E2E Lokal“ mit Farbe anlegen, umbenennen, löschen (die Bestätigung nennt den Namen; Datenverlust-Hinweis). `desktop_e2e_crud.sh` ruft ihn statt `settings-mode.live.js` (`:84`) als eigenen wdio-Lauf mit leerem `AH_E2E_WORKSPACE` am Ende. Öffnen aus dem Picker (abgekoppelter Prozess außerhalb von WebDriver) beweisen T12 und T32.
Verify: bash scripts/dev/verify.sh desktop-e2e scripts --strict
Doku: keine (Test)
Abhängt von: T20, T27
Test-Löschung: apps/desktop/e2e/test/specs/settings-mode.live.js::* — der Moduswechsel in den Einstellungen entfällt, ersetzt durch workspace-picker.live.js

### T29 — E2E-Stack: zwei Installationen nebeneinander  [ ]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, docker-compose.test.yml
Änderung: `e2e_init` (`lib_e2e_stack.sh:93`) bekommt einen optionalen Stack-Schlüssel (`a`/`b`) mit eigenem Projekt, Arbeitsverzeichnis, Ports (Daten-, Postgres-, Redis-Port mit Versatz), Bind-Adresse (`a` = `127.0.0.1`, `b` = `127.0.0.2`; ohne Schlüssel wie heute), `FRP_BIND_PORT`/`FRP_HTTPS_PORT` (`b`: 7001/7444) und `E2E_SERVER_URL`; `e2e_stack_use <a|b>` schaltet die globalen Variablen um, der Teardown räumt beide Stacks ab. `docker-compose.test.yml` (Gateway-Ports `:55-60`) veröffentlicht unter `${ITEST_BIND_IP:-0.0.0.0}`, damit beide Stacks die feste Enrollment-Ebene :8444 auf ihrer eigenen Loopback-Adresse halten. Bestehende Orchestratoren bleiben unverändert. `lib_e2e_stack_test.sh` (ohne Docker): zwei Stacks haben disjunkte Ports, Projekte, Arbeitsverzeichnisse und URLs; ohne Schlüssel bleibt alles wie bisher. Nicht gefahren: Veröffentlichung auf `127.0.0.2`.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Test)
Abhängt von: T27

### T30 — WebDriver mit zwei Workspace-Prozessen gleichzeitig  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/wdio.workspaces.conf.js, apps/desktop/e2e/test/lib/app-args.js, apps/desktop/e2e/test/unit/app-args.test.js, apps/desktop/e2e/eslint.config.js
Änderung: Neue Config `wdio.workspaces.conf.js` (SPDX-Header, Build und Hooks wie `wdio.conf.js`) für WebdriverIO-Multiremote: zwei Sitzungen `wsA`/`wsB` mit Args aus `AH_E2E_WORKSPACE_A`/`_B` (über `app-args.js`), zwei tauri-driver auf 4444/4445 und 4446/4447, beide beim Ende beendet. `app-args.js` liefert dazu die Port-Paare; Unit-Tests dafür. Spec-Glob nur `*.workspaces.js`, damit `npm test` (smoke) ihn nicht greift; ESLint kennt die Multiremote-Namen. Nicht verifiziert: zwei WebKitWebDriver-Sitzungen unter einem Xvfb gleichzeitig; scheitert das im Sammellauf, `[?]` an Kevin (Rückfall: nacheinander, der Port des ersten hält ein Listener).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T25

### T31 — Live-Specs: zwei Installationen, derselbe Visitor-Port  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/workspace-add-server.live.js, apps/desktop/e2e/test/specs/two-installations.workspaces.js
Änderung: `workspace-add-server.live.js` (SPDX-Header, Launcher): legt den Server-Workspace „Kunde B“ mit `AH_E2E_SERVER_URL_B` an und schreibt seine Id in die Datei aus `AH_E2E_WS_B_FILE`. `two-installations.workspaces.js` (SPDX-Header, Multiremote): `wsA` (Standard, Stack A) und `wsB` (Kunde B, Stack B) registrieren sich je mit ihrem Token (`AH_ENROLL_TOKEN_A`/`_B`), melden sich an und starten den Tunnel; `tunnel_status` beider zeigt denselben Server-Port und verschiedene lokale Ports; jeder öffnet seine SSH-Verbindung; `wsB` findet vor der Registrierung keine Identität (`is_device_enrolled` false), obwohl `wsA` registriert ist; ein zweiter Start `--workspace standard` aus Node endet mit Exit 3, während `wsA` läuft. Verify ist der Lint; Beweis im Sammellauf (T32).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T30

### T32 — Suite desktop_e2e_workspaces: zwei Stacks, zwei PKIs  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_workspaces.sh
Änderung: Neuer Orchestrator (SPDX-Header) nach dem Muster von `desktop_e2e_connect_tunnel.sh`: `e2e_require` wie dort, SKIP mit Exit 75 ohne tauri-cli (`desktop_e2e_skip_test.sh` prüft das per Glob mit); zwei Stacks (T29) je mit Gateway, frps, geseedetem Server, FRP-Konfiguration, SSH-Ziel (Host-Port 2222 bzw. 2223), verknüpfter Verbindung und STCP-Tunnel, vom Agent provisioniertem frpc und Enrollment-Token; prüft über die API, dass beide Installationen dem Tunnel denselben Visitor-Port gegeben haben. Seedet `settings.json` mit der URL von Stack A (Standard), führt `workspace-add-server.live.js` im Launcher und dann `two-installations.workspaces.js` mit `wdio.workspaces.conf.js` aus; danach: das SSH-Ziel A sah genau die Verbindung von `wsA`, Ziel B die von `wsB`; `workspaces/standard/` und `workspaces/<id B>/` enthalten nur die Verbindungen ihres Servers. `run.sh` und `heavy.sh` bleiben unberührt (Glob).
Verify: bash scripts/dev/verify.sh scripts --strict -- desktop_e2e_skip_test
Doku: keine (Test)
Abhängt von: T29, T31

## Block F — Doku

### T33 — Entwickler-Doku, README, CHANGELOG; rdp-error ohne Versuch; Windows-Prüfanleitung  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, README.md, CHANGELOG.md
Dedup-Key: bug:desktop-ui:connectFlow.ts:markRdpError
Änderung: `desktop.html` DE+EN: Abschnitt Workspaces (Launcher und Prozess je Workspace, Startargumente und Exit-Codes, Lock, Datenlayout, Migration nach „Standard“ und die Zusatz-Workspaces, Keyring-Präfix, Portkarte je Workspace mit Obergrenzen und Abweisung fremder Ports, Laufzeitdateien nur bei laufendem Tunnel, Schnitt global/Workspace, Logname je Prozess); der Satz zur Single-Instance (`:64`) gilt nur noch für den Launcher; „Server-Modus“ → „Server-Workspace“ (`:34`, `:66-78`, Server-Mode-Flow `:125`); Keyring-Schlüssel mit Präfix (`:100`); Windows-RDP-Passwörter (App-Namensraum, `TERMSRV` nur für den Start, Ergebnis des Spikes) mit einer Prüfanleitung für eine manuelle Abnahme unter Windows (zwei Workspaces, Passwort speichern, `cmdkey /list` vor, während und nach dem Start, Wiederverbindung, Tunnelziel mit demselben Server-Port in beiden); R-0524: der Satz zum RDP-Race-Guard (`:98`) sagt künftig, dass ein `rdp-error`-Event ohne passenden offenen Versuch in der Statusleiste gemeldet wird, aber keinen anderen Versuch markiert (`markRdpError`, `connectFlow.ts:79-95`; der Fall ohne Correlation-ID markiert alle offenen Versuche — nennen, wenn die Seite ihn beschreibt). `README.md`: Desktop-Abschnitt (Workspaces statt Modus, Dateiliste, Einstellungen). `CHANGELOG.md` unter `[Unreleased]`: Added (Workspaces, Picker, Kennzeichnung in Titel, Sidebar, OS-Benachrichtigung und RDP-Fenster; Windows-RDP-Passwörter für Tunnelziele), Changed (Moduswechsel entfällt; Migration nach „Standard“; zweiter Start öffnet den Launcher; Sync-Workspaces ohne Geräte-Zertifikat). Stellen beim Bau neu greppen. Nachtrag (T7): Die Doku nennt zwei Ausnahmen von „Laufzeitdateien nur, solange der Tunnel läuft“: Die Laufzeitdateien früherer Versionen im App-Datenordner verschwinden erst beim ersten Abgleich eines Workspace-Prozesses; stürzt frpc von selbst ab, bleiben die Dateien bis zum nächsten Abgleich, Stopp oder Programmende liegen. Nachtrag (T8, Kevin 2026-10-20): Die Doku nennt die hingenommenen Restrisiken der Port-Prüfung: Namen, die erst über DNS, /etc/hosts oder einen ssh_config-Alias auf Loopback zeigen; eine Web-URL, die per Redirect auf einen fremden Loopback-Port umleitet; ein Server, der über eigene Visitor-Einträge Ports eines anderen Workspace sperrt (scheitert sicher). Dazu: Ein Host, den die App nicht lesen kann (etwa IPv6 mit Zone, `host:port:port`), wird abgelehnt, solange ein anderer Workspace Ports belegt; Benutzer und Port gehören in ihre eigenen Felder. `connectFlow.ts` `resolveTarget` verschluckt Fehler von `resolve_connection` (RDP fragt dann erst nach dem Passwort, bevor `open_connection` ablehnt; Web ohne URL zeigt die URL-Prüfung statt des Port-Hinweises): den Fehler anzeigen statt weiterzumachen, Test dazu. Nachtrag (T13): Spec und Doku angleichen: die Identität ohne Präfix gilt nur als geteilt, wenn ein anderer migrierter Server-Workspace dieselbe Origin hat (Session 2026-10-20, statt „solange ein anderer Workspace mit legacyKeys besteht“ aus dem Nachtrag T6); `legacy-secrets.json` im Layout-Abschnitt der Spec; Spec-Zeile „bei legacyKeys keine RDP-Schlüssel“ durch die Übergabe an den letzten migrierten Workspace ersetzen; der Ausgang beim Löschen (`NotEnrolled` im geteilten Fall) in Text und Doku richtig benennen. Nachtrag (T15): Restrisiko in der Doku: zwei gleichzeitige Logins desselben Benutzers in zwei Workspaces können beide die Sperre „dieselbe Anmeldung nur einmal“ passieren (Prüfung nicht atomar).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/bridge/ipc.inventory.test.ts
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html · README.md · CHANGELOG.md
Abhängt von: T14, T16, T24

### T34 — Admin-Doku DE+EN, Teil 1: Einstieg, Benutzer, Betrieb, Fehlersuche  [ ]
Komponente: scripts · Dateien: docs/index.html, docs/en/index.html, docs/admin/index.html, docs/en/admin/index.html, docs/admin/benutzer.html, docs/en/admin/users.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html
Änderung: „Server-Modus“/„server mode“ → „Server-Workspace“/„server workspace“, Einstellungspfade („Einstellungen (Modus Server)“ → „Einstellungen des Workspaces“); auf `docs/admin/index.html` + EN ein Absatz Workspaces (mehrere Installationen nebeneinander, Picker, Login je Workspace, Löschen mit Widerruf). Stellen beim Bau neu greppen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/index.html + docs/en/index.html · docs/admin/{index,benutzer,betrieb,troubleshooting}.html + EN
Abhängt von: T33

### T35 — Admin-Doku DE+EN, Teil 2: Monitoring, Ansible, FRP, Agent-Rollout  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/admin/ansible.html, docs/en/admin/ansible.html, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Änderung: Wie T34 für die übrigen Seiten; `frp-tunnel.html`: der lokale Port gehört dem Workspace (Portkarte je Workspace), ein zweiter Workspace mit demselben Visitor-Port bekommt einen Ausweichport. Stellen beim Bau neu greppen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/{monitoring,ansible,frp-tunnel,agent-deployment}.html + EN
Abhängt von: T33
