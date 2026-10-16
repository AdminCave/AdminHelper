<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: vier Fehler vor den Workspaces — Task-Ledger
Status: geplant · Branch: feature/desktop-pre-workspaces · Review: pro Task
Spec: docs/features/desktop-pre-workspaces.md (Roadmap R-0429)
Heavy: linux-full + windows — Desktop-Journey Abmelden mit laufendem Tunnel (`tunnel-start.live.js` im Sammellauf über `desktop_e2e_tunnel.sh`); `windows` für die Rust-Änderungen an `open_connection_stored` und am Sync-Client; kein `scenario`, weil FRP-Datenpfad, Visitor-TOML und die mTLS-Pfade von Login und Tunnel unberührt bleiben
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16 (`/feature-plan` auf R-0429): voller Weg mit Spec statt Kurz-Ledger (fünf Tasks plus Live-Beweis); Abmelden lädt das Fenster neu, statt Stores einzeln zu leeren; Sync nimmt die Geräte-Identität nur für die Origin der gespeicherten `serverUrl`; RDP-Passwörter für Tunnelziele unter Windows (mstsc, `TERMSRV`) bleiben außen vor und gehören zu R-0431. Gebaut wird erst nach dem Merge von R-0402 (desktop-tunnel-refresh): gemeinsame Dateien `commands.rs`, `bridge/index.ts`, `desktop.html`, `CHANGELOG.md`, `tunnel-start.live.js`, und T1 setzt voraus, dass `stop()` dessen 60-s-Takt beendet.

### T1 — Jedes Abmelden stoppt den Tunnel und lädt das Fenster neu  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/settings.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/lib/utils/reloadWindow.ts, CHANGELOG.md
Änderung: Neu `logoutAndReload()` in `settings.ts`: Tunnel stoppen (`tunnelStore.stop()`, Fehler ignoriert wie in `serverLogout`, `:148-153`), dann `logout()` aus `session.ts:114` (Keyring-Session und Verbindungsliste, unverändert), danach Neuladen des Fensters, auch wenn das Abmelden am Server scheitert. Das Neuladen kapselt der neue Helfer `lib/utils/reloadWindow.ts` (SPDX-Header; ruft `window.location.reload()`, damit Tests ihn mocken). Der Header-Knopf (`AppShell.svelte:276`) und `SettingsModal.onLogout` (`:294`, heute `serverLogout`) rufen `logoutAndReload()`. `serverLogout` bleibt für den erzwungenen Logout bei geänderter Server-URL (`settings.ts:86-91`); dieser Weg lädt nach erfolgreichem Speichern neu. Neue Vitest-Fälle in `settings.test.ts` (zuerst rot): `logoutAndReload` ruft `bridge.stopTunnel` vor `bridge.logout` und danach den Helfer; ein scheiternder Tunnel-Stopp oder ein scheiterndes `bridge.logout` verhindert das Neuladen nicht; Speichern mit geänderter Server-URL bei laufender Session lädt nach dem Speichern neu, ohne Session nicht. CHANGELOG Fixed: Abmelden im Header beendet jetzt auch den Tunnel und zeigt danach keine Daten des vorigen Benutzers mehr.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/settings.test.ts
Doku: CHANGELOG.md (Fixed); `docs/` beschreibt das Abmelden nicht
Beweis: main@af4498a7 · `sed -n 276p apps/desktop/ui/src/components/AppShell.svelte` → `onclick={() => logout()}` (Import aus `$lib/stores/session`, `:12`); `sed -n 114,127p apps/desktop/ui/src/lib/stores/session.ts` → `bridge.logout()`, `connectionsSync.clear()`, kein Tunnel-Stopp; `sed -n 163,175p apps/desktop/ui/src/components/AppShell.svelte` → `onDestroy` ohne Tunnel-Stopp
Orakel: mutation-sample — Entfernen des Tunnel-Stopps oder des Neuladens in `logoutAndReload` macht einen neuen Test rot
Dedup-Key: bug:desktop:AppShell.svelte:logout-keeps-tunnel
HEAD: af4498a7
Semantik: keine Stelle in docs/ — gesucht: Abmelden/Logout in `docs/developer/desktop.html`, `docs/admin/frp-tunnel.html` und `README.md`; Annahme im Ledger von R-0402 (T6): „jede Abmeldung und jeder Moduswechsel läuft über `stop()`“

### T2 — Speichern der Einstellungen behält den gemerkten Benutzernamen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.save.test.ts, CHANGELOG.md
Änderung: `onSave` (`SettingsModal.svelte:276`) baut `next` auf den aktuellen Einstellungen auf (`{ ...$settings, … }` oder gleichwertig), sodass jedes Feld, das der Dialog nicht bearbeitet, erhalten bleibt; heute geht `lastUsername` verloren. Neue Testdatei `SettingsModal.save.test.ts` (SPDX-Header, zuerst rot): Einstellungen mit `lastUsername: 'kevin'` laden, Dialog öffnen, Sprache ändern, speichern → `bridge.saveSettings` bekommt `lastUsername: 'kevin'` und die neue Sprache. CHANGELOG Fixed.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.save.test.ts
Doku: CHANGELOG.md (Fixed)
Beweis: main@af4498a7 · `sed -n 276,290p apps/desktop/ui/src/components/SettingsModal.svelte` → `next` ohne `lastUsername`; `sed -n 173,176p apps/desktop/src-tauri/src/storage.rs` → `save_settings` schreibt das Objekt ohne Abgleich
Orakel: mutation-sample — `next` wieder ohne die bisherigen Einstellungen → der neue Test wird rot
Dedup-Key: bug:desktop:SettingsModal.svelte:save-drops-lastusername
HEAD: af4498a7
Semantik: docs/developer/desktop.html:143 — „Server-URL und Benutzername werden vorausgewählt, gespeichert in <code>settings.json</code> als <code>serverUrl</code>/<code>lastUsername</code>“

### T3 — open_connection_stored lädt das Passwort unter der Verbindung vor der Auflösung  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/mod.rs
Änderung: `open_connection_stored` (`commands.rs:241`) nimmt zusätzlich `credential_connection: Option<Connection>` (JS `credentialConnection`) und reicht es an `connection::open_connection_stored` (`connection/mod.rs:39`) weiter; ist es gesetzt, wird es wie die Verbindung an der Grenze geprüft (`validate_connection_input`). `open_rdp_with_stored_password` (`:64`) lädt unter Unix das Passwort unter dieser Verbindung statt unter der aufgelösten (`:76`); fehlt sie, gilt wie heute die übergebene. Dafür eine reine Funktion, die die Quelle des Schlüssels wählt. Neue cargo-Tests `stored_password_key_*` (zuerst rot): mit Credential-Verbindung ist der Schlüssel `rdp_storage_key` der logischen Verbindung, nicht der von `127.0.0.1:<Port>`; ohne bleibt er der der übergebenen. Windows unverändert (gibt kein Passwort weiter, `:77-78`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- stored_password_key
Doku: keine (intern; die Doku folgt mit T4)
Beweis: main@af4498a7 · `sed -n 74,77p apps/desktop/src-tauri/src/connection/mod.rs` → `load_password_keyring(connection)` mit der aufgelösten Verbindung; `sed -n 17,32p apps/desktop/src-tauri/src/password.rs` → Schlüssel aus `host` und `port`
Orakel: mutation-sample — die Wahl wieder auf die aufgelöste Verbindung → ein neuer Test wird rot
Dedup-Key: bug:desktop:connectFlow.ts:stored-password-resolved-key
HEAD: af4498a7
Semantik: docs/developer/desktop.html:153-156 — „Rust-Backend resolved den FRP-Tunnel (lokaler Visitor-Port)“, danach „Passwort wird aus dem Keyring geholt oder via <code>PasswordPrompt</code>-Modal abgefragt“

### T4 — Connect-Flow übergibt die Verbindung vor der Auflösung  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Änderung: `openConnectionStored` (`bridge/index.ts:182`) nimmt optional `credentialConnection` und gibt es an `invoke` weiter. `performConnect` (`connectFlow.ts:202`) übergibt an beiden Stellen (`:225`, `:232`) die unaufgelöste `connection` als `credentialConnection`. Neuer Vitest-Fall in `connectFlow.test.ts` (zuerst rot): Ein Mapping löst eine RDP-Verbindung auf `127.0.0.1:6000` auf, das Passwort ist gespeichert → `open_connection_stored` bekommt die aufgelöste Verbindung als `connection` und die ursprüngliche als `credentialConnection`. Doku DE+EN: der Connect-Flow (`desktop.html:156`) sagt, dass das Passwort unter der Verbindung vor der Tunnel-Auflösung im Keyring steht (unter Windows liest mstsc `TERMSRV` selbst, für Tunnelziele noch ohne gespeichertes Passwort). CHANGELOG Fixed (Linux/macOS).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:156`) · CHANGELOG.md
Abhängt von: T3
Beweis: main@af4498a7 · `sed -n 141p;152p;225p;232p apps/desktop/ui/src/lib/stores/connectFlow.ts` → Prüfen und Speichern mit `connection`, Öffnen mit `resolved`
Orakel: mutation-sample — `credentialConnection` nicht mehr übergeben → der neue Test wird rot
Dedup-Key: bug:desktop:connectFlow.ts:stored-password-resolved-key
HEAD: af4498a7
Semantik: docs/developer/desktop.html:153-156 (wie T3)

### T5 — Sync nimmt die Geräte-Identität nur für die eigene Server-Origin  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/http_client.rs, apps/desktop/src-tauri/src/commands.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Änderung: `sync_connections` (`commands.rs:177`) liest neben `allowSelfSignedCerts` auch `serverUrl` aus den Einstellungen und gibt sie an `sync::sync_connections` (`sync.rs:10`) weiter. Eine reine Funktion `sync_uses_identity(sync_url, server_url)` vergleicht die Origins (Schema, Host ohne Groß-/Kleinschreibung, Port mit Standard-Port wie `tofu::pin_identity`, `tofu.rs:55`; Pfad und Query zählen nicht); nur bei Gleichheit baut Sync den Client wie heute über `build_client`, sonst über eine Variante in `http_client.rs` ohne Geräte-Identität (TOFU bei erlaubten selbstsignierten Zertifikaten, sonst öffentliche CA). Der Client-Cache (`http_client.rs:52`) trägt die Wahl im Schlüssel. Neue cargo-Tests `sync_identity_*` (zuerst rot): gleiche Origin auch mit Standard-Port, anderer Schreibweise und Schrägstrich am Ende → mit Identität; anderer Host, Port oder Schema → ohne; keine `serverUrl` → ohne. Doku DE+EN: der Absatz zum registrierten Zustand (`desktop.html:130`, „läuft jeder Request über <code>enrolled_client</code>“) nennt die Ausnahme. CHANGELOG Fixed.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sync_identity
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:130`) · CHANGELOG.md
Beweis: main@af4498a7 · `sed -n 18p apps/desktop/src-tauri/src/sync.rs` → `build_client(&url, allow_self_signed)`; `sed -n 50,64p apps/desktop/src-tauri/src/http_client.rs` → registriert ⇒ `enrolled_client()` für jede URL
Orakel: mutation-sample — `sync_uses_identity` immer `true` → ein neuer Test wird rot
Dedup-Key: bug:desktop:sync.rs:sync-uses-device-identity
HEAD: af4498a7
Semantik: README.md:18 — „Sync mode: load connections from a remote HTTPS JSON“; docs/admin/benutzer.html:126 — „Der Fallback <code>?api_key=…</code> (für Sync-URLs)“ (Sync gegen den eigenen Server bleibt gewollt); docs/developer/desktop.html:130 beschreibt das heutige Verhalten und ändert sich auf Kevins Entscheidung (2026-10-16)

### T6 — Live-E2E: Abmelden im Header beendet den Tunnel, erneutes Anmelden verbindet wieder  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/tunnel-start.live.js
Änderung: Nach dem Schritt „logs in and the seeded tunnel auto-connects“ ein weiterer: Abmelde-Knopf im Header (`.content-header-right .btn.ghost.small`, wie `logout.live.js`) → `.login-card` erscheint → `invoke('tunnel_status')` liefert `running: false` → erneut `login()` → die Tunnel-Anzeige erreicht wieder `connected`. Auf dem Stand nach R-0402 (dessen T9 ändert dieselbe Spec); `scripts/` bleibt unberührt. Das Verify hier ist der Lint der E2E-Specs; der echte Beweis (Neuladen unter WebDriver, frpc wirklich beendet) kommt aus dem Sammellauf (`Heavy: linux-full`).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T1
