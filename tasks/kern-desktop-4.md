<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-4 — Task-Ledger
Status: erledigt · Branch: feature/kern-desktop-4 · Review: pro Task
Spec: docs/features/kern-desktop-4.md (Roadmap R-1012, R-1013, R-1041)
Heavy: linux-full — Desktop-Journeys (Login, Tunnel-Abgleich, Keyring, mTLS) nach Crate-Majors; Windows über die CI-Jobs rust-windows
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@5bbfc896`.

### T1 — Gesamtfrist für Listen-, Bundle- und Playbook-Antworten (R-1012)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/http_client.rs, apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/ansible.rs, changelog.d/kern-desktop-4.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @581212ab 2026-11-02T13:31:28+01:00
Review: approve (.ah-out/review/kern-desktop-4/T1.verdict.json)
Beweis: security kern-desktop-3 T1 (Nit), 2026-10-30 · `sync.rs:48` `read_list`, `frpc.rs:273` `bundle_from`, `ansible.rs:71` `fetch_json`: Schleife über `response.chunk()` nur mit Bytegrenze · Dedup-Key: ref:desktop:read-bounds-no-total-deadline
Änderung: Ein Leser `read_bounded(response, max_bytes)` in `http_client.rs` mit Bytegrenze (Content-Length vorab, dann je Chunk) und Gesamtfrist 120 s (`tokio::time::timeout` über die Schleife), Fehler `TooLarge`/`TimedOut` ohne Zitat der Antwort; die drei Aufrufer nutzen ihn und behalten ihre Texte (Frist: „… (answer took longer than 120 s)“). Test (erst rot): ein Testserver, der unterhalb von `READ_TIMEOUT` tropft, endet nach der (im Test verkürzten) Frist mit Fehler; die vorhandenen 16-MiB-Tests bleiben grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-desktop-4.md

### T2 — spawn_blocking-Pfad von off_worker im Test (R-1013)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f9ec0ca6 2026-11-02T13:41:00+01:00
Review: approve (.ah-out/review/kern-desktop-4/T2.verdict.json)
Änderung: Den `spawn_blocking`-Zweig von `off_worker` (`enrollment.rs:522`) als eigene Funktion `on_blocking_thread` herausziehen, die der Nicht-Test-Pfad aufruft; Tests fahren sie mit einer Funktion ohne Thread-lokale Fakes: der Wert kommt zurück und läuft auf einem anderen Thread, eine Panik wird `AppError::Io` mit „did not finish“. Der `#[cfg(test)]`-Kurzschluss bleibt (Fakes je Thread).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (nur Test und interne Struktur)

### T3 — Kompatible Crate-Updates und Tauri-JS auf 2.12 (R-1041)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock, apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, changelog.d/kern-desktop-4.md
Evidenz: run.sh[quick] desktop-rs desktop-ui: 2 passed, 0 failed, 16 skipped @1df07b64 2026-11-02T14:10:41+01:00
Review: approve (.ah-out/review/kern-desktop-4/T3.verdict.json)
Änderung: `cargo update` (u. a. tauri 2.12.5, tokio 1.54); `@tauri-apps/api` und die Plugins (`plugin-dialog`, `plugin-notification`, `plugin-shell`) auf die zur Crate passende Minor (`apps/desktop/ui/package.json:44`), Lockfile per `npm install`. Major.Minor von `tauri` und `@tauri-apps/api` gleich.
Verify: bash scripts/dev/verify.sh desktop-rs desktop-ui --strict
Doku: changelog.d/kern-desktop-4.md

### T4 — reqwest 0.13 bei gleichen Vertrauensankern (R-1041)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/http_client.rs, apps/desktop/src-tauri/src/tofu.rs, apps/desktop/src-tauri/src/enrollment.rs, changelog.d/kern-desktop-4.md, apps/desktop/src-tauri/src/proxy.rs, apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @a17affd4 2026-11-02T14:21:11+01:00
Review: approve (.ah-out/review/kern-desktop-4/T4.verdict.json)
Änderung: `reqwest = "0.13"` (`Cargo.toml:17`) mit `rustls-no-provider` statt `rustls-tls` und explizitem ring-Provider wie bei rustls (`Cargo.toml:44`), damit aws-lc draußen bleibt (`cargo tree -i aws-lc-rs` leer); Public-CA-Pfad (`http_client.rs`) weiter mit webpki-roots über `tls_certs_only`, TOFU- und mTLS-Pfad unverändert; umbenannte TLS-Methoden nachziehen. `src/test_tls.rs` bleibt unverändert grün; ein Test belegt, dass der Public-CA-Client ein selbstsigniertes Zertifikat ablehnt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-desktop-4.md

### T5 — keyring 4 mit denselben Einträgen (R-1041)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/keyring_store.rs, changelog.d/kern-desktop-4.md, docs/developer/desktop.html, docs/en/developer/desktop.html, THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @798b9517 2026-11-02T14:35:09+01:00
Review: approve (.ah-out/review/kern-desktop-4/T5.verdict.json)
Änderung: `keyring = "4"` (`Cargo.toml:26`) mit den Stores für macOS, Windows und Secret Service (async, ohne openssl). Vorher aus dem Quelltext der Store-Crates belegen, dass Service/Konto auf dieselben Attribute (Secret Service `service`/`username`, Windows-Target-Name, Keychain service/account) abgebildet werden wie in keyring 3; Beleg unter `## Entscheidungen`. Ohne Beleg: Task `[?]` (Datenmigration). Probe nur gegen einen toten Bus (`DBUS_SESSION_BUS_ADDRESS` auf eigenen Pfad).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-desktop-4.md

### T6 — rcgen 0.14, sha2 0.11, toml 1, windows 0.62 (R-1041)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/terminal.rs, apps/desktop/src-tauri/src/launcher.rs, changelog.d/kern-desktop-4.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @4da99694 2026-11-02T14:46:55+01:00
Review: approve (.ah-out/review/kern-desktop-4/T6.verdict.json)
Änderung: Die vier Majors (`Cargo.toml:45`, `:48`, `:59`, `:69`) und die API-Änderungen in den Aufrufern; rcgen weiter mit ring. Windows-Code kompiliert per `cargo check --target x86_64-pc-windows-gnu` oder die CI-Jobs rust-windows (Ergebnis im Commit-Body). Mehr als acht Dateien nur, wenn die Aufrufer es verlangen (dann `set-files`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-desktop-4.md

## Entscheidungen
- 2026-11-02 Plan: Vertrauensanker bleiben bei reqwest 0.13 gleich (kein `rustls-platform-verifier` als Wurzelquelle); ein Wechsel auf den System-Truststore wäre sichtbares Verhalten und eine eigene Zeile.
- 2026-11-02 Plan: `kern-laufzeit-1` T3 ändert ebenfalls `apps/desktop/ui/package.json`/Lockfile; wer später merged, erzeugt das Lockfile nach dem main-Merge neu.
- 2026-11-02 T4: Statt `tls_certs_only` bekommt jeder Client in `http_client::with_timeouts` eine vorkonfigurierte rustls-Config (ring, `webpki_roots::TLS_SERVER_ROOTS`). Grund: Mit `rustls-no-provider` greift reqwest 0.13.5 beim Bauen zum Prozess-Default-Provider und bricht ohne einen mit panic ab (`default_rustls_crypto_provider`, async_impl/client.rs). Außerdem bräuchte `tls_certs_only` volle Zertifikate, keine TrustAnchors. TOFU und mTLS überschreiben die Config wie bisher; die Test-Clients in frpc.rs und proxy.rs laufen deshalb ebenfalls über `with_timeouts`. Den Beleg für die Ablehnung selbstsignierter Zertifikate liefert der bestehende Test `error.rs` (`ERR_TLS_UNKNOWN_ISSUER` über den Public-CA-Client).
- 2026-11-02 T5: Beleg Zuordnung keyring 3 → 4 (Quelltext keyring-3.6.3, zbus-secret-service-keyring-store-1.0.1, apple-native-keyring-store-1.0.2): Secret Service v3 legte `service`, `username`, `target=default`, `application=rust-keyring` an, v4 sucht über alle Collections nach `service`+`username` (cred.rs `search_attributes`, kein target gesetzt) — die Secret-Service-Suche ist eine Teilmengen-Suche, v3-Einträge werden gefunden und bei `set` überschrieben statt dupliziert; Keychain v3 und v4: generic password service/account im User-Keychain; Windows nutzt keyring nicht (wincred in password.rs). Statt der `keyring`-4-Fassade `keyring-core` mit den Store-Crates und einem Store je Aufruf (`os_entry`): die Fassade setzt den Default-Store einmal je Prozess (LazyLock in v1.rs) mit einer festen Secret-Service-Verbindung, ein Fehler oder ein Neustart des Dienstes bliebe bis zum App-Neustart; keyring 3 verband je Aufruf. Test: Kindprozess mit totem Bus, Lesen ist `Err`, nicht `Ok(None)` (Gegenprobe rot).
