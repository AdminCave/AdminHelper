<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Session im Rust-Speicher und eigene lokale Visitor-Ports

Roadmap R-0430 (REF) · Phase 1 des Workspace-Konzepts (Kevin 2026-10-16, Ansatz „ein Prozess je Workspace“, durch
den Spike auf der Desktop-VM bestätigt). Zeilenangaben für den Desktop gelten für `edfab4a0`
(feature/desktop-tunnel-refresh, R-0402, noch nicht auf `main`), für den Server für `main`. Gebaut wird nach den
Merges von R-0402 und R-0429; die Bau-Session greppt die Zeilen dann neu.

## Problem / Motivation

**Session.** Der Desktop legt Access-Token, Refresh-Token und Server-URL im OS-Keyring ab (`auth.rs:11-13`,
`save_session_to_keyring` `:267`) und gibt beide Tokens an die Webview (`AuthSession`, `models.rs:143-151`,
`types.ts:59-65`); die UI schickt `serverUrl` und `token` mit fast jedem Command zurück. Daraus folgen heutige Fehler:
- `api_proxy` (`proxy.rs:37-91`) erneuert bei 401 nie. Nach acht Stunden (`ACCESS_TOKEN_EXPIRE_MINUTES=480`)
  scheitert jede Seite, die über `apiRequest` lädt.
- Erneuert wird nur in `authenticated_get` (`auth.rs:161-212`), und nicht single-flight. Treffen 401 aus Sync,
  Tunnel und Mappings zusammen, erneuern sie mit demselben Refresh-Token; die Reuse-Erkennung des Servers
  (`auth_router.py:194-211`) widerruft dann die ganze Token-Familie und meldet den Benutzer überall ab.
- Der Benachrichtigungs-Stream behält das Token vom Login (`notifications.rs:80`, `:133`); nach dessen Ablauf meldet
  er `notification-stream-auth-failed` (`:104`), worauf niemand hört.
- Die Keyring-Session überlebt das Beenden: `stored_server_url` (`:253`) liefert bis zum nächsten Login die URL des
  vorigen Laufs, obwohl der Client bewusst keine Session wiederherstellt (`desktop.html:143`).
- Für die Workspaces (R-0431, ein Prozess je Workspace) teilen sich mehrere Prozesse sonst `auth|jwt` & Co.

**Ports.** Jede Installation vergibt Visitor-Ports aus 6000–6999 (`_helpers.py:62`, `config.py:76-77`), der Desktop
bindet sie unverändert auf `127.0.0.1` (`config_generator.py:258-259`). Zwei Workspaces derselben oder zweier
Installationen kollidieren damit sicher, ebenso ein lokaler Dienst auf demselben Port. frpc meldet einen belegten
Port nur im Log und versucht es alle 10 s erneut; ein Reload meldet trotzdem Erfolg. Außerdem löst der Desktop
Tunnel-Ziele nur über `/api/frp/tunnels` auf (`tunnel.rs:36-52`), das nur Admins lesen dürfen
(`tunnel_router.py:25-38`); Nicht-Admins bekommen keine Auflösung (`tunnel.ts:47-51`).

## Ziel & Nicht-Ziele

**Ziel, Block A (Session):**
- Die Session lebt nur im Rust-Prozess (verwalteter Zustand); kein Token im Keyring, keines über IPC. Die UI kennt
  nur `serverUrl`, `username`, `isAdmin`.
- Ein gemeinsamer Weg für alle authentifizierten Anfragen (`api_proxy`, Verbindungen, Mappings, Visitor-Bundle,
  Token-Ausgabe, SSE): bei 401 genau eine Erneuerung zur Zeit; wer danach kommt, nimmt das neue Token.
- Scheitert die Erneuerung, ist die Session weg, und die App zeigt den Login-Screen mit dem Hinweis „Sitzung
  abgelaufen“ (Event `session-expired`, Abmelden über `logoutAndReload` aus R-0429).
- Alte `auth|*`-Einträge löscht der Start einmal (best effort).

**Ziel, Block B (Ports):**
- Nach der Prüfung der Visitor-TOML setzt Rust je Visitor `bindAddr = 127.0.0.1` und einen lokalen Port aus einer
  prozessübergreifenden Portkarte (Datei mit Sperre). Standard: lokal = Server-Port, wenn frei; sonst ein Port aus
  einem Ausweichbereich. Einmal vergeben bleibt die Zuordnung, solange der Visitor im Bundle steht.
- Rust löst Verbindungen mit dieser Karte auf: über `connection_id` (Admin-Mappings, wie heute) und wörtlich
  (`127.0.0.1`/`localhost` und ein Server-Port der Karte → lokaler Port). Damit gehen die Auto-Verbindungen auch für
  Nicht-Admins.
- Ein gespeichertes Passwort öffnet nur die Auflösung derselben Verbindung über diese Karte (T13, Folge aus R-0429 T9).

**Nicht-Ziele (Kevin 2026-10-16):**
- Kein Workspace-Namensraum (Datenordner, Keyring-Präfix je Prozess); der kommt mit R-0431.
- Keine Server-Änderung. Das Visitor-Bundle bleibt `{toml, pki}`; Tunnel- und Verbindungs-IDs kommen nicht dazu.
  Lücke: Ein Nicht-Admin mit einer vom Admin verknüpften (nicht automatisch angelegten) Verbindung wird nicht
  aufgelöst. Nach einem `PUT` auf den Visitor-Port passt der Server die Auto-Verbindung nicht an (`_helpers.py`,
  `tunnel_router.py:236`); die wörtliche Auflösung sieht dann den alten Port (bestehender Server-Fehler).
- Kein Session-Restore über Neustarts (bleibt).
- Kein Auswerten der frpc-Logs auf `start error` je Visitor.

## Betroffene Komponenten & Dateien

- **desktop-rs:** neu `src/session.rs` (Zustand + `authed_send`), `auth.rs` (`login` `:61`, `try_refresh` `:132`,
  `authenticated_get` `:161`, `logout` `:214`, `stored_server_url` `:253`, `current_access_token` `:261`,
  Keyring-Helfer `:267-290`), `proxy.rs` (`forward` `:37-91`), `validation.rs` (`require_pinned_destination`
  `:176-187`, bleibt pur), `notifications.rs` (`start` `:49`, `run_loop` `:80`, `connect_and_read` `:118`),
  `enrollment.rs` (`mint_token` `:473`, `export_browser_p12` `:798`), `frpc.rs` (`fetch_visitor_bundle` `:176`,
  `Applied` `:62`, `rewrite_identity_paths` `:225`, `validate_visitor_toml` `:252`, `frpc_config` `:351`,
  `Sidecar` `:455`, `reconcile` `:633`, `refresh_tunnel` `:742`), neu `src/port_registry.rs`, `tunnel.rs`
  (`fetch_tunnels` `:36`, `resolve_connection` `:55`), `sync.rs` (`fetch_connections_jwt` `:45`), `commands.rs`
  (`api_proxy` `:148`, `export_browser_p12` `:132`, `login` `:279`, `logout` `:291`, `fetch_connections_jwt` `:297`,
  `start_tunnel` `:308`, `refresh_tunnel` `:321`, `start_notification_stream` `:354`, `fetch_tunnels` `:371`,
  `resolve_connection` `:381`), `models.rs` (`AuthSession` `:143`, `TunnelStatus` `:155`), `main.rs`
  (Zustände `:49-52`, `.manage` `:74-76`, `setup` `:77-90`), `Cargo.toml` (tokio `:21`).
- **desktop-ui:** `lib/bridge/index.ts` (`login` `:60`, `exportBrowserP12` `:128`, `apiProxy` `:146`,
  `fetchConnectionsJwt` `:164`, `startTunnel` `:214`, `refreshTunnel` `:222`, `fetchTunnels` `:238`,
  `startNotificationStream` `:261`), `lib/bridge/types.ts`, `lib/api/request.ts` (`:29-51`),
  `lib/stores/{session,connections,notifications,tunnel,connectFlow}.ts`, `components/SettingsModal.svelte`
  (`:247-253`), `components/AppShell.svelte` (Listener `:140-151`), dazu die Test-Fixtures mit `token` (Liste in T5).
- **desktop-e2e:** `apps/desktop/e2e/test/specs/tunnel-connect.live.js`.
- **Doku:** `docs/developer/desktop.html` + EN (`:93`, `:133`, `:142-147`, `:155`), `docs/admin/frp-tunnel.html`
  + EN (`:95`, `:105`, `:114`), `README.md` (`:99`, `:109`, `:465`), `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine Server-API, keine Alembic-Migration. Tauri-IPC (intern, Desktop-UI ↔ Rust):
- `login` liefert `{serverUrl, username, isAdmin}` ohne Tokens.
- `api_proxy`, `fetch_connections_jwt`, `start_tunnel`, `refresh_tunnel`, `fetch_tunnels`,
  `start_notification_stream`, `export_browser_p12` verlieren `serverUrl` und `token` (und `username`), die Command-
  Namen bleiben (`ipc.inventory.test.ts` unverändert).
- Neues Event `session-expired` (ohne Nutzlast); `notification-stream-auth-failed` entfällt.
- `TunnelStatus` bekommt die Zuordnung je Visitor (`name`, Server-Port, lokaler Port); `types.parity.test.ts` zieht
  mit.

Lokale Daten: `auth|jwt`, `auth|refresh`, `auth|server_url` im Keyring werden beim Start gelöscht (Tokens, die ohnehin
nie wieder gelesen werden). Neu `app_data_dir/port-registry.json` (0600) mit Sperrdatei; Einträge
`{owner, visitor, serverPort, localPort}`, `owner` heute fest `default` (R-0431 setzt die Workspace-Id).

## Externe Integrationen

- **frp v0.69.1** (Pins `ci.yml:24`, `release.yml:22`, `bootstrap_linux.sh:17`): `bindAddr` leer → `127.0.0.1`;
  `bindPort = 0` wird abgewiesen, `bindPort < 0` heißt kein Listener; doppelte Namen und Ports prüft frpc nicht; die
  Admin-API meldet keinen Bind-Status der Visitors (<https://gofrp.org/en/docs/reference/visitor/>, Quellcode
  v0.69.1, laut Erkundung; ein Satz zum Bind-Fehler im Log ist nicht verifiziert).
- **Rust std** `File::lock`/`try_lock` (stabil seit 1.89; CI baut mit `stable`).

## Trade-offs & Alternativen

- **Session im Prozess statt im Keyring (gewählt):** Es gibt kein Restore, der Keyring brachte nur Risiko (Tokens
  überleben Absturz und Beenden) und den gemeinsamen Schlüssel für mehrere Prozesse. Nur in der UI wäre kein
  vertrauenswürdiger Ziel-Pin mehr möglich.
- **Single-flight per Generationszähler:** Die Erneuerung läuft unter einer async-Sperre; wer nach einem 401 die
  Sperre bekommt und eine neuere Generation sieht, wiederholt nur. Einfacher als eine Warteschlange, und die
  Server-Rotation bleibt intakt.
- **Port-Remap im Client (gewählt, Kevin)** statt eigener Loopback-Adressen (macOS bindet ohne Root nur
  `127.0.0.1`) oder abgestimmter Server-Bereiche (unabhängige Installationen stimmen sich nicht ab).
- **Eine Registry-Datei für alle Prozesse:** Eindeutigkeit über Prozesse und Klebrigkeit je Besitzer in einem Ort;
  getrennte Dateien je Workspace bräuchten trotzdem eine gemeinsame Sperre.
- **Remap auf dem geparsten Wert, vor dem Vergleich:** `Applied` hält die umgeschriebene Fassung, `plan_refresh`
  vergleicht Gleiches mit Gleichem. Klebrige Zuteilung ohne erneuten Bind-Test für eigene Einträge verhindert, dass
  jeder 60-s-Takt den eigenen frpc-Bind als „belegt“ sieht und neu verteilt.

## Risiken & Rollback

- Großer Diff auf Risikopfaden (Auth, PKI-Client, FRP): `security`-Prüfer bei T1–T4 und T7–T10.
- Zwischen Bind-Test und frpc-Start kann ein anderer Prozess den Port nehmen (TOCTOU); frpc versucht es dann alle
  10 s erneut, die Anzeige zeigt den Tunnel trotzdem verbunden (wie heute).
- Eine Erneuerung, die scheitert, meldet jetzt sichtbar ab statt still zu scheitern. Gewollt, aber sichtbar.
- Rollback: Revert des Merges. Die gelöschten Keyring-Tokens braucht keine Version (seit dem Wegfall des Restores
  liest sie nur der laufende Prozess); `port-registry.json` ignoriert eine ältere Version.

## Doku-Impact

`docs/developer/desktop.html` DE+EN: Server-Mode-Flow (Session im Prozess, ein Erneuerungsweg, `session-expired`),
Tunnel-Auflösung und lokaler Port. `docs/admin/frp-tunnel.html` DE+EN: Visitor-Port ist der Wunschport, der Desktop
weicht bei Belegung aus. `README.md` (`:99`, `:109`, beide schon heute falsch). `CHANGELOG.md`: Fixed (8-h-Abbruch,
Abmelden durch gleichzeitige Erneuerung, verstummter Stream, Tunnel-Ziele für Nicht-Admins), Changed (lokale Ports).

## Offene Fragen

1. **Ausweichbereich:** 23000–23999 (unter den Ephemeral-Bereichen von Linux 32768–60999 und Windows 49152–65535,
   außerhalb des Server-Bereichs). Empfehlung: so, als Konstante.
2. **R-0425 (Windows: Identitätspfad ohne TOML-Escaping):** Ist die Zeile beim Baustart noch offen, setzt T7 die
   Identitätspfade im geparsten Wert, und der Serializer escaped sie; damit ist R-0425 mit erledigt. Empfehlung: ja.
3. **Sichtbares Abmelden bei gescheiterter Erneuerung** mit Hinweis „Sitzung abgelaufen“ statt stiller Fehler auf
   jeder Seite. Empfehlung: ja.
