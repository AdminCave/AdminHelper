<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-4 — Desktop: Gesamtfrist für Antworten, Reset-Pfad im Test, Crates aktuell

Roadmap: R-1012 (REF), R-1013 (REF), R-1041 (REF). Zeilenangaben `origin/main@5bbfc896`.

## Problem / Motivation
- **R-1012:** Die Leser der Verbindungsliste (`apps/desktop/src-tauri/src/sync.rs:48` `read_list`), des
  Visitor-Bundles (`src/frpc.rs:273` `bundle_from`) und eines Playbooks (`src/ansible.rs:71` `fetch_json`) deckeln die
  Bytes (16 MiB), nicht die Dauer. Eine Antwort, die knapp unter `READ_TIMEOUT` (45 s, `src/http_client.rs:75`) je
  Chunk tropft, hält den Abruf beliebig lange offen. Die drei Schleifen sind gleich gebaut.
- **R-1013:** `off_worker` (`src/enrollment.rs:522`) läuft in Tests inline (`#[cfg(test)]`); der
  `spawn_blocking`-Pfad, den das Programm nimmt, ist ungeprüft. Er funktioniert nur, weil Workspace und Keyring
  prozessweit sind; die Test-Fakes sind je Thread.
- **R-1041:** Kevin 2026-11-02: alles auf aktuelle Stable. Offen sind reqwest 0.12 → 0.13, keyring 3 → 4,
  rcgen 0.13 → 0.14, sha2 0.10 → 0.11, toml 0.8 → 1, windows 0.61 → 0.62 und 212 kompatible Updates (`cargo update
  --dry-run`), darunter tauri 2.11.5 → 2.12.5. `@tauri-apps/api` steht im Lockfile auf 2.11.0 und muss zur
  Tauri-Crate passen.

## Ziel & Nicht-Ziele
- Ziel: Ein gemeinsamer Leser `read_bounded` in `http_client.rs` mit Bytegrenze und Gesamtfrist (120 s ab dem
  ersten Byte des Bodys); die drei Aufrufer nutzen ihn und behalten ihre Fehlertexte.
- Ziel: Ein Test fährt den echten `spawn_blocking`-Pfad von `off_worker` (Rückgabe und Panik als Fehler).
- Ziel: Alle genannten Crates auf aktueller Stable, Tauri-JS-Pakete auf derselben Minor wie die Crate.
- Nicht-Ziel: Verhalten der TLS-Prüfung ändern. reqwest 0.13 nimmt per Default `rustls-platform-verifier` und
  aws-lc; die Migration hält die heutigen Vertrauensanker (webpki-roots im Public-CA-Pfad, gepinnte CA bei mTLS,
  TOFU-Pin) und den ring-Provider. Ein Wechsel auf den System-Truststore wäre eine eigene Zeile.
- Nicht-Ziel: Format der Keyring-Einträge ändern; vorhandene Passwörter und Identitäten müssen lesbar bleiben.

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/` (`Cargo.toml`, `Cargo.lock`, `src/http_client.rs`, `src/sync.rs`, `src/frpc.rs`,
`src/ansible.rs`, `src/enrollment.rs`, `src/keyring_store.rs`, `src/tofu.rs` und die Aufrufer der Crate-APIs),
`apps/desktop/ui/package.json`, `apps/desktop/ui/package-lock.json`, `changelog.d/kern-desktop-4.md`.

## Datenmodell / API / Migrationen
Keine Tauri-Command-Signatur ändert sich. Keyring: Dienstname und Konto je Eintrag bleiben gleich; die Task prüft,
dass die keyring-4-Stores (Secret Service, Windows Credential Manager, macOS Keychain) Einträge der Version 3
unter denselben Attributen finden. Lässt sich das nicht belegen, wird die Task `[?]` (Datenmigration = Kevin).

## Externe Integrationen
- reqwest 0.13 CHANGELOG (https://github.com/seanmonstar/reqwest/blob/master/CHANGELOG.md): `rustls-tls` heißt
  `rustls`, Default-Provider aws-lc (`rustls-no-provider` ohne), Wurzeln über `rustls-platform-verifier`, andere über
  `tls_certs_only`; TLS-Methoden umbenannt (Soft-Deprecation). Features: https://docs.rs/crate/reqwest/latest/features
- keyring 4.2 (https://docs.rs/crate/keyring/latest/features): API in `keyring-core`, Stores als eigene Crates
  (`apple-native-keyring-store`, `windows-native-keyring-store`, `zbus-secret-service-keyring-store`), Feature `v1`
  für die alte API.
- Tauri: Versionen von `tauri` (Rust) und `@tauri-apps/api` (JS) müssen in Major.Minor übereinstimmen
  (`tauri build` prüft das).

## Trade-offs & Alternativen
- R-1012: Eine Frist über die ganze Schleife (`tokio::time::timeout`) statt je Chunk. **Empfehlung**, weil sie die
  Dauer unabhängig vom Tropftempo begrenzt. 120 s reichen für 16 MiB ab ~1,1 Mbit/s. Alternative: Client-weites
  `timeout()`, das bricht aber den SSE-Strom (`http_client.rs:72`).
- R-1013: Den `#[cfg(test)]`-Kurzschluss lassen (die Fakes sind je Thread) und einen eigenen Test schreiben, der
  eine Funktion ohne Fakes über den `spawn_blocking`-Zweig schickt. Dafür wird der Zweig eine eigene Funktion.
- R-1041: In einzeln zurücknehmbaren Schritten: erst kompatible Updates und Tauri-JS, dann reqwest (TLS), dann
  keyring (Datenpfad), dann die übrigen Majors.

## Risiken & Rollback
- reqwest 0.13 berührt jeden TLS-Pfad (Public CA, TOFU, mTLS): `security` je Task, die TLS-Tests in
  `src/test_tls.rs` müssen unverändert grün bleiben.
- keyring 4 berührt gespeicherte Geheimnisse. Ein falscher Store oder ein geändertes Attribut sieht aus wie
  „keine Passwörter mehr“.
- `kern-laufzeit-1` ändert ebenfalls `apps/desktop/ui/package.json` und das Lockfile (`@types/node`). Wer später
  merged, holt `origin/main` und erzeugt das Lockfile mit `npm install` neu.
- Rollback: Revert der jeweiligen Task.

## Doku-Impact
Keine Nutzer-Doku (kein sichtbares Verhalten außer dem Abbruch tropfender Antworten nach 120 s); CHANGELOG über
`changelog.d/kern-desktop-4.md`.

## Offene Fragen
Keine. Bleibt die Keyring-Kompatibilität unbelegt, wird T5 zur Frage an Kevin.
