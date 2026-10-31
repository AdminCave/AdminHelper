<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: blockierende Keyring- und Sperr-Zugriffe, Frist beim Verbindungsaufbau, Tunnel-Ports, Ansible-Temp-Dateien

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand; Rust-Pfade relativ zu
`apps/desktop/src-tauri/src/`. Ledger: `tasks/desktop-blocking.md`. Roadmap R-0643 und R-0644 (Paket
„desktop-keyring-blocking“), R-0642, R-0569, R-0572, R-0574.

**Hängt ab von: desktop-tofu-store** (`feature/desktop-tofu-store`, Plan `25b716ff`), gebaut wird nach dessen Merge.
Dessen T1 ändert `tofu.rs` (`PinDecision::Unavailable`, `PinStore::store` gibt `Result` zurück) und legt die
Invariante fest, die T9 hier erhält: ein erster TOFU-Kontakt gilt erst, wenn `keyring_store::set` für den Pin `Ok`
geliefert hat, und der Prozess-Cache hält nur gespeicherte Pins. Dessen T2 lässt `keyring_store::try_get` unter
Windows einen Lesefehler melden statt „kein Eintrag“; T8 hier liest die Identität über `try_get` und profitiert davon.
Gemeinsame Dateien: `tofu.rs` (T9), `docs/developer/desktop.html` + EN (hier `:114`, dort `:242`, `:244`),
`CHANGELOG.md`. Die Zeilen zu `tofu.rs` unten gelten für `origin/main@b1432223` und werden nach dem Merge neu gegreppt.

## Problem / Motivation

1. **Synchrone Commands mit Keyring- oder Dateisperr-Zugriff laufen auf dem Main-Thread (R-0643).** Tauri v2:
   „Commands without the async keyword are executed on the main thread unless defined with
   `#[tauri::command(async)]`.“ Synchron sind `reset_server_cert_pin` (`commands.rs:85-88`, löscht den TOFU-Pin im
   Keyring), `pinned_ca_fingerprint` (`:100-103`), `device_identity` (`:108-111`), `is_device_enrolled` (`:115-118`,
   alle drei lesen die Identität aus dem Keyring, `enrollment.rs:175-177`), `load_settings` (`:252-256`, wartet auf
   die geteilte Sperre von `prefs.lock`, `storage.rs:277`), `save_settings` (`:258-261`, `holds_identity` liest den
   Keyring, `storage.rs:299`, dazu die exklusive Sperre, `:308`), `password_state`, `save_password`,
   `delete_password` (`:397-414`, Keyring über `password.rs:1430`, `:1466`, `:1484`). Das `keyring`-Crate (3.6.3,
   Secret Service) baut je Zugriff eine neue D-Bus-Verbindung (`SecretService::connect`,
   `keyring-3.6.3/src/secret_service.rs:337`) und entsperrt gesperrte Einträge mit `item.unlock()` (`:361-363`), was
   eine Abfrage des Systems auslösen kann. Solange das dauert, steht das Fenster. Für die Workspace-Commands gibt es
   den Weg schon: `blocking()` (`commands.rs:541-553`) über `tauri::async_runtime::spawn_blocking`.

2. **Die Geräte-Identität wird bei jedem authentifizierten Request aus dem Keyring gelesen (R-0644).** `client_for`
   (`http_client.rs:59-101`) ruft vor dem Blick in den Client-Cache `enrollment::is_enrolled()` (`:72`), das sind zwei
   Keyring-Lesezugriffe (`enrollment.rs:238-240`), auf einem tokio-Worker. `keyring_store::get` macht aus einem
   Lesefehler `None` (`keyring_store.rs:48-57`, `:150-153`): ein Fehler macht `mtls` still `false`, der Request geht
   ohne Zertifikat, und unter erzwungenem mTLS sieht der Nutzer `ERR_MTLS_CERT_REQUIRED`. Der TOFU-Verifier liest und
   schreibt den Keyring im TLS-Handshake unter der globalen Pin-Sperre (`tofu.rs:158-186`, `guard` ab `:164`,
   `keyring_read` `:167`, `keyring_write` `:182`): hängt der Keyring, warten alle anderen Handshakes mit
   selbstsigniertem Zertifikat und `forget_pin` (`:330-339`) an derselben Sperre. `export_identity`
   (`frpc.rs:325-333`) liest die Identität in der async-Reconciliation über `load_identity`.

3. **Nach der Zeitüberschreitung läuft der Verbindungsaufbau weiter und startet doch (R-0642).** `run_with_deadline`
   (`commands.rs:289-301`) gibt nach `OPEN_CONNECTION_TIMEOUT` (30 s, `:287`) den Fehler „Verbindungsaufbau:
   Zeitueberschreitung …“ zurück und lässt nur den `JoinHandle` fallen; die Arbeit in `spawn_blocking` läuft weiter.
   `check_rdp_auth` wartet ohne eigene Frist auf `xfreerdp +auth-only` (`connection/rdp.rs:570-629`,
   `wait_with_output` `:606`). Endet die Prüfung später erfolgreich, startet `open_rdp` das RDP-Fenster
   (`spawn_rdp_with_password`, `:131`), obwohl die UI schon die Zeitüberschreitung gemeldet hat. Ebenso nach einem
   Keyring-Lesezugriff, der auf eine Entsperr-Abfrage wartet (`open_connection_stored` → `load_password_keyring`,
   `connection/mod.rs:194-197`), und unter Windows (`start_mstsc`, `rdp.rs:179-182`). Der Test
   `run_with_deadline_maps_a_hung_task_to_a_timeout_error` (`commands.rs:682-691`) prüft nur die Meldung.

4. **Eine Tunnel-Zeile mit Port außerhalb von `u16` lässt `fetch_tunnels` scheitern (R-0569).** `TunnelMapping` hat
   `local_port: u16` und `visitor_port: Option<u16>` (`tunnel.rs:23-24`); `fetch_tunnels` dekodiert die ganze Liste
   in einem Zug (`:60`). Der Server darf mehr liefern: `FrpTunnelOut` hat `localPort: int`, `visitorPort:
   Optional[int]` (`apps/server/app/modules/frp/schemas.py:320`, `:323`), `local_port` ist beim Anlegen nur ein
   INTEGER (`IntColumn`, `:245`), `visitor_port` ist erst seit R-0533 auf 1–65535 begrenzt (`:248`), ältere Zeilen
   bleiben, wie sie sind (`config_generator.py:112-125`). Eine solche Zeile, und der Tunnel-Store hat keine
   Zuordnungen (`apps/desktop/ui/src/lib/stores/tunnel.ts:219-223` behält die letzten, anfangs keine).

5. **Test mit festen Namen, die eine PID sein können (R-0572).** `write_json_atomic_removes_only_the_stale_temps_of_the_same_file`
   (`storage.rs:1560-1596`) legt `prefs.json.4243.tmp` und `prefs.json.4244.tmp` als fremde, junge Temp-Dateien an
   und erwartet sie danach (`:1590-1591`). `write_json_atomic` schreibt seine eigene Temp-Datei unter
   `<pfad>.<std::process::id()>.tmp` (`:120-122`, mit `truncate`, `:177-185`) und benennt sie um (`:125`): trägt der
   Testprozess pid 4243 oder 4244 (unter Windows üblich), ist die Fixture die eigene Temp-Datei, und der Test fällt.

6. **Ansible-Temp-Dateien (R-0574).** (a) Kein Test prüft, dass die Dateien erst nach dem Ende von
   `ansible-playbook` gelöscht werden: Ohne `trap exit HUP TERM` (`ansible.rs:206`) stirbt bash beim SIGHUP sofort
   und löscht im EXIT-Trap, während `ansible-playbook` noch läuft; am Ende sind die Dateien so oder so weg, der
   HUP-Test (`:373-380`) bliebe grün. Probe (unten, Beweis): mit dem Trap sieht ein Stub, der 0,3 s nach dem Signal
   nachsieht, beide Dateien, ohne ihn keine. (b) Scheitert `ansible_write_playbook`, nachdem
   `ansible_generate_inventory` geschrieben hat, bleibt das Inventory liegen (`apps/desktop/ui/src/lib/stores/ansible.ts:145-147`;
   nur ein gescheiterter Start räumt auf, `ansible.rs:150-165`). Ebenso bleibt eine angefangene Datei liegen, wenn
   das Schreiben nach dem Anlegen scheitert (`ansible.rs:88-89`, `:113-114`).

## Ziel & Nicht-Ziele

Ziel:
- Kein Command aus (1) läuft auf dem Main-Thread oder wartet auf einem tokio-Worker auf Keyring oder Dateisperre:
  er ist `async` und führt seine Arbeit über `blocking()` aus. Name, Argumente und Antwort bleiben.
- Die Identität (Schlüssel, Zertifikat, CA-Kette) des Workspace liest der Prozess einmal aus dem Keyring und hält sie
  im Speicher; jedes Schreiben der Identität (Registrieren, Erneuern, Zurücksetzen, Löschen) lädt sie neu. Ein
  gescheiterter Lesezugriff wird nicht behalten.
- Der TOFU-Verifier hält die globale Pin-Sperre nie über einen Keyring-Zugriff; Lesen, Entscheiden und Speichern
  eines Pins laufen je Identität nacheinander. Die Entscheidung bleibt atomar, ein unlesbarer oder nicht
  beschreibbarer Keyring weist weiter ab (3.60, `Unavailable` aus desktop-tofu-store), und ein erster Kontakt gilt
  erst nach dem gelungenen Speichern (Invariante von desktop-tofu-store).
- Hat die UI die Zeitüberschreitung gemeldet, startet der Verbindungsaufbau nichts mehr; hat die Arbeit ihren Start
  vor der Frist begonnen, bekommt die UI dessen Ergebnis statt der Zeitüberschreitung. `check_rdp_auth` endet
  spätestens mit der Frist und beendet `xfreerdp`.
- `fetch_tunnels` nimmt jede Zeile, die der Server liefern darf; ein Port außerhalb von 1–65535 löst keinen Visitor
  auf.
- Der Temp-Test hängt nicht mehr an der PID; die Lösch-Reihenfolge des Ansible-Laufs ist gepinnt; ein gescheitertes
  Schreiben lässt keine Ansible-Datei dieses Laufs liegen.

Nicht-Ziele (YAGNI):
- Keine weiteren synchronen Commands (`generate_diagnostics`, `load_connections`, `save_connections`,
  `workspace_context`, `open_launcher`, `ansible_*`, `stop_tunnel`, `tunnel_status`): Datei-IO ohne Sperre und ohne
  Keyring, nicht Teil von R-0643.
- Die verbleibenden, seltenen Keyring-Zugriffe auf einem tokio-Worker bleiben auf dem aufrufenden Thread: der erste
  Lesezugriff je Prozess (meist beim Login in `client_for`) und das Schreiben bei Registrierung, Erneuerung und
  Zurücksetzen (`enrollment.rs:488-519`, `:614-643`, `:384-396`). Sie auf Blocking-Threads zu legen, hieße die
  async-Abläufe in `enrollment.rs` umzubauen und den Test-Keyring je Thread (`keyring_store.rs:92-96`, R-0294)
  aufzugeben; alle sind Nutzeraktionen und blockieren weder Main-Thread noch einen Request-Pfad (offene Frage 3).
- Kein neuer Fehler, wenn der Keyring die Identität nicht lesen kann: der Aufruf geht wie heute ohne Identität
  (offene Frage 2), dazu eine Warnung einmal je Prozess im Log.
- Keine Änderung an `frpc.rs`: `export_identity` liest nach T8 aus dem Speicher.
- Kein neuer Tauri-Command, keine Änderung an `stores/ansible.ts` oder `bridge/` (R-0574 löst Rust, Trade-off 5).
- Keine Prüfung der Tunnel-Ports im Desktop über die Auflösung hinaus; was der Server speichert, bleibt seine Sache.

## Betroffene Komponenten & Dateien

| Task | Roadmap | Komponente | Dateien |
|---|---|---|---|
| T1 | R-0572 | desktop-rs | `storage.rs` |
| T2 | R-0569 | desktop-rs | `tunnel.rs`, `CHANGELOG.md` |
| T3 | R-0574 | desktop-rs | `ansible.rs` |
| T4 | R-0574 | desktop-rs | `ansible.rs`, `CHANGELOG.md` (verkleinert, Ledger `## Entscheidungen` 2026-10-29) |
| T5 | R-0643 | desktop-rs | `commands.rs`, `CHANGELOG.md` |
| T6 | R-0642 | desktop-rs | `connection/rdp.rs` |
| T7 | R-0642 | desktop-rs | `commands.rs`, `connection/mod.rs`, `connection/rdp.rs`, `CHANGELOG.md` |
| T8 | R-0644 | desktop-rs | `enrollment.rs`, `http_client.rs`, `CHANGELOG.md` |
| T9 | R-0644 | desktop-rs | `tofu.rs` |

Risikopfade (`scripts/dev/review-risk.txt`): `tunnel.rs` (T2), `enrollment.rs` und `http_client.rs` (T8), `tofu.rs`
(T9) bekommen zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration, keine Server-Route. Tauri-IPC: Namen, Argumente und Erfolgsantworten aller Commands bleiben.
`pinned_ca_fingerprint` und `is_device_enrolled` liefern intern `Result<…, AppError>` statt des nackten Werts; auf
dem Draht ist ein Erfolg derselbe Wert, ein Fehler entsteht nur, wenn die Blocking-Task nicht zu Ende kommt, und die
UI fängt beide schon ab (`SettingsModal.svelte:114-129`, `ProvisioningTab.svelte:124-126`). Alle Aufrufer der neun
Commands warten ihr Ergebnis ab (`await` in `stores/settings.ts:83`, `stores/session.ts:85`, `:112`, `:152`, `:157`,
`stores/connectFlow.ts:173`, `:186`, `ConnectionEditor.svelte:72`, `SettingsModal.svelte:116`, `:124`, `:164`,
`:290`, `Login.svelte:107`; `ProvisioningTab.svelte:124` über `.then`): dass async Commands nebeneinander laufen
können, ändert keine Reihenfolge. `TunnelMapping` behält Feldnamen und JSON (`bridge/types.ts:109-120`: `number`); der
Paritätstest (`ui/src/lib/bridge/types.parity.test.ts`) vergleicht nur Namen. Neue Hilfstypen bleiben nicht `pub`,
damit der Paritätstest sie nicht als Bridge-Typ sieht.

## Externe Integrationen

- Tauri v2, „Calling Rust from the Frontend“ (https://v2.tauri.app/develop/calling-rust/, gelesen 2026-10-22):
  „Commands without the async keyword are executed on the main thread unless defined with
  `#[tauri::command(async)]`.“ — „Async commands are executed on a separate async task using async_runtime::spawn.“ —
  „Since invoking the command from JavaScript already returns a promise, it works just like any other command.“
  Belegt am Quelltext: `tauri-macros-2.6.3/src/command/wrapper.rs:264` (`#[tauri::command(async)]` an einer
  synchronen Funktion ist `sync_threadpool`) und `:388-394` (der Körper läuft in `respond_async_serialized`),
  `tauri-2.11.5/src/ipc/mod.rs:375` (`crate::async_runtime::spawn`): eine synchrone Funktion mit `(async)` blockiert
  einen tokio-Worker. Deshalb `async fn` mit `blocking()`, nicht `(async)`.
- tokio 1.51.0 (`Cargo.lock`), `src/task/blocking.rs:106-110`: „Be aware that tasks spawned using `spawn_blocking`
  cannot be aborted because they are not async. If you call [`abort`] on a `spawn_blocking` task, then this *will not
  have any effect*, and the task will continue running normally.“ Ein fallengelassener `JoinHandle` hält sie erst
  recht nicht an (R-0642).
- `keyring` 3.6.3 (Secret Service): je Zugriff `SecretService::connect` (`src/secret_service.rs:337`), gesperrte
  Einträge `item.unlock()` (`:361-363`).
- serde: eine Zahl außerhalb von `u16` ist ein Fehler der ganzen Deserialisierung, eine `Vec` scheitert als Ganzes
  (das zeigt der Test von T2 auf HEAD rot).
- bash 5.2.37: Die Probe zu (6a) zeigt, dass bash mit `trap exit HUP TERM` den EXIT-Trap erst nach dem Ende des
  Vordergrundbefehls ausführt und ohne ihn sofort.

## Trade-offs & Alternativen

1. **Async-Weg für R-0643.** (a) `pub async fn` + `blocking(move || …)` — **Empfehlung**: Main-Thread und tokio-Worker
   bleiben frei, der Helfer ist da und für die Workspace-Commands erprobt. (b) `#[tauri::command(async)]`: läuft auf
   einem tokio-Worker (siehe oben), ein hängender Keyring hält dann einen Worker. (c) `spawn_blocking` in jedem
   Modul: verstreut, und die `_in`-Funktionen verlören ihre Tests auf dem Test-Thread.
2. **Beweis für R-0643.** Ein Strukturtest über den eigenen Quelltext (`include_str!("commands.rs")`): jeder der neun
   ist `#[tauri::command] pub async fn` und ruft `blocking(`. Rot auf HEAD, rot bei jedem Rückfall auf synchron.
   Alternative `tauri::test::mock_app` braucht das Feature `test` in `Cargo.toml` und sähe den Thread doch nicht, weil
   Keyring und Workspace im Test je Thread gelten.
3. **Identität im Speicher (T8).** (a) In `enrollment.rs` die drei Einträge je Prozess halten, Neuladen über einen
   Helfer an den vier Stellen, die heute `invalidate_client_cache` rufen (`enrollment.rs:199`, `:457`, `:469`,
   `:516`), mit Generationszähler gegen einen Lesezugriff, der ein Schreiben überlappt — **Empfehlung**: alle Leser
   (`client_for`, `export_identity`, Settings, Renew) profitieren ohne Änderung an ihnen. (b) Nur den `mtls`-Wert im
   Client-Cache-Schlüssel merken: `export_identity`, `enrolled_client` und die Settings-Commands läsen weiter je Aufruf.
   (c) `client_for` async machen und den Lesezugriff auf `spawn_blocking` legen: zwölf Aufrufer in sechs Dateien und
   der Test-Keyring je Thread.
   Gültigkeit: in Produktion je Prozess (das Präfix steht nach `set_current` fest), in Test-Builds je Thread und
   Keyring-Präfix wie `workspace::current` (`workspace.rs:656-663`), sonst sähen parallele Tests und die
   Workspace-Wechsel in einem Test (`enrollment.rs:1807-1829`) fremde Werte. Die migrierten Workspaces teilen ihre
   Schlüssel ohne Präfix (`docs/developer/desktop.html:136`), Identität hat davon nur der eine migrierte
   Server-Workspace (`:124`); ein zweiter Prozess, der dieselbe Identität ändert, ist damit ausgeschlossen.
4. **TOFU ohne IO unter der globalen Sperre (T9).** (a) Eine Sperre je Pin-Identität: die globale Sperre schützt nur
   die Maps (Cache und die Sperren je Identität) und wird nie über IO gehalten; Cache-Treffer entscheiden wie heute
   sofort; ein Fehlgriff nimmt die Sperre seiner Identität, sieht erneut in den Cache, liest den Keyring, speichert bei
   einem Erstkontakt und legt den Pin erst nach `Ok` in den Cache; `forget_pin` nimmt dieselbe Sperre —
   **Empfehlung**: Lesen→Entscheiden→Speichern bleibt je Identität atomar, die Invariante von desktop-tofu-store
   (erst gespeichert, dann vertraut) bleibt ohne Sonderfälle, und ein hängender Keyring hält nur Verbindungen zum
   selben Server auf. (b) Lesen außerhalb der Sperre mit Generationszähler und Schreiben nach der Sperre: das Schreiben
   käme nach dem Annehmen (bricht die Invariante), ein paralleler Erstkontakt bräuchte ein eigenes Warten. (c) Den Pin
   schon beim Bau des Clients laden: der gecachte Client trüge einen unlesbaren Zustand weiter, bis der Cache fällt,
   und das Speichern beim Erstkontakt bliebe im Handshake.
5. **Inventory bei gescheitertem Playbook (T4).** (a) Rust merkt sich die Inventories, die `generate_inventory`
   geschrieben und noch kein Start übernommen hat; ein gescheitertes `write_playbook_temp` löscht sie —
   **Empfehlung**: kein neuer Command, die UI bleibt; ein Fenster fährt immer nur einen Lauf (`ansibleCanRun`,
   `stores/ansible.ts:59-62`). (b) Neuer Command zum Verwerfen, den `runPlaybook` im `catch` ruft: Vertragsänderung
   (`main.rs`, Bridge, `ipc.inventory.test.ts`, Command-Tabellen der Entwickler-Doku), Kevins Bereich. (c)
   Reihenfolge tauschen: ließe dann das Playbook liegen, wenn das Inventory an der Prüfung der Hostnamen scheitert
   (`ansible.rs:39-47`), dem häufigeren Fehler.
6. **Ports in `TunnelMapping` (T2).** (a) `i64`/`Option<i64>`, Auflösung nur über `u16::try_from` — **Empfehlung**: die
   Liste zeigt jede Zeile wie der Server und die Web-UI, keine Filterlogik. (b) Zeilen mit fremdem Port überspringen:
   der Desktop verschwiege Zeilen. (c) eigener Deserializer, der auf `None` abbildet: `localPort` ist nicht optional,
   `bridge/types.ts` müsste mit.
7. **Frist und Start (T7).** Ein `Deadline` mit drei Zuständen (offen, gestartet, abgelaufen): die Arbeit beansprucht
   den Start unmittelbar vor dem ersten Seiteneffekt, `run_with_deadline` erklärt die Frist nach dem Timeout nur für
   abgelaufen, wenn noch nichts gestartet ist, sonst wartet es auf das Ergebnis. Alternative: nur ein Abbruch-Flag —
   zwischen Prüfen des Flags und dem Start bliebe ein Fenster, in dem die UI „Zeitüberschreitung“ meldet und das
   Fenster doch aufgeht.

## Risiken & Rollback

- T5: Async Commands können nebeneinander laufen. Die Zustände dahinter haben ihre Sperren (`SEEN_PREFS`,
  `META_LOCK`, `storage.rs:465-480`, `:329-334`; `INDEX_LOCK`, `password.rs:319`); alle UI-Aufrufer warten ab (oben).
- T7: Nach dem Start wartet `run_with_deadline` auf das Ergebnis; was danach noch läuft, ist kurz (Passwort auf stdin,
  unter Windows der Zeitgeber für den `TERMSRV`-Eintrag). Unter Windows schreibt `start_mstsc` den Eintrag vor dem
  Start; eine abgelaufene Frist lässt den Start scheitern, und `run_termsrv_plan` entfernt Eintrag und Hold
  (`password.rs:529-569`).
- T8: Ein Lesefehler beim ersten Zugriff wird nicht gehalten, der nächste Aufruf liest neu; ist der Keyring dauerhaft
  unerreichbar, liest jeder Aufruf wie heute. Tests, die Identitäts-Einträge am `enrollment` vorbei schreiben, nachdem
  sie gelesen haben, rufen danach den Neulade-Helfer.
- T9: Ein Handshake zum selben Server wartet, solange der Keyring für diesen Pin hängt (heute warten alle). Ein
  `forget_pin` wartet auf einen laufenden Erstkontakt derselben Identität und entfernt danach Cache-Eintrag und
  Keyring-Eintrag; es läuft nach T5 auf einem Blocking-Thread (`reset_server_cert_pin`) bzw. auf einem tokio-Worker in
  `reset_device_identity_in` (`commands.rs:145`, Reset-Pfad, Nicht-Ziele). Die Sperren je Identität bleiben für die Laufzeit des Prozesses (ein Eintrag je Server).
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T4: `docs/admin/ansible.html:67` und `docs/developer/desktop.html:114` (DE+EN): ein gescheitertes Schreiben löscht,
was der Lauf schon geschrieben hat; dazu die Reihenfolge in `ansible.html:67` richtig (erst das Inventory, dann das
Playbook, `stores/ansible.ts:145-146`). CHANGELOG (Fixed) für T2, T4, T5, T7, T8. T1, T3, T6, T9: keine (Tests bzw.
ohne sichtbare Änderung; T6 wird mit T7 sichtbar).

## Offene Fragen

1. **Multibox vor dem Merge (CLAUDE.md §5, Kevins Ja).** T8 und T9 ändern Identität und TOFU im Desktop, die nur die
   Desktop-Journeys gegen einen entfernten Server unter erzwungenem mTLS über Hosts hinweg zeigen. Empfehlung:
   `scenario --agents 0 --desktop --enforce` vor dem Merge; ohne Ja bleibt es bei `linux-full` im Sammellauf und dem
   CI-Job `rust-windows`.
2. **Unlesbare Identität.** Soll ein Keyring-Lesefehler in `client_for` ein Fehler werden statt eines Requests ohne
   Zertifikat? Empfehlung: nein — Geräte ohne Secret Service blieben sonst ohne Login; die Warnung im Log macht den
   Fall sichtbar. Keine Task hängt daran.
3. **Restliche Keyring-Zugriffe auf tokio-Workern (R-0644, Abhilfe „per spawn_blocking“).** Empfehlung: hinnehmen
   (Nicht-Ziele); bei Bedarf eine eigene Zeile. Keine Task hängt daran.
