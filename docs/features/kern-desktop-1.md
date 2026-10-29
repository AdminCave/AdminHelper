<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Nacharbeiten an Sync, Client-Cache, RDP-Start, Geräte-Reset und Tunnel-Hinweis

Zug `kern-desktop-1` (Roadmap R-0876, R-0930, R-0932, R-0870, R-0931, R-0948). Stand des Codes: `origin/main@fd3a3b32`.
Pfade ohne Präfix liegen unter `apps/desktop/src-tauri/src/`. R-0842 und R-0871 aus diesem Zug ändern Dateien des
offenen Branches `feature/ca-rotation` (`ProvisioningTab.svelte`, `enrollment.rs`) und fahren im Zug `kern-desktop-2`.

## Problem / Motivation

1. **Sync-Antwort ohne Grenze (R-0876).** `sync.rs:35` und `:81` lesen die Antwort mit `response.json()` ganz ein.
   `ansible.rs` begrenzt dieselbe Art Antwort seit desktop-hardening-3 auf 16 MiB (`MAX_RESPONSE_BYTES`).
2. **Client-Cache und Identitätswechsel (R-0930).** `client_for` (`http_client.rs:60-102`) baut den Client und legt
   ihn danach im Cache ab (`:101`). Läuft dazwischen `invalidate_client_cache` (`:108`), bleibt ein Client mit dem
   alten Vertrauensmaterial im Cache. Einzelheiten privat.
3. **RDP-Start nach Fristende, Pin-Laden ohne Sperre (R-0932).** `open_rdp` (`connection/rdp.rs:127-136`) ruft
   `check_rdp_auth` auch, wenn die Frist schon abgelaufen ist; `KeyringPinStore::load` (`tofu.rs:211`) nimmt die
   Sperre je Identität nicht. Einzelheiten privat.
4. **Geräte-Reset auf dem async-Worker (R-0931).** `reset_device_identity_in` (`commands.rs:146-155`) ruft
   `tofu::forget_pin` direkt im async-Kontext; `reset_server_cert_pin` führt es über `blocking()`.
5. **Geräte-Reset, Fehlerpfad (R-0870, BUG).** Scheitert der Reset, bleibt `deviceEnrolled` in
   `SettingsModal.svelte:196-205` unverändert und `refreshDeviceIdentity()` läuft nicht; scheitert nach einem
   Widerruf nur lokal (`LocalOnly`) zusätzlich das Pin-Löschen, nennt der Fehler nur das Pin-Löschen.
6. **Tunnel endet ohne Grund (R-0948, FEAT).** `carries_bundle` (`frpc.rs:278`) behandelt 403 wie 404 als „keine
   Tunnel“; der Abgleich stoppt frpc, die UI (`lib/stores/tunnel.ts:216`) sieht nur `stopped`.

## Ziel & Nicht-Ziele

Ziel: je Zeile das beschriebene Verhalten, mit Test. Nicht-Ziele: Änderungen am Server, neue Einstellungen,
Änderungen an `enrollment.rs` und `ProvisioningTab.svelte` (Überlappung, s. o.).

## Betroffene Komponenten & Dateien

`desktop-rs`: `sync.rs`, `http_client.rs`, `connection/rdp.rs`, `tofu.rs`, `commands.rs`, `frpc.rs`.
`desktop-ui`: `components/SettingsModal.svelte`, `lib/bridge/types.ts`, `lib/stores/tunnel.ts`, i18n, Tests.

## Datenmodell / API / Migrationen

Keine Migration, keine Server-API. Tauri-IPC: `TunnelRefresh` bekommt ein zusätzliches Feld für den Grund des
Stopps (Rust und `lib/bridge/types.ts` in derselben Task-Folge, T6 vor T7); bestehende Felder bleiben.

## Externe Integrationen

Keine neuen. Tauri-IPC serialisiert über serde wie im Bestand.

## Trade-offs & Alternativen

- R-0876: dieselbe Lesegrenze wie `ansible.rs` (deklarierte Länge, dann stückweise); ein gemeinsamer Helfer nur,
  wenn er beide Stellen ohne Umbau trägt.
- R-0930: eine Generation in `http_client.rs`, die `invalidate_client_cache` erhöht; `client_for` legt nur ab, wenn
  sie sich seit dem Start nicht geändert hat. Keine Änderung an `enrollment.rs` (Überlappung).
- R-0948: der Grund als eigenes Feld statt eines neuen `RefreshOutcome`-Werts, damit bestehende Vergleiche auf
  `stopped` gleich bleiben.

## Risiken & Rollback

Jede Task ein Commit, einzeln zurücknehmbar. Client-Cache, TOFU und RDP-Start berühren Vertrauens- und
Geheimnispfade; `security` prüft T1–T4.

## Doku-Impact

Tunnel-Hinweis bei verweigertem Zugriff in `docs/admin/frp-tunnel.html` + EN. CHANGELOG über
`changelog.d/kern-desktop-1.md`. Übrige Tasks ohne dokumentiertes Verhalten.

## Offene Fragen

Keine.
