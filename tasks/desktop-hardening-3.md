<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Härtung 3: Ansible-Laufverzeichnis, Playbook-Name, Sync-Doku, Pin-Reset, Provisionierungsbefehl — Task-Ledger
Status: erledigt · Branch: feature/desktop-hardening-3 · Review: pro Task
Spec: docs/features/desktop-hardening-3.md (Roadmap R-0748, R-0771, R-0817; Härtung, Kevin 2026-10-22)
Heavy: linux-full + windows — linux-full: T7 und T9 ändern den Provisionierungs-Tab, den `provisioning.live.js` zeigt, T5 den Pin-Reset in Login und Einstellungen, T1 den Ansible-Lauf (GUI-E2E im Sammellauf über `main`); windows = der Job `rust-windows` der PR-CI (keine Windows-VM im Pool): T1 legt das Laufverzeichnis unter `%TEMP%` an, T2 ändert den Namen, der an `wt`/`cmd` geht, T5 und T6 ändern `tofu.rs`; kein `scenario` (kein FRP-Datenpfad, keine PKI, `enrollment.rs` unverändert, kein Install-Skript)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Inventory und Playbook eines Ansible-Laufs liegen in einem eigenen Verzeichnis je Lauf; ein Fehler vor dem
Start entfernt es ganz; kein Test lässt etwas im Temp-Verzeichnis. (2) Der Playbook-Name behält nur `[A-Za-z0-9._-]`,
eine Server-Antwort wird höchstens 16 MiB gelesen. (3) clippy `--all-targets` sauber, Kommentare und Doku wie der
Code (R-0817). (4) Die Doku nennt die erste URL eines Workspace, ein Test pinnt den Sync ohne Geräte-Identität.
(5) Ein gescheitertes Löschen des Pins meldet einen Fehler (R-0748), Keyring-Fehler im TOFU-Pfad stehen im Log
(R-0771). (6) Token-Form und Quoting im Provisionierungsbefehl; (7) nur nach Kevins Antwort: der Einzeiler ohne Token.

Für alle Tasks:
- Basis: Der Branch steht auf `feature/desktop-hardening-2@cea7fb9b` (PR #269, beim Planen nicht gemergt;
  `origin/main` war 53a7dbc5). Gebaut wird nach dem Merge von #269, mit `origin/main` im Branch; der builder greppt
  jede `datei:zeile` vor dem Schreiben neu. `HEAD:` der Tasks ist cea7fb9b.
- Reihenfolge: T1 zuerst (vor dem nächsten Release). `ansible.rs`: T1 → T2 → T3. `docs/developer/desktop.html` (DE+EN):
  T1, T3, T4 nacheinander. `commands.rs`: T1, T2, T5. `tofu.rs`: T5 → T6. `ProvisioningTab.*`: T7 → T9. T9 wartet auf
  Kevin und auf den Merge von ops-install-hardening (dort ändern T2/T3 `docs/admin/agent-deployment.html` DE+EN).
- Andere Vorhaben ändern dieselben Dateien; die Reihenfolge der Merges steuert die Session: desktop-blocking (T3 ein
  Signal-Test in `ansible.rs`, nach T1 hier auf das Laufverzeichnis anzupassen; T9 `tofu.rs` mit T5/T6 hier seriell, wer
  später kommt, nimmt die Naht des anderen; T5/T7 `commands.rs`; T8 `http_client.rs`; T6/T7 `connection/rdp.rs`),
  desktop-process-safety (T5 `connection/rdp.rs`; `terminal.rs` fasst dieses Ledger nicht an), desktop-ui-fixes
  (#262, `dictionaries.ts`); `CHANGELOG.md` überall.
- `tofu.rs` und `http_client.rs` stehen auf `scripts/dev/review-risk.txt` (T3, T5, T6); die Session zieht für T1, T2,
  T7, T8 und T9 zusätzlich `security` hinzu (Werte an der Datei-, Prozess- und Shell-Grenze).
- Neue Code-Strings (Fehlertexte, Logzeilen in Rust) englisch; neue UI-Texte über `dictionaries.ts` (DE+EN).
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737. Tests schreiben nur in eigene, per Guard entfernte
  Verzeichnisse.

### T1 — Ansible: Inventory und Playbook in einem eigenen Verzeichnis je Lauf  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/commands.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/ansible.html, docs/en/admin/ansible.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f74d00a8 2026-10-23T08:17:51+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T1.verdict.json)
Änderung: Neu `create_run_dir(base: &Path) -> io::Result<PathBuf>` in `ansible.rs`: `base/adminhelper_ansible_<pid>_<n>_<nanos>` (n aus einem `AtomicU64`, nanos aus `SystemTime`) mit `std::fs::DirBuilder`, unter Unix `DirBuilderExt::mode(0o700)`, `create` (nicht `create_all`, also exklusiv); bei `AlreadyExists` ein neuer Name, höchstens 16 Versuche, sonst der Fehler. `generate_inventory(dir, servers)` schreibt `dir/inventory.ini`, `write_playbook_temp(dir, filename, content)` schreibt `dir/playbook_<safe_name>` (Präfix, damit kein Name mit `inventory.ini` kollidiert); beide weiter über `create_temp_file` (0600, `create_new`), die Zähler `INVENTORY_SEQ`/`PLAYBOOK_SEQ` (`:167`, `:191`) und ihre Kommentare entfallen. `run` (`:81-100`) legt das Laufverzeichnis in `std::env::temp_dir()` an und entfernt bei jedem Fehler danach (Inventory, Playbook — auch halb geschrieben —, `launch`) das ganze Verzeichnis mit `remove_dir_all`; nach einem gelungenen `launch` bleibt es dem Lauf. `is_confined_ansible_path` (`:211-228`): nach `canonicalize` liegt die Datei in einem Verzeichnis P direkt im (kanonischen) Temp-Verzeichnis, P beginnt mit `adminhelper_ansible_`, unter Unix hat P keine Gruppen- und Fremdbits (`mode & 0o077 == 0`); `launch_ansible_with` (`:237-253`) verlangt zusätzlich, dass Inventory und Playbook in demselben P liegen, und entfernt nach einem gescheiterten Start P. `linux_run_script` (`:288-297`): `ah_cleanup` wird `rm -rf -- <P>` (P = Elternverzeichnis des Inventory, `shell_escape`), Trap-Folge unverändert; Doc-Kommentare von `run`, `create_temp_file`, `is_confined_ansible_path`, `linux_run_script` passend. Tests in `ansible.rs`: ein Test-Guard (Drop entfernt das Laufverzeichnis, auch nach einem Panic) für jeden Test, der Dateien schreibt; die Tests an `generate_inventory`/`write_playbook_temp`/`signal_mid_run`/`launch_ansible_with`/`is_confined_ansible_path` (`:520-886`) nehmen ein Laufverzeichnis aus `create_run_dir`. Neu, zuerst rot: (a) nach `run` mit einem notierenden `launch` liegen beide Pfade im selben Verzeichnis P, P ≠ Temp-Verzeichnis, P liegt direkt darin, unter Unix Modus 0700 (auf HEAD rot: P ist das Temp-Verzeichnis); (b) ein Playbook, das sich nicht schreiben lässt (Name aus 300 Zeichen, ENAMETOOLONG) → Fehler, P existiert nicht mehr; (c) `launch` scheitert → P existiert nicht mehr; (d) die Pfadprüfung lehnt ab: Datei direkt im Temp-Verzeichnis, P mit Modus 0755 (Unix), Inventory und Playbook in zwei verschiedenen P; (e) das Linux-Skript entfernt P nach dem Ende von `ansible-playbook` (der Stub-Test `:520` prüft zusätzlich P). `commands.rs`: `remove_ansible_files_with` (`:950-967`) sucht Laufverzeichnisse `adminhelper_ansible_*`, deren Dateien im Namen oder Inhalt den Marker tragen, und entfernt jedes per vollem Pfad mit `remove_dir_all`; die Tests `ansible_run_*` (`:1014-1200`) behalten ihre Prüfungen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:114`, Satz Ansible: Inventory und Playbook liegen je Lauf in einem eigenen Verzeichnis `adminhelper_ansible_<pid>_<n>_<zeit>` im Temp-Verzeichnis, unter Linux und macOS nur für den eigenen Nutzer; Ansible liest Variablen- und Plugin-Verzeichnisse neben Inventory und Playbook, dort liegt nur, was der Lauf schreibt; das Linux-Skript entfernt das Verzeichnis; scheitert ein Schritt vor dem Start, entfernt `ansible_run` das ganze Verzeichnis; der Windows-Satz bleibt; `:247`, Satz zu `launch_ansible`: nur Dateien in einem solchen eigenen Verzeichnis, beide im selben) · docs/admin/ansible.html + docs/en/admin/ansible.html (`:67`, `:70`: ein eigenes temporäres Verzeichnis je Lauf, das der Client nach einem gescheiterten Start und das Linux-Terminal nach dem Lauf entfernt) · CHANGELOG.md (Changed, umlautfrei: Desktop, Ansible: Inventory und Playbook eines Laufs liegen in einem eigenen Verzeichnis im Temp-Verzeichnis, unter Linux und macOS nur fuer den eigenen Nutzer lesbar; scheitert ein Schritt vor dem Start, entfernt der Desktop das ganze Verzeichnis, auch eine halb geschriebene Datei)
Test-Löschung: apps/desktop/src-tauri/src/ansible.rs::write_new_temp_removes_the_file_when_the_write_fails — `write_new_temp` entfällt mit dem Merge 831e2a30 (das Laufverzeichnis geht samt halber Datei bei jedem Fehler, `run_removes_its_directory_when_the_playbook_cannot_be_written` prüft das); apps/desktop/src-tauri/src/ansible.rs::run_removes_the_inventory_when_the_playbook_cannot_be_written — ersetzt durch `run_removes_its_directory_when_the_playbook_cannot_be_written` (das ganze Laufverzeichnis statt nur des Inventory); apps/desktop/src-tauri/src/ansible.rs::per_process_playbooks_of_one_name_get_a_file_each — umbenannt in `two_runs_of_one_playbook_get_a_directory_each` (ein Verzeichnis je Lauf statt einer Datei je Prozess); apps/desktop/src-tauri/src/ansible.rs::confines_ansible_paths_to_own_temp_files — umbenannt in `confines_ansible_paths_to_files_of_a_run_directory` (Prüfung gegen das Laufverzeichnis)
Beweis: Code-Lesung apps/desktop/src-tauri/src/ansible.rs:169-175 und :193-200 (beide Dateien direkt in `std::env::temp_dir()`; nach `create_temp_file` kann `write_all` scheitern, die Datei bleibt) und :81-100 (`run` entfernt nur das Inventory); Test (a) ist auf HEAD rot
HEAD: cea7fb9b

### T2 — Ansible: Playbook-Name nur aus `[A-Za-z0-9._-]`, Server-Antwort höchstens 16 MiB  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/commands.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @a3c3dde7 2026-10-23T08:29:55+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T2.verdict.json)
Änderung: `safe_name` in `write_playbook_temp` (`:182-186`): jedes Zeichen außerhalb von ASCII `[A-Za-z0-9._-]` wird `_`, danach `..` → `_` wie bisher; keine Längenkappung. Doc-Kommentar: der Name geht unter Windows als Argument an Windows Terminal und `cmd`. `fetch_json` (`:63-75`): ist `content_length()` größer als 16 MiB (`const MAX_RESPONSE_BYTES`), Fehler ohne Lesen; sonst den Body mit `response.chunk()` lesen und abbrechen, sobald mehr als 16 MiB da sind; dann `serde_json::from_slice`. Fehlertexte englisch, ohne Body. Tests in `ansible.rs`, zuerst rot: (a) `write_playbook_temp` mit `a;b&c%d^e|f.yml`, `x y.yml`, `ü.yml` → Dateiname `playbook_a_b_c_d_e_f.yml`, `playbook_x_y.yml`, `playbook__.yml` (auf HEAD rot); (b) `fetch_playbook` gegen `serve` (`:323`) mit `200 OK` und Body `{}` bzw. `<html>` → Fehler, keine Datei (Befund tester #269); (c) eine Antwort mit `content-length` über 16 MiB und eine ohne Länge, deren Body 16 MiB + 1 Byte hat (`serve` um einen Antwort-Modus ohne `content-length` erweitern) → Fehler. `commands.rs`: `ansible_run_removes_the_inventory_when_the_playbook_cannot_be_written` (`:1113`) braucht einen neuen Auslöser, weil ein NUL nach (a) zu `_` wird: ein Name aus 300 Zeichen (ENAMETOOLONG); Prüfungen unverändert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible
Doku: CHANGELOG.md (Changed, umlautfrei: Desktop, Ansible: der Dateiname des Playbooks behaelt nur Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich, andere Zeichen werden zu Unterstrichen; die Antwort des Servers auf den Playbook-Abruf liest der Desktop hoechstens 16 MiB weit) · keine weitere (die Doku nennt den Dateinamen nicht)
Abhängt von: T1
Beweis: Code-Lesung apps/desktop/src-tauri/src/ansible.rs:182-186 (nur `/`, `\`, `..` ersetzt), :262-270 und apps/desktop/src-tauri/src/terminal.rs:107-128 (Pfad als Argument an `wt` bzw. `cmd /K`), apps/desktop/src-tauri/src/ansible.rs:74 (`response.json()` ohne Grenze)
HEAD: cea7fb9b

### T3 — Aufräumen: Kindprozess im Signal-Test einsammeln, veraltete Kommentare und Doku (R-0817)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/http_client.rs, apps/desktop/src-tauri/src/connection/rdp.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5bd9a6c1 2026-10-23T09:41:50+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T3.verdict.json)
Änderung: `signal_mid_run` (`ansible.rs:559-609`): nach der Warte-Schleife und dem bedingten `kill -KILL` steht `let _ = child.wait();` unbedingt (std gibt nach einem `try_wait`, der den Status schon hatte, ihn erneut zurück), sodass clippy `zombie_processes` unter `--all-targets` nichts mehr meldet; Verhalten des Tests unverändert. `http_client.rs:48-51`: der Doc-Kommentar von `build_client_without_identity` nennt als Beispiel die Sync-Quelle eines Sync-Workspace (jeder Sync lädt ohne Identität) statt „a sync URL on another origin“. `connection/rdp.rs:778-780`: der Testkommentar sagt, was der Test prüft (Passwort und Zeilenumbruch kommen an, `Ok`), nicht das Nullen. Die Metrik misst der builder vor und nach dem Diff mit `cargo clippy --all-targets -- -D warnings` in `apps/desktop/src-tauri` und schreibt beide Zahlen in den Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:238`, Choke-Point: `build_client` deckt Login, Refresh, `api_proxy`, Tunnel- und Connection-Abruf; der Sync-Abruf baut seinen Client über `build_client_without_identity`, ohne Geräte-Identität, mit derselben TOFU- bzw. CA-Prüfung) · kein CHANGELOG (keine Verhaltensänderung)
Abhängt von: T2
Beweis: cargo clippy --all-targets -- -D warnings (clippy 0.1.99, rustc 1.99.0) beim Bau von desktop-hardening-2 (#269): `zombie_processes` an apps/desktop/src-tauri/src/ansible.rs:567 (Spawn mit `process_group(0)`, `wait()` nur im Zweig `:588-593`); Code-Lesung apps/desktop/src-tauri/src/http_client.rs:51, docs/developer/desktop.html:238 gegen :245, apps/desktop/src-tauri/src/connection/rdp.rs:778-780
Orakel: analyzer — clippy `zombie_processes` unter `--all-targets`
Metrik: cargo clippy --all-targets -- -D warnings (clippy 0.1.99): 1 Fehler → 0
Dedup-Key: ref:desktop:ansible.rs:zombie-tests-stale-docs
HEAD: cea7fb9b

### T4 — Sync: Doku nennt die erste URL eines Workspace, Test für den Abruf ohne Geräte-Identität  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sync.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @c17adac6 2026-10-23T08:40:40+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T4.verdict.json)
Änderung: `sync::sync_connections` (`sync.rs:11-32`) teilt sich in `fetch(url, allow_self_signed) -> Result<Vec<Connection>, AppError>` (Prüfung `validate_https_url`, Client über `build_client_without_identity`, GET, Parsen, `sanitize_synced_connections`) und den Rest (`write_connections`, Rückgabe); Verhalten unverändert. Neuer Test in `sync.rs`, Aufbau wie `sync_identity_choice_is_part_of_the_client_cache_key` (`http_client.rs:123-145`): `keyring_store::memory()`, Workspace `standard`, eine Geräte-Identität, die kein Client laden kann (`enroll|key`, `enroll|cert`, `enroll|ca` = `not a pem`); `fetch` gegen `https://127.0.0.1:<port>/c.json` mit einem Port aus `test_tls::refused_port()` (`src/test_tls.rs:39`) → `AppError::Network(_)` (die Verbindung wurde versucht, der Client entstand ohne Identität). Gegenprobe im Commit-Body: mit `build_client` statt `build_client_without_identity` scheitert der Test (Fehler beim Laden der Identität statt `Network`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sync
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:247`, der Klammersatz zur CSP `connect-src`: der Server-Verkehr läuft über `api_proxy`; dazu nennt er die erste URL eines Workspace ohne gespeicherte URL: beim ersten Speichern bzw. Anmelden übernimmt er einmal eine URL aus der Oberfläche (`storage::meta_with`), danach nur diese, und der Sync lädt nur von ihr) · kein CHANGELOG (keine Verhaltensänderung)
Abhängt von: T3
Beweis: Code-Lesung apps/desktop/src-tauri/src/storage.rs:439-448 (erste URL aus der Oberfläche) gegen docs/developer/desktop.html:247; apps/desktop/src-tauri/src/sync.rs:23 ohne Test seit #269 (Befund tester #269)
HEAD: cea7fb9b

### T5 — Pin-Reset meldet, wenn der Schlüsselbund den Pin nicht löschen kann (R-0748)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tofu.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/session.rs, CHANGELOG.md, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @0202d421 2026-10-23T08:58:50+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T5.verdict.json)
Änderung: `keyring_delete` (`tofu.rs:220-222`) gibt `Result<(), AppError>` zurück. Neu `forget_pin_with(server_url, delete: impl FnOnce(&str) -> Result<(), AppError>) -> Result<(), AppError>`; `forget_pin(server_url) -> Result<(), AppError>` (`:354-363`) ruft es mit `keyring_delete`. Es leert den Cache und den Client-Cache wie bisher, auch wenn `delete` scheitert (dieser Prozess pinnt beim nächsten Kontakt neu), und gibt danach den Fehler zurück (Text englisch, etwa „the pinned certificate could not be removed from the keyring: …“, ohne Fingerprint). Hat desktop-blocking T9 vorher eine Naht für das Löschen eingeführt, nimmt T5 diese statt `forget_pin_with`. Aufrufer: `reset_server_cert_pin_in` (`commands.rs:91-95`) mit `?`; `reset_device_identity_in` (`:139-147`) nach dem Zurücksetzen der Identität mit `?` (Reihenfolge unverändert; der Fehlertext sagt, dass die Identität zurückgesetzt ist und nur der Pin blieb); Test-Helfer `session.rs:1183` und Test `tofu.rs:574` mit `.unwrap()`. Tests in `tofu.rs`, zuerst rot (auf HEAD gibt es keinen Rückgabewert): (a) `forget_pin_with` mit einem `delete`, der `Err(AppError::Keyring(…))` liefert → `Err`, und der Cache-Eintrag unter der normalisierten Identität ist trotzdem weg; (b) mit `Ok` → `Ok`. Gegenprobe im Commit-Body: `let _ = delete(…)` statt Rückgabe macht (a) rot. Der Kommentar „keyring_delete is fail-silent“ (`tofu.rs:566`) entfällt. Die Oberfläche zeigt einen Fehler beider Commands schon (`SettingsModal.svelte:170-178`, `:195-205`, `Login.svelte:103-113`, `:136-143`): keine UI-Änderung.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pin
Doku: CHANGELOG.md (Fixed, umlautfrei: Desktop: Gepinntes Zertifikat zuruecksetzen meldet einen Fehler, wenn der Schluesselbund den Pin nicht loeschen kann, statt den Reset als erfolgreich zu melden (R-0748)) · docs/developer/desktop.html bleibt (`:244` beschreibt den Reset richtig)
Beweis: Code-Lesung apps/desktop/src-tauri/src/tofu.rs:220-222 (`let _ =` verwirft den Fehler von `keyring_store::delete`), :354-363 (`forget_pin` ohne Rückgabe), apps/desktop/src-tauri/src/commands.rs:93 (`Ok(())` danach)
Orakel: mutation-sample — `let _ = delete(…)` statt Rückgabe macht Test (a) rot
Dedup-Key: bug:desktop:tofu.rs:forget_pin-drops-delete-error
HEAD: cea7fb9b

### T6 — TOFU: Keyring-Fehler ins Log (R-0771)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tofu.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @0999327d 2026-10-23T09:03:29+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T6.verdict.json)
Änderung: `keyring_read` (`:210-212`), `keyring_write` (`:216-218`) und `keyring_delete` (nach T5) loggen einen Fehler mit `log::warn!` (wie `password.rs`), mit Operation, Pin-Identität (Host und Port) und Fehlertext, nie dem Fingerprint; die Rückgaben bleiben (`Err(())` für Lesen und Schreiben, damit die Aufrufer fail-closed bleiben). Kein eigener Test: reines Logging, kein Log-Capture im Desktop (Spec, Nicht-Ziele); die TOFU-Tests vor und nach dem Diff grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tofu::
Doku: keine (intern)
Abhängt von: T5
Beweis: Code-Lesung apps/desktop/src-tauri/src/tofu.rs:211 und :217 (`.map_err(|_| ())`, kein Log)
Orakel: metric — Fehlerpfade ohne Log in tofu.rs
Metrik: grep -c 'map_err(|_| ())' apps/desktop/src-tauri/src/tofu.rs (GNU grep): 2 → 0
Dedup-Key: ref:desktop:tofu.rs:keyring-errors-unlogged
HEAD: cea7fb9b

### T7 — Provisionierung: Token beginnt nicht mit `-`  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e87dffee 2026-10-23T09:12:41+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T7.verdict.json)
Änderung: `TOKEN_FORM` (`ProvisioningTab.svelte:20`) wird `/^[A-Za-z0-9_][A-Za-z0-9_-]*$/` (der Server erzeugt `adminhelper_prov_…`, `apps/server/app/modules/provisioning/router.py:70`); Kommentar: kein Wert, den eine Shell oder das Skript als Option liest. Test, zuerst rot: `it.each` der Token ohne Befehl (`ProvisioningTab.test.ts:120`) bekommt `-x` und `--server` dazu.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/ProvisioningTab.test.ts
Doku: keine (der Server erzeugt solche Token nie)
Beweis: Code-Lesung apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:20 (`/^[A-Za-z0-9_-]+$/` lässt ein führendes `-` zu)
HEAD: cea7fb9b

### T8 — `shellQuote`: Backslash so, dass POSIX-Shells und fish denselben Wert lesen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/shell.ts, apps/desktop/ui/src/lib/utils/shell.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0566a9a2 2026-10-23T09:21:27+02:00
Review: approve (.ah-out/review/desktop-hardening-3/T8.verdict.json)
Änderung: `shellQuote` ersetzt im gequoteten Fall zusätzlich jedes `\` durch `'\\'` (Quote schließen, `\\` außerhalb der Quotes, wieder öffnen): POSIX liest `\\` außerhalb von Quotes als `\` (2.2.1), fish ebenso, und innerhalb der fish-Quotes bleibt kein `\`; Werte ohne `\` sehen aus wie bisher. Doc-Kommentar nennt fish und die Quelle. Tests in `shell.test.ts`, zuerst rot: (a) `a\b` → `'a'\\'b'`, `a\'b` und `x\\` gequotet erwartet; (b) ein kleines Modell der fish-Regeln im Test (in einfachen Quotes nur `\\` → `\` und `\'` → `'`, außerhalb `\x` → `x`) liest jedes Wort aus BARE und QUOTED als genau den Wert zurück (auf HEAD rot für Werte mit `\`); (c) die Rundreise über `/bin/sh` (`:45-46`) nimmt die neuen Werte auf.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/utils/shell.test.ts
Doku: CHANGELOG.md (Fixed, umlautfrei: Desktop, Provisionierungs-Tab: ein Backslash in der Server-URL steht im erzeugten Befehl so, dass auch fish ihn woertlich liest) · fish nur am Modell geprüft (Spec, Externe Integrationen)
Beweis: Code-Lesung apps/desktop/ui/src/lib/utils/shell.ts (`value.replace(/'/g, …)`, kein Fall für `\`) gegen die fish-Doku (Escapes `\\` und `\'` in einfachen Quotes)
HEAD: cea7fb9b

### T9 — Provisionierung: Einzeiler ohne Token, das Skript fragt ihn ab  [x]
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @831e2a30 2026-10-29T08:55:53+01:00
Review: approve (.ah-out/review/desktop-hardening-3/T9.verdict.json)
Entscheidung: Kevin 2026-10-23: Variante A, Einzeiler ohne Token, agent-install.sh fragt verdeckt über /dev/tty ab; „Nur provisionieren“ bleibt vorerst mit --token (eigene Roadmap-Zeile).
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Änderung: Variante A der Spec (Trade-off 6). `scriptCommand` (`ProvisioningTab.svelte:94-99`) ohne die Zeile `--token` (`:98`); `scripts/agent-install.sh` fragt den Token ohne `--token` verdeckt über `/dev/tty` ab (`:32-33`, `:306-316`), unverändert. Unter dem Einzeiler zeigt ein neuer Kasten (`data-testid="prov-token"`) den Token mit Kopierknopf (`copyText`, `:117`) und dem Hinweis `infra.prov.tokenPrompt` (neu, DE+EN: das Skript fragt beim Ausführen nach dem Token, Eingabe verdeckt); er verschwindet mit den Befehlen (`scheduleHide`, `:42-49`). Der Befehl „Nur provisionieren“ (`:104-108`) bleibt mit `--token`. Tests, zuerst rot: (a) `script-command` enthält den Token nicht und kein `--token`; (b) `prov-token` zeigt genau den Token, der Knopf kopiert genau ihn; (c) ein Token ohne gültige Form (T7) zeigt auch keinen Token-Kasten; (d) nach dem Ausblenden (Fake-Timer, 60 s) ist der Kasten weg. Die Prüfung `:73` (`toContain('--token tok-123')`) kehrt sich um; `:151` (Nur-provisionieren-Befehl) bleibt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/ProvisioningTab.test.ts src/lib/i18n/i18n.test.ts
Doku: docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html (`:44` der Einzeiler ohne Token, `:46-51` Beispiel ohne `--token`, `:52` der Satz zur Abfrage über `/dev/tty` nennt den Desktop-Einzeiler; in der Fassung nach ops-install-hardening neu greppen) · CHANGELOG.md (Changed, umlautfrei: Desktop, Provisionierungs-Tab: der Einzeiler enthaelt den Token nicht mehr; das Skript fragt ihn beim Ausfuehren verdeckt ab, der Tab zeigt ihn zum Kopieren daneben)
Abhängt von: T7; ops-install-hardening gemergt
Beweis: Code-Lesung apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:94-99 (Token im Einzeiler) gegen scripts/agent-install.sh:32-33 und :306-316 (Abfrage ohne `--token`)
HEAD: cea7fb9b

### T10 — README: Einzeiler ohne Token (Fund der Abschlussprüfung)  [x]
Komponente: scripts · Dateien: README.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f0de06a4 2026-10-29T09:20:25+01:00
Review: approve (.ah-out/review/desktop-hardening-3/T10.verdict.json)
Änderung: `README.md` (Abschnitt „Installing the agent“, `:340-346`) beschreibt den Einzeiler des Provisionierungs-Tabs noch mit `--token <PROVISION-TOKEN>`; seit T9 enthält er keinen Token mehr, `agent-install.sh` fragt ihn verdeckt ab. Beispiel ohne `--token`, ein Satz zur Abfrage und zu `--token` für unbeaufsichtigte Rollouts, wie `agent-deployment.html` (DE+EN). CHANGELOG: der T9-Eintrag nennt README unter Doku und wird umbrochen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Dateien dieser Task
Abhängt von: T9

## Entscheidungen
- 2026-10-29 T9: der Kopierknopf des Token-Kastens meldet `infra.prov.tokenCopied` (neu, DE+EN) statt "Befehl kopiert"; `copyText` nimmt den Meldungsschlüssel als zweiten Parameter. Merge origin/main (831e2a30): `ansible.rs` behält das Laufverzeichnis aus T1, `write_new_temp` und seine zwei Tests aus desktop-blocking T4 entfallen (das Laufverzeichnis samt halber Datei geht bei jedem Fehler, Test `run_removes_its_directory_when_the_playbook_cannot_be_written`); `tofu.rs`: `KeyringPinStore::forget` gibt den Löschfehler zurück, `forget_pin_with` setzt den Lösch-Hook in den Store, R-0748 bleibt unter der Identitätssperre aus desktop-blocking T9.
