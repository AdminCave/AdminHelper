<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: vier Fehler vor den Workspaces

Roadmap R-0429 (BUG) · Fund aus dem Workspace-Konzept vom 2026-10-16 (Code-Lesung auf main@af4498a7, von der
Session nachgeprüft); Entscheidungen Kevin 2026-10-16. Nichts davon ist zur Laufzeit gefahren; den Beweis liefert
je Fehler ein roter Test in der Task.

## Problem / Motivation

1. **Abmelden im Header lässt den Tunnel laufen.** Der Knopf (`AppShell.svelte:276`) ruft `logout()` aus
   `session.ts:114`. Das löscht die Keyring-Session und die Verbindungsliste, stoppt aber den Tunnel nicht; nur der
   Weg aus den Einstellungen (`serverLogout`, `settings.ts:148`) ruft `tunnelStore.stop()`. Auch der Abbau der
   AppShell (`onDestroy`, `AppShell.svelte:163`) stoppt ihn nicht. frpc des abgemeldeten Benutzers läuft also mit
   dessen Visitor-Secrets weiter. Außerdem leert keiner der beiden Wege die Stores `infra`, `monitoring` und
   `ansible`: Nach einem Login unter anderem Benutzer stehen dort bis zum nächsten Laden die Daten des vorigen.
   Das Ledger von desktop-tunnel-refresh (R-0402) geht davon aus, dass jede Abmeldung über `stop()` läuft.
2. **Speichern der Einstellungen löscht den gemerkten Benutzernamen.** `SettingsModal.onSave`
   (`SettingsModal.svelte:276-290`) baut `Settings` ohne `lastUsername`; Rust schreibt das Objekt ganz
   (`storage.rs:173`). Gewollt ist laut `docs/developer/desktop.html:143`: „Server-URL und Benutzername werden
   vorausgewählt, gespeichert in `settings.json` als `serverUrl`/`lastUsername`“.
3. **Gespeichertes RDP-Passwort wird bei Tunnelzielen nicht gefunden (Linux/macOS).** `handleRdpAuth` prüft und
   speichert unter der Verbindung, wie sie in der Liste steht (`connectFlow.ts:141`, `:152`). `performConnect` löst
   sie auf `127.0.0.1:<Visitor-Port>` auf (`:213`) und öffnet mit `openConnectionStored(resolved)` (`:225`, `:232`);
   Rust lädt das Passwort unter dem Schlüssel der aufgelösten Verbindung (`connection/mod.rs:76` →
   `password.rs:17`). Gewollt ist laut `desktop.html:153-156`: Tunnel auflösen, „Passwort wird aus dem Keyring
   geholt“.
4. **Sync gegen eine fremde URL scheitert auf einem registrierten Gerät.** `sync.rs:18` baut den Client mit
   `build_client`, und der nimmt nach der Registrierung für jede URL den mTLS-Client mit CA-Pin
   (`http_client.rs:50`, `:63`). Eine fremde Sync-URL scheitert dann mit `ERR_CA_PIN_MISMATCH`. Sync gegen den
   eigenen Server ist gewollt (`docs/admin/benutzer.html:126`: `?api_key=…` „für Sync-URLs“) und braucht unter
   `MTLS_ENFORCE` die Identität; dieser Fall funktioniert heute und muss bleiben. Ein Leck des Zertifikats an Dritte
   gibt es nicht: Scheitert der CA-Pin, bricht der Handshake ab, bevor der Client sein Zertifikat schickt.
   `desktop.html:130` beschreibt das heutige Verhalten („läuft jeder Request über `enrolled_client`“); die Doku
   ändert sich mit.

## Ziel & Nicht-Ziele

**Ziel:**
- Jedes Abmelden (Header-Knopf, Einstellungen) stoppt den Tunnel, beendet die Session und lädt das Fenster neu;
  danach zeigt der Login-Screen leere Stores. Der erzwungene Logout bei geänderter Server-URL
  (`settings.ts:86-91`) lädt nach dem Speichern ebenfalls neu.
- Speichern der Einstellungen behält jedes Feld, das der Dialog nicht bearbeitet (heute `lastUsername`).
- Rust lädt ein gespeichertes RDP-Passwort unter der Verbindung **vor** der Tunnel-Auflösung, also unter
  demselben Schlüssel, unter dem `handleRdpAuth` prüft und speichert.
- Sync nimmt die Geräte-Identität nur, wenn die Sync-URL dieselbe Origin (Schema, Host, Port) hat wie die
  gespeicherte `serverUrl`; sonst denselben Client wie ein unregistriertes Gerät (TOFU oder öffentliche CA).

**Nicht-Ziele (Kevin 2026-10-16):**
- RDP unter Windows für Tunnelziele: mstsc sucht `TERMSRV/<gewählte Adresse>` = `127.0.0.1:<Port>`, gespeichert
  ist `TERMSRV/<Host>`. Die Lösung (TERMSRV kurz vor dem Start schreiben, nach einem Spike auf der Windows-VM)
  gehört zum Workspace-Konzept (R-0431). Der Windows-Pfad bleibt unverändert (`connection/mod.rs:73-79`).
- Kein Neuladen beim Moduswechsel weg von `server` (`settings.ts:114-138`); den Moduswechsel ersetzen später die
  Workspaces.
- Keine Reset-Funktionen je Store; das Neuladen ersetzt sie.
- Login, Token-Refresh und Tunnel behalten ihren mTLS-Pfad; nur der Sync-Abruf wählt neu.

## Betroffene Komponenten & Dateien

- **desktop-ui:** `lib/stores/settings.ts` (`saveSettings` `:76`, URL-Wechsel `:86-91`, `serverLogout` `:148`),
  `lib/stores/settings.test.ts`, `components/AppShell.svelte` (`:276`), `components/SettingsModal.svelte`
  (`onSave` `:276`, `onLogout` `:294`), neuer Test `components/SettingsModal.save.test.ts`, ein kleiner Helfer zum
  Neuladen (testbar statt `window.location.reload()` direkt), `lib/stores/connectFlow.ts` (`:225`, `:232`),
  `lib/stores/connectFlow.test.ts`, `lib/bridge/index.ts` (`openConnectionStored` `:182`).
- **desktop-rs:** `commands.rs` (`open_connection_stored` `:241`, `sync_connections` `:177`),
  `connection/mod.rs` (`open_connection_stored` `:39`, `open_rdp_with_stored_password` `:64`), `sync.rs` (`:18`),
  `http_client.rs` (`build_client` `:40`).
- **desktop-e2e:** `apps/desktop/e2e/test/specs/tunnel-start.live.js`.
- **Doku:** `docs/developer/desktop.html` + `docs/en/developer/desktop.html` (`:130`, `:156`), `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine Server-API, keine Migration, kein neues Feld in `settings.json`.

Tauri-IPC: `open_connection_stored` nimmt zusätzlich optional `credentialConnection`; fehlt es, gilt wie heute
die übergebene Verbindung. Der Command-Name bleibt (`ipc.inventory.test.ts` unverändert). `sync_connections`
behält seine Signatur und liest `serverUrl` selbst aus `settings.json`, so wie heute schon `allowSelfSignedCerts`
(`commands.rs:29`).

## Externe Integrationen

Keine. Das Neuladen ist `window.location.reload()` im Webview. Dass die WebDriver-Session das Neuladen übersteht,
ist nicht verifiziert; T6 zeigt es im Sammellauf.

## Trade-offs & Alternativen

- **Neuladen statt Stores leeren (Kevin):** Alle Stores sind garantiert leer, auch künftige; dasselbe Muster
  braucht später der Workspace-Wechsel. Sichtbar ist ein kurzer Neuaufbau.
- **Ein Abmelde-Weg in `settings.ts`:** Die Datei importiert Session und Tunnel schon. `session.ts` importiert den
  Tunnel-Store nicht, weil `tunnel.ts` die Session importiert; Zyklen umgeht der Code bisher mit
  `registerConnectionsSync` (`main.ts:16`).
- **RDP-Schlüssel:** optionaler Parameter (gewählt) statt Auflösung in Rust oder Speichern unter dem aufgelösten
  Schlüssel. Der aufgelöste Schlüssel wechselt mit dem Visitor-Port und kollidiert zwischen Installationen.
- **Sync-Identität (Kevin):** Origin-Vergleich (gewählt). Erneuter Versuch ohne Identität nach einem Pin-Fehler
  fiele bei einem MITM auf den eigenen Server auf öffentliches Vertrauen zurück; nie mit Identität bräche Sync
  gegen den eigenen Server unter `MTLS_ENFORCE`. Grenzfall: Ein Alias-Hostname des eigenen Servers bekommt keine
  Identität; dort hilft derselbe Hostname wie in der Server-URL.

## Risiken & Rollback

- Scheitert der Tunnel-Stopp beim Abmelden, laufen Abmelden und Neuladen trotzdem (wie heute in `serverLogout`);
  frpc kann dann weiterlaufen. Der Normalfall ist durch T6 belegt.
- Der Origin-Vergleich ist reine Logik mit Tests für Standard-Port, Groß-/Kleinschreibung, Schrägstrich am Ende,
  Pfad und Query.
- Rollback: Revert des Merges; keine Daten ändern sich.

## Doku-Impact

`desktop.html` DE+EN: der Connect-Flow (`:156`) nennt den Schlüssel vor der Tunnel-Auflösung, der Absatz zum
registrierten Zustand (`:130`) die Ausnahme für Sync gegen eine andere Origin. `CHANGELOG.md` je Fehler eine
Zeile unter Fixed.

## Offene Fragen

- **Bauen erst nach R-0402:** desktop-tunnel-refresh ändert `commands.rs`, `bridge/index.ts`, `desktop.html`,
  `CHANGELOG.md` und `tunnel-start.live.js`, und T1 verlässt sich darauf, dass `stop()` den 60-s-Takt von R-0402
  beendet. Empfehlung: seriell nach dessen Merge.
- **Heavy:** `linux-full` (Sammellauf mit `tunnel-start.live.js`) und `windows` (Rust-Änderungen), kein
  `scenario`: FRP-Datenpfad, Visitor-TOML sowie die mTLS-Pfade von Login und Tunnel bleiben unberührt.
