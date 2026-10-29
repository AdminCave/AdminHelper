<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: blockierende Keyring- und Sperr-Zugriffe, Frist beim Verbindungsaufbau, Tunnel-Ports, Ansible-Temp-Dateien — Task-Ledger
Status: bereit · Branch: feature/desktop-blocking · Review: pro Task
Spec: docs/features/desktop-blocking.md (Roadmap R-0643, R-0644, R-0642, R-0569, R-0572, R-0574)
Heavy: linux-full + scenario --agents 0 --desktop --enforce + windows — T5 und T8 ändern, wie jede Desktop-Journey Einstellungen, Passwort-Status und Geräte-Identität liest (GUI-E2E im Sammellauf, `run.sh e2e`, u. a. `desktop_e2e_connect.sh`, `desktop_e2e_tunnel.sh`, `desktop_e2e_workspaces.sh`); T8 und T9 ändern Desktop-Enrollment und TOFU (CLAUDE.md §5), die nur die Desktop-Journeys gegen einen entfernten Server unter `MTLS_ENFORCE` über Hosts hinweg zeigen (`multibox.sh --desktop --enforce`, S3; ask-first, Spec offene Frage 1); `windows` ist der CI-Job `rust-windows` (`cargo test`, kein Windows im Pool): T7 ändert den mstsc-Start (`rdp.rs`, `cfg(windows)`), T5 und T8 laufen dort mit allen Tests. Kein `--tunnel`: der FRP-Datenpfad bleibt, `frpc.rs` ändert sich nicht.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: desktop-tofu-store (`feature/desktop-tofu-store`, Plan `25b716ff`). Gebaut wird nach dessen Merge, mit `origin/main` im Branch: dessen T1 baut `tofu.rs` um (`PinDecision::Unavailable`, `PinStore::store` → `Result`, Invariante „ein erster Kontakt gilt erst nach gelungenem `keyring_store::set`, der Cache hält nur gespeicherte Pins“), die T9 hier erhält; dessen T2 lässt `keyring_store::try_get` unter Windows Lesefehler melden, worauf T8 sich stützt. Gemeinsame Dateien: `tofu.rs` (T9), `docs/developer/desktop.html` + EN (hier `:114`, dort `:242`/`:244`), `CHANGELOG.md`. Zeilen zu `tofu.rs` nach dem Merge neu greppen.

Ziel: (1) Commands, die auf Keyring oder Dateisperre warten, laufen auf einem Blocking-Thread, nie auf dem
Main-Thread. (2) Die Geräte-Identität liest der Prozess einmal und hält sie; der TOFU-Verifier hält die Pin-Sperre
nicht über Keyring-IO. (3) Nach der gemeldeten Zeitüberschreitung startet keine Verbindung mehr; die
xfreerdp-Anmeldeprüfung endet mit der Frist. (4) `fetch_tunnels` scheitert nicht an einem Port außerhalb von `u16`.
(5) Der Temp-Test hängt nicht an der PID; die Lösch-Reihenfolge des Ansible-Laufs ist gepinnt, ein gescheitertes
Schreiben lässt keine Ansible-Datei liegen.

Für alle Tasks:
- Zeilenangaben: origin/main@b1432223, Rust-Pfade unter `apps/desktop/src-tauri/src/`; der builder greppt sie vor dem
  Schreiben neu.
- Reihenfolge: wie gelistet. T7 hängt an T6 (Parameter der Frist) und baut nach T5 (beide `commands.rs`); T4 nach T3
  (beide `ansible.rs`); `CHANGELOG.md` ändern T2, T4, T5, T7, T8 nacheinander, je ein eigener Eintrag unter
  `## [Unreleased]` → `### Fixed` (umlautfrei, Gedankenstrich „—“).
- Risikopfade (`scripts/dev/review-risk.txt`): T2 (`tunnel.rs`), T8 (`enrollment.rs`, `http_client.rs`), T9
  (`tofu.rs`) bekommen zusätzlich `security`.
- Tests mit `sh`-Stubs sind `#[cfg(unix)]`; alles andere läuft auch im CI-Job `rust-windows`. Temp-Verzeichnisse der
  Tests wie die vorhandenen (`std::env::temp_dir()` + Fall + `std::process::id()`, am Ende entfernt).
- Neue Code-Strings (Fehler, Log) englisch; die bestehenden deutschen Texte bleiben, auch die Meldung
  „Verbindungsaufbau: Zeitueberschreitung …“ (`commands.rs:297-299`). Test-Adressen nur aus RFC 5737.
- Neue Hilfstypen nicht `pub` (sonst prüft sie `ui/src/lib/bridge/types.parity.test.ts`); kein neuer Tauri-Command.
- Test-Keyring und Workspace gelten je Thread (`keyring_store.rs:92-96`, `workspace.rs:656-663`): was in
  `blocking()`/`spawn_blocking` läuft, sieht sie nicht. Getestet werden die synchronen Teile auf dem Test-Thread.

### T1 — Temp-Test ohne Namen, die eine PID sein können (R-0572)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/storage.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @73a538b4 2026-10-29T06:10:48+01:00
Review: approve (.ah-out/review/desktop-blocking/T1.verdict.json)
Änderung: In `write_json_atomic_removes_only_the_stale_temps_of_the_same_file` (`storage.rs:1560-1596`) tragen die Fixtures statt `4242`, `4243`, `4244` Ziffernfolgen über `u32::MAX`, also nie eine PID, aber für `remove_stale_temps` (`:142-173`, nur ASCII-Ziffern) weiter Temps: `prefs.json.4294967296.tmp` (alt), `prefs.json.4294967297.tmp` (jung), `prefs.json.4294967298.tmp` (Zukunft), `other.json.4294967296.tmp`, `prefs.json.x4294967296.tmp`; die erwartete Namensliste (`:1585-1595`) zieht mit, ihre Reihenfolge bleibt sortiert. Ein Kommentar sagt das Warum: eine Fixture mit der PID des Testprozesses wäre die eigene Temp-Datei des Schreibens (`:120-125`). Kein Produktcode.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- write_json_atomic
Doku: keine (nur Test)
Beweis: origin/main@b1432223 · Code-Lesung: `write_json_atomic` schreibt `<pfad>.<std::process::id()>.tmp` mit `truncate` (`storage.rs:120-122`, `:177-185`) und benennt sie in `prefs.json` um (`:125`); mit PID 4243 oder 4244 ist die Fixture `:1573` bzw. `:1575` die eigene Temp-Datei, danach weg, und `:1590`/`:1591` sind rot. Die PID lässt sich im Test nicht wählen.
Orakel: property — kein Fixture-Name ist als `u32` lesbar, also nie die PID des Testprozesses
Dedup-Key: bug:desktop:src-tauri:write_json_atomic-test-fixed-pid
HEAD: b1432223

### T2 — `fetch_tunnels` nimmt Ports außerhalb von 1–65535 (R-0569)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @55d2b0ab 2026-10-29T06:16:02+01:00
Review: approve (.ah-out/review/desktop-blocking/T2.verdict.json)
Änderung: `TunnelMapping.local_port` wird `i64`, `visitor_port` `Option<i64>` (`tunnel.rs:23-24`); Feldnamen und JSON bleiben (`ui/src/lib/bridge/types.ts:109-120`: `number`). In `resolve_connection` (`:83`) löst ein Visitor-Port nur über `u16::try_from(vport).ok()` zu `visitor_at` auf, nie über `as` (das bildete 78925 auf 13389 ab). Andere Rust-Leser der Felder gibt es nicht (Testfixtures `tunnel.rs:374-375`, `session.rs:847-848`, `connection/mod.rs:240-241` bleiben als Literale). Tests in `tunnel.rs`: (a) `fetch_tunnels` über den vorhandenen Fake-Server `serve` (`:955`): 200 mit drei Zuordnungen — `tunnel("c1", "stcp", "rdp")`, eine mit `"localPort": 70000, "visitorPort": 70000`, eine mit `"localPort": -1, "visitorPort": 0` — liefert `Ok` mit allen dreien, Ports wie gesendet, und die Session hält alle drei (`held`, `:1010-1012`). Zuerst rot auf HEAD (serde: „invalid value: integer `70000`, expected u16“). (b) `resolve_connection` mit einer STCP-Zuordnung der Verbindung, deren `visitor_port` `Some(78925)` (13389 + 65536) bzw. `Some(-1)` ist, und dem Visitor aus `same_ports()` (Server-Port 13389): Ziel unverändert (Host `server.internal`, Port 3389), `via_tunnel` wie in `stcp_without_visitor_port_keeps_original_target` (`:466-474`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tunnel::
Doku: CHANGELOG.md (Fixed: Desktop: eine Tunnel-Zuordnung mit einem Port ausserhalb von 1–65535 laesst die Tunnel-Liste nicht mehr scheitern (R-0569) — bisher fehlten dann alle Zuordnungen, und keine Verbindung wurde ueber einen Tunnel aufgeloest; eine solche Zuordnung loest keinen Visitor auf)
Beweis: origin/main@b1432223 · Code-Lesung: `TunnelMapping` mit `u16` (`tunnel.rs:23-24`), `response.json::<Vec<TunnelMapping>>()` für die ganze Liste (`:60`); der Server liefert `localPort: int`, `visitorPort: Optional[int]` (`apps/server/app/modules/frp/schemas.py:320`, `:323`), `local_port` ist beim Anlegen nur `IntColumn` (`:245`), `visitor_port` erst seit R-0533 begrenzt (`:248`, ältere Zeilen: `config_generator.py:112-125`). Test (a) auf HEAD: `fetch_tunnels` → `Err`.
Orakel: contract — der Desktop nimmt jede Zeile, die `GET /api/frp/tunnels` liefern darf
Dedup-Key: bug:desktop:src-tauri/tunnel.rs:TunnelMapping-port-range
HEAD: b1432223

### T3 — Test: die Ansible-Dateien bleiben, bis `ansible-playbook` nach HUP/TERM endet (R-0574)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @2c1b50b6 2026-10-29T06:20:36+01:00
Review: approve (.ah-out/review/desktop-blocking/T3.verdict.json)
Änderung: Ein neuer Test (`#[cfg(unix)]`) über `signal_mid_run` (`ansible.rs:320-371`), je für `-HUP` und `-TERM` (eigene Fallnamen, etwa `hangup-keeps`, `term-keeps`): der Stub bekommt als `before` `trap 'sleep 0.3; if [ -f "$2" ] && [ -f "$3" ]; then echo AH_KEPT_BOTH; fi; exit 0' HUP TERM` und als `then` `while :; do sleep 0.1; done` (kein `exec`: der Trap des Stubs muss bleiben). Erwartet: `started`, `ended`, `left == (false, false)` und `stdout` enthält `AH_KEPT_BOTH` (der Stub sieht 0,3 s nach dem Signal noch beide Dateien). Ein Kommentar nennt das Warum: ohne `trap exit HUP TERM` (`:206`) führt bash den EXIT-Trap sofort aus, und der bestehende HUP-Test (`:373-380`) bliebe trotzdem grün. Produktcode bleibt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible::
Doku: keine (nur Test; das Soll steht in `docs/admin/ansible.html:67` und `docs/developer/desktop.html:114`)
Beweis: origin/main@b1432223 · Probe (bash 5.2.37, Python 3, dreimal identisch): das Skript von `linux_run_script` (`ansible.rs:201-211`) mit einem Stub wie oben, Prozessgruppe per Signal: mit `trap exit HUP TERM` meldet der Stub bei HUP und TERM `KEPT`, ohne ihn `GONE`; beide Male sind die Dateien danach weg (`left_after=(False, False)`).
Orakel: mutation-sample — Mutation „`trap exit HUP TERM; ` gestrichen“: der neue Test rot (Probe), der bestehende HUP-Test grün
Dedup-Key: bug:desktop:ansible-temp-cleanup-order-test
HEAD: b1432223
Semantik: `docs/developer/desktop.html:114` — „endet die Shell vorher, weil das Terminal geschlossen wird (SIGHUP, ebenso SIGTERM), löscht sie ein EXIT-Trap, sobald <code>ansible-playbook</code> beendet ist“

### T4 — Ein gescheitertes Schreiben lässt keine Ansible-Datei des Laufs liegen (R-0574)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, CHANGELOG.md, docs/features/desktop-blocking.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @375b635a 2026-10-29T06:29:57+01:00
Review: approve (.ah-out/review/desktop-blocking/T4.verdict.json)
Änderung: Verkleinert (siehe ## Entscheidungen, 2026-10-29): `ansible::run` (main, fa7d2c4f) löscht das Inventory schon, wenn das Playbook-Schreiben scheitert. Neu: `write_new_temp(path, content, write)` legt die Datei an (`create_temp_file`) und schreibt mit einem injizierbaren Schritt; scheitert er, schließt es die Datei und löscht sie, denn ihr Pfad erreicht den Aufrufer nie. `generate_inventory` und `write_playbook_temp` schreiben darüber. Tests in `ansible.rs`: (a) `write_new_temp` mit einem scheiternden Schreibschritt → `Err` mit dessen Fehler, die Datei fehlt; zuerst rot ohne das Löschen. (b) `run` mit einem Playbook, dessen Datei nicht angelegt werden kann (Name über 255 Zeichen) → `Err`, kein Start, kein Inventory des Tests im Temp-Verzeichnis (Gegenprobe: ohne die Aufräumung in `run` rot).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible::
Doku: CHANGELOG.md (Fixed, umlautfrei, R-0574); keine HTML-Änderung: `docs/admin/ansible.html:67` (DE+EN) sagt schon, dass der Client bei einem gescheiterten Schritt vor dem Start die geschriebenen Dateien löscht
Abhängt von: T3
Beweis: origin/main@b1432223 · Code-Lesung: `runPlaybook` ruft `ansibleGenerateInventory`, dann `ansibleWritePlaybook`, dann `ansibleLaunch` (`ui/src/lib/stores/ansible.ts:145-147`); nur ein gescheiterter Start räumt auf (`ansible.rs:160-164`); scheitert der zweite Schritt, bleibt die Datei aus dem ersten (`:88-89`, `adminhelper_ansible_inventory_<pid>_<n>.ini`).
Orakel: property — nach jedem gescheiterten Schritt vor dem Start liegt keine Datei dieses Laufs mehr im Temp-Verzeichnis
Dedup-Key: bug:desktop:ansible-temp-cleanup-order-test
HEAD: b1432223
Semantik: `docs/admin/ansible.html:67` — „Scheitert der Start (kein <code>ansible-playbook</code>, kein Terminal), löscht der Client beide sofort.“ Das Schreiben davor beschreibt die Doku nicht; Maßstab ist dieselbe Regel: was ein Lauf, der nicht startet, angelegt hat, geht.

### T5 — Keyring- und Sperr-Commands auf einem Blocking-Thread (R-0643)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @08f8ac26 2026-10-29T06:36:24+01:00
Review: approve (.ah-out/review/desktop-blocking/T5.verdict.json)
Änderung: Neun Commands werden `pub async fn` und führen ihre Arbeit über `blocking(move || …)` (`commands.rs:541-553`) aus: `reset_server_cert_pin` (`:85-88`, `reset_server_cert_pin_in` bleibt synchron), `pinned_ca_fingerprint` (`:100-103`), `device_identity` (`:108-111`), `is_device_enrolled` (`:115-118`), `load_settings` (`:252-256`), `save_settings` (`:258-261`), `password_state` (`:397-400`), `save_password` (`:402-409`), `delete_password` (`:411-414`). `AppHandle` und Argumente wandern in die Closure (`storage::app_data_dir(&app)` dort oder davor). Name, Argumente und Erfolgsantwort bleiben; `pinned_ca_fingerprint` und `is_device_enrolled` geben `Result<…, AppError>` zurück (Spec, Datenmodell). Nicht `#[tauri::command(async)]` (Spec, Trade-off 1). Neuer Test in `commands.rs`, `commands_that_wait_run_on_a_blocking_thread`: liest `include_str!("commands.rs")` und prüft für jeden der neun, dass `#[tauri::command]\npub async fn <name>(` vorkommt und der Körper bis zum nächsten `\n}\n` `blocking(` enthält; ein Kommentar sagt das Warum (synchron = Main-Thread, das Fenster steht, solange Keyring oder Sperre warten). Zuerst rot auf HEAD (alle neun synchron).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- commands::
Doku: CHANGELOG.md (Fixed: Desktop: das Fenster friert nicht mehr ein, solange der System-Schluesselbund oder die Sperre der Einstellungen antwortet (R-0643) — Einstellungen laden und speichern, Passwort-Status, Passwort speichern und loeschen, Geraete-Identitaet, CA-Fingerprint und das Zuruecksetzen des Zertifikat-Pins laufen nicht mehr auf dem Haupt-Thread)
Beweis: origin/main@b1432223 · Code-Lesung: die neun sind `#[tauri::command] pub fn` (`commands.rs:85`, `:100`, `:108`, `:115`, `:252`, `:258`, `:397`, `:402`, `:411`) und erreichen Keyring (`enrollment.rs:175-177`, `tofu.rs:204-206`, `password.rs:1430`, `:1466`, `:1484`, `storage.rs:299`) oder `prefs.lock` (`storage.rs:277`, `:308`); Tauri v2: „Commands without the async keyword are executed on the main thread“ (v2.tauri.app/develop/calling-rust); keyring 3.6.3 verbindet sich je Zugriff neu und entsperrt mit Abfrage (`src/secret_service.rs:337`, `:361-363`).
Orakel: contract — jeder der neun ist ein async Command, dessen Arbeit über `blocking()` läuft
Dedup-Key: bug:desktop:commands.rs:sync-keyring-commands-main-thread
HEAD: b1432223

### T6 — `check_rdp_auth` mit eigener Frist (R-0642)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/rdp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @2d60227c 2026-10-29T06:44:01+01:00
Review: approve (.ah-out/review/desktop-blocking/T6.verdict.json)
Änderung: `check_rdp_auth` (`rdp.rs:570-629`) bekommt `timeout: Duration`. Statt `wait_with_output` (`:606`) liest es stdout und stderr auf je einem Thread und fragt `try_wait` (etwa alle 50 ms) bis zur Frist; ist sie um, `kill` und `wait` (kein Zombie), ohne auf die Lese-Threads zu warten, und `Err(AppError::Connection(<englischer Text: die Anmeldeprüfung lief in die Frist>))`. Ein normales Ende geht wie bisher weiter (`auth_only_unsupported`, Erfolg, `parse_freerdp_error`). `open_rdp` (`:120-128`) übergibt bis T7 eine eigene Konstante von 30 s (die äußere Frist, `commands.rs:287`). Tests (`#[cfg(unix)]`) mit einem Stub-Skript als `rdp_binary` in einem eigenen Temp-Verzeichnis: (a) Skript schreibt `$$` in eine Datei und macht `exec sleep 30`; `check_rdp_auth(stub, "192.0.2.10", 3389, "u", "", false, "pw", 300 ms)` gibt in unter 5 s `Err` zurück, danach scheitert `kill -0 <pid>` (beendet und abgeholt). Zuerst rot: mit dem Parameter, aber noch `wait_with_output` (Lauf über 5 s). (b) Skript `exit 0` → `Ok` innerhalb der Frist.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- connection::rdp::
Doku: keine (sichtbar erst mit T7; CHANGELOG dort)
Beweis: origin/main@b1432223 · Code-Lesung: `check_rdp_auth` startet `xfreerdp +auth-only` und wartet mit `child.wait_with_output()` ohne Frist (`rdp.rs:595-606`); der Aufruf in `open_rdp` (`:120-128`) läuft in `run_with_deadline`, dessen Timeout ihn nicht beendet (tokio 1.51.0 `src/task/blocking.rs:106-110`).
Orakel: property — die Anmeldeprüfung endet spätestens mit ihrer Frist, und kein xfreerdp bleibt zurück
Dedup-Key: bug:desktop:commands.rs:run_with_deadline-work-continues
HEAD: b1432223

### T7 — Nach der Zeitüberschreitung startet keine Verbindung mehr (R-0642)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/src-tauri/src/connection/rdp.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f66881b3 2026-10-29T06:57:23+01:00
Review: approve (.ah-out/review/desktop-blocking/T7.verdict.json)
Änderung: (1) Neu in `connection/mod.rs`: `pub struct Deadline` mit Zeitpunkt und drei Zuständen (offen, gestartet, abgelaufen; atomar). `start(&self) -> Result<(), AppError>`: offen und vor dem Zeitpunkt → gestartet, `Ok`; abgelaufen oder Zeitpunkt vorbei → abgelaufen, `Err` mit dem Text der Zeitüberschreitung (eine Konstante mit `run_with_deadline`, Text wie heute `commands.rs:297-299`); schon gestartet → `Ok`. `expire(&self) -> bool` (crate-intern): offen → abgelaufen, `true`; gestartet → `false`. `remaining(&self) -> Duration` (sättigend). (2) `run_with_deadline` (`commands.rs:289-301`): die Arbeit bekommt `&Deadline` (`FnOnce(&Deadline) -> Result<…>`); beim Timeout gibt es nur dann den Fehler zurück, wenn `expire()` `true` ist, sonst wartet es auf die gestartete Arbeit und gibt deren Ergebnis zurück. (3) Die Arbeit beansprucht den Start unmittelbar vor dem ersten Seiteneffekt: `connection::open_connection` (`mod.rs:15-45`) bekommt `deadline: &Deadline`, die Zweige SSH und Web rufen `deadline.start()?` vor `open_ssh`/`open_web`, RDP reicht sie an `open_rdp` weiter; `open_connection_stored` (`:58-92`) und `open_rdp_with_stored_password` (`:173-207`) reichen sie durch. `open_rdp` (`rdp.rs:65-146`): unter Unix `check_rdp_auth(…, deadline.remaining())` (die Konstante aus T6 geht), dann `deadline.start()?` vor `spawn_rdp_with_password` (`:131`) und `spawn_rdp_interactive` (`:134`); unter Windows ist `deadline.start()?` die erste Zeile der Start-Closure an `start_mstsc` (`:179-182`), so entfernt `run_termsrv_plan` (`password.rs:529-569`) Eintrag und Hold eines Starts, der nicht lief. `resolve_connection` (`commands.rs:511-529`) übergeht die Frist (kein Seiteneffekt). Tests: in `connection/mod.rs` `deadline_*` — `start` vor dem Zeitpunkt `Ok`, danach `expire()` `false`; `expire()` zuerst, dann `start` `Err` mit dem Text der Zeitüberschreitung; `start` nach dem Zeitpunkt ohne `expire()` `Err`; `remaining` endet bei null. In `commands.rs`: (a) `run_with_deadline_starts_nothing_after_the_timeout`: die Arbeit schläft über die Frist, ruft dann `start()` und setzt ein Flag nur bei `Ok`; `run_with_deadline` gibt den Timeout-Fehler, und nach dem Ende der Arbeit (Kanal) ist das Flag nicht gesetzt. (b) `run_with_deadline_reports_a_start_that_began_in_time`: die Arbeit ruft `start()` vor der Frist, läuft über sie hinaus und gibt `Ok` → `run_with_deadline` gibt `Ok`; zuerst rot mit der neuen Signatur und dem alten Timeout-Zweig. Die drei bestehenden `run_with_deadline_*`-Tests (`commands.rs:674-700`) nehmen die Closure mit `|_|`; ihre Assertions bleiben.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- deadline
Doku: CHANGELOG.md (Fixed: Desktop: nach der Meldung „Zeitueberschreitung“ beim Verbindungsaufbau oeffnet sich kein RDP-, SSH- oder Web-Fenster mehr (R-0642) — bisher lief der Aufbau weiter und startete spaeter doch; die Anmeldepruefung von xfreerdp endet mit der Frist von 30 s)
Abhängt von: T6
Beweis: origin/main@b1432223 · Code-Lesung: `tokio::time::timeout(timeout, handle)` (`commands.rs:294`) lässt beim Timeout nur den `JoinHandle` fallen; eine `spawn_blocking`-Task läuft weiter (tokio 1.51.0 `src/task/blocking.rs:106-110`); `open_rdp` startet danach `spawn_rdp_with_password` (`rdp.rs:131`); `run_with_deadline_maps_a_hung_task_to_a_timeout_error` (`commands.rs:682-691`) prüft nur die Meldung.
Orakel: property — nach der Zeitüberschreitungsmeldung kein Seiteneffekt; nach einem rechtzeitigen Start dessen Ergebnis statt der Meldung
Dedup-Key: bug:desktop:commands.rs:run_with_deadline-work-continues
HEAD: b1432223

### T8 — Die Geräte-Identität liest der Prozess einmal (R-0644)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/http_client.rs, CHANGELOG.md, apps/desktop/src-tauri/src/keyring_store.rs, apps/desktop/src-tauri/src/frpc.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @2e8bbdeb 2026-10-29T07:14:57+01:00
Review: approve (.ah-out/review/desktop-blocking/T8.verdict.json)
Änderung: (1) `enrollment.rs` hält Schlüssel, Zertifikat und CA-Kette des Workspace nach dem ersten Lesen im Speicher: `load_identity` (`:232-234`), `is_enrolled` (`:238-240`), `pinned_ca_fingerprint` (`:262-264`), `leaf_fingerprint` (`:276-278`) und `device_identity` (`:325-330`) lesen die gehaltenen Einträge; `enroll|replaces` (`read`, `:175-177`, für `pending_replaces` `:356-358`) und `holds_identity` (`:247-254`, fremdes Präfix) bleiben direkt. (2) Laden: die drei Einträge über `keyring_store::try_get` (`keyring_store.rs:60-69`; unter Windows meldet es Lesefehler erst mit desktop-tofu-store T2), ohne eine Sperre über den Zugriff zu halten. Ein Lesefehler wird nicht gehalten (der nächste Aufruf liest neu), gilt für diesen Aufruf wie heute als „nicht registriert“ und steht einmal je Prozess als Warnung im Log (englisch). (3) Neuladen: ein Helfer, der die gehaltenen Einträge verwirft und `http_client::invalidate_client_cache()` ruft, ersetzt die vier Aufrufe in `store_identity` (`:199`), `clear_identity` (`:457`), `purge_identity` (`:469`) und `enroll_with_token` (`:516`); ein Generationszähler sorgt dafür, dass ein Lesezugriff, den ein solches Verwerfen überlappt, sein Ergebnis nicht behält. (4) Gültigkeit: in Produktion je Prozess, in Test-Builds je Thread und Keyring-Präfix (Spec, Trade-off 3). (5) `http_client.rs`: nur die Kommentare, die Keyring-Lesezugriffe je Client-Bau zählen (`:15-19`, `:69-71`); `client_for` (`:59-101`) bleibt. Tests in `enrollment.rs`: (a) nach `is_enrolled() == true` werden die drei Einträge am `enrollment` vorbei gelöscht (`keyring_store::delete`); `is_enrolled()`, `load_identity()` und `device_identity()` bleiben unverändert — kein Keyring-Zugriff je Aufruf; zuerst rot auf HEAD. (b) danach `clear_identity()` → nicht registriert; `store_identity` mit neuem Zertifikat → `load_identity` liefert das neue; `purge_identity()` → keine Identität. (c) ein Lesefehler (injizierter Leser mit `Err`, Naht wie bei `replace_identity`, `:214-226`) → nicht registriert und nichts gehalten: der nächste Aufruf mit funktionierendem Leser liest erneut (Zähler 2). (d) ein Leser, der während des Lesens den Neulade-Helfer ruft → sein Ergebnis wird nicht gehalten, der nächste Aufruf liest erneut. Bestehende Tests, die Identitäts-Einträge am `enrollment` vorbei schreiben, nachdem sie gelesen haben (Kandidaten: `commands.rs`-Tests ab `:1225`, `http_client.rs:122-145`, `enrollment.rs`-Tests ab `:1775`), rufen danach den Helfer (eine Zeile, Kommentar warum); keine Assertion entfällt. Nicht Teil: `frpc.rs` (`export_identity`, `:325-333`, liest nach (1) aus dem Speicher) und die Keyring-Zugriffe beim ersten Lesen, Registrieren, Erneuern und Zurücksetzen (Spec, Nicht-Ziele).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md (Fixed: Desktop: Anfragen an den Server lesen die Geraete-Identitaet nicht mehr bei jedem Aufruf aus dem System-Schluesselbund (R-0644) — der Prozess liest sie einmal und nach Registrieren, Erneuern und Zuruecksetzen neu; ein kurzer Lesefehler des Schluesselbunds schickt nicht mehr dauerhaft Anfragen ohne Geraete-Zertifikat)
Beweis: origin/main@b1432223 · Code-Lesung: `client_for` ruft `enrollment::is_enrolled()` vor dem Blick in den Client-Cache (`http_client.rs:72`, Cache `:74-77`); `is_enrolled` liest zwei Einträge (`enrollment.rs:238-240`) über `keyring_store::get`, das Fehler zu `None` macht (`keyring_store.rs:48-57`, `:150-153`), je Zugriff eine neue Secret-Service-Verbindung (keyring 3.6.3 `src/secret_service.rs:337`).
Orakel: property — nach dem ersten Lesen erreicht kein Leser der Identität den Keyring, bis sie sich ändert
Dedup-Key: bug:desktop:http_client.rs:keyring-read-per-request
HEAD: b1432223

### T9 — TOFU: kein Keyring-Zugriff unter der globalen Pin-Sperre (R-0644)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tofu.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @97c59368 2026-10-29T07:26:17+01:00
Review: approve (.ah-out/review/desktop-blocking/T9.verdict.json)
Änderung: Stand nach desktop-tofu-store (Zeilen dort neu greppen; hier `origin/main@b1432223`). `KeyringPinStore::load_or_store` (`tofu.rs:158-186`) hält die globale Sperre (`cache()`, `:124-128`) nur noch, um in den Cache zu sehen, ihn zu ändern oder die Sperre einer Pin-Identität zu holen, nie über `keyring_read`/`keyring_write` (`:196-202`). Cache-Treffer → Entscheidung sofort wie heute. Kein Treffer: die Sperre dieser Identität nehmen (eine je Identität, angelegt unter der globalen Sperre), erneut in den Cache sehen (ein paralleler Erstkontakt kann inzwischen gespeichert haben, dann gegen ihn entscheiden), sonst den Keyring lesen: Lesefehler → `Unavailable`, nichts im Cache, kein Schreiben; gespeicherter Pin → in den Cache, entscheiden; kein Pin → `keyring_write` mit dem präsentierten Fingerprint, erst bei `Ok` in den Cache und `Capture`, sonst `Unavailable` (Invariante von desktop-tofu-store, kein Schreiben nach dem Annehmen, kein fire-and-forget). `forget_pin` (`:330-339`) nimmt dieselbe Sperre der Identität, dann entfernt es den Cache-Eintrag und den Keyring-Eintrag: ein laufender Erstkontakt derselben Identität ist danach entweder ganz vorbei und vergessen oder beginnt erst danach. `KeyringPinStore::store` verfährt ebenso (Sperre der Identität, erst speichern, dann Cache). Naht: `KeyringPinStore` bekommt Cache und Keyring-Lesen/-Schreiben/-Löschen als Felder (Produktion: der globale Cache, `keyring_read`, `keyring_write`, `keyring_delete`; gebaut in `pinning_client`, `:319-326`, und `forget_pin`), damit ein Test einen hängenden Keyring nachstellt. Tests in `tofu.rs` (je Test eigene Identitäten unter `.example`; Zeitgrenzen großzügig: Antwort in unter 5 s, der hängende Zugriff wird erst danach über einen Kanal freigegeben): (a) während das Keyring-Lesen für Identität X hängt, liefert `load_or_store` für Y mit Pin im Cache aus einem anderen Thread `Trust`; zuerst rot mit der Naht, aber der alten Sperrfolge. (b) während das Speichern eines Erstkontakts von X (FP_A) hängt, entscheidet ein zweiter Erstkontakt von X (FP_B) nicht vorher; nach der Freigabe: der erste `Capture`, der zweite `Reject`, im Cache FP_A, `keyring_write` genau einmal. (c) Leser `Err` → `Unavailable`, Cache ohne X, kein Schreiben. (d) Schreiber `Err` beim Erstkontakt → `Unavailable`, Cache ohne X; ein zweiter Versuch liest und schreibt erneut. (e) während das Speichern eines Erstkontakts von X hängt, kehrt `forget_pin` für X erst nach dem Speichern zurück, und danach hält weder der Cache noch der (Test-)Keyring einen Pin für X. (f) während das Speichern eines Erstkontakts von X hängt, entscheidet `load_or_store` für Y mit Pin im Cache (`Trust`). Die Tests von desktop-tofu-store, `forget_pin_clears_the_cache_under_the_normalized_identity` (`:425-448`) und `mod tls_handshake` bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tofu::
Doku: keine (keine sichtbare Änderung; `docs/developer/desktop.html:242` in der Fassung von desktop-tofu-store bleibt richtig)
Abhängt von: T5 (nach ihm wartet `reset_server_cert_pin` mit `forget_pin` auf einem Blocking-Thread, nicht auf dem Main-Thread); desktop-tofu-store gemergt (Kopf)
Beweis: origin/main@b1432223 · Code-Lesung: `load_or_store` nimmt die globale Sperre (`tofu.rs:164`) und hält sie über `keyring_read` (`:167`) und `keyring_write` (`:182`); dieselbe Sperre brauchen jeder andere TOFU-Handshake (`verify_server_cert`, `:248`) und `forget_pin` (`:332-335`). desktop-tofu-store T1 behält diese Sperrfolge (Schreiben vor dem Cache unter derselben Sperre, Ledger `tasks/desktop-tofu-store.md` T1).
Orakel: property — unter der globalen Pin-Sperre kein Keyring-Zugriff; je Identität bleibt Lesen→Entscheiden→Speichern atomar, und ein erster Kontakt gilt erst nach gelungenem Speichern
Dedup-Key: bug:desktop:http_client.rs:keyring-read-per-request
HEAD: b1432223

### T10 — Quelltext-Test der Blocking-Commands auch mit CRLF-Checkout (rust-windows rot)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @0ad39e8d 2026-10-29T08:14:18+01:00
Review: approve (.ah-out/review/desktop-blocking/T10.verdict.json)
Änderung: `commands_that_wait_run_on_a_blocking_thread` (T5) liest `commands.rs` per `include_str!` und sucht `#[tauri::command]\npub async fn …` und `\n}\n`; der Windows-Runner checkt mit CRLF aus, der Test fiel dort für jeden Command (`reset_server_cert_pin is not an async command`, PR #295, Job rust-windows). Der Test normalisiert `\r\n` zu `\n`, bevor er sucht.
Beweis: PR #295 Desktop-Backend (cargo test, Windows), run 40833303189: 605 passed, 1 failed, commands.rs:1849
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- commands::tests::commands_that_wait_run_on_a_blocking_thread
Doku: keine (nur ein Test)

## Entscheidungen
- 2026-10-29 T4: seit dem Plan hat `main` `ansible::run` (fa7d2c4f), das bei einem gescheiterten Playbook-Schreiben das Inventory löscht, und `docs/admin/ansible.html:67` beschreibt das; die Merkliste, die Naht `write_playbook_with` und die HTML-Doku entfallen. Gebaut: `write_new_temp` (eine halb geschriebene Datei geht) und ein Test, der die Aufräumung in `run` belegt.
