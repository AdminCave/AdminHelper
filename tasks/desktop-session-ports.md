<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Session im Rust-Speicher und eigene lokale Visitor-Ports — Task-Ledger
Status: aktiv · Branch: feature/desktop-session-ports · Review: pro Task
Spec: docs/features/desktop-session-ports.md (Roadmap R-0430)
Heavy: linux-full + scenario --agents 1 --tunnel --desktop + windows — Desktop-Auth und -Tunnel (CLAUDE.md §5): Login, Erneuerung, SSE und die Tunnel-Specs laufen im Sammellauf; `scenario`, weil der Desktop die lokalen Visitor-Ports umschreibt (FRP-Datenpfad); `windows` für Sidecar, Datei-Sperre und Keyring-Aufräumen
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16 (`/feature-plan` auf R-0430, nach dem Spike): ein Vorhaben mit zwei Blöcken (A Session, B Ports); der Workspace-Namensraum gehört zu R-0431; Ports nur im Desktop, ohne Server-Änderung. Gebaut wird nach den Merges von R-0402 (desktop-tunnel-refresh) und R-0429 (desktop-pre-workspaces): Zeilen gelten für `edfab4a0` und werden beim Baustart neu gegreppt; T5 nutzt `logoutAndReload` aus R-0429 T1. Risikopfade Auth, PKI-Client, FRP: `security`-Prüfer bei T1–T4 und T7–T10.

## Block A — Session im Rust-Speicher

### T1 — Session-Zustand und ein Erneuerungsweg (single-flight)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/session.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/error.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @1075bd2c 2026-10-19T07:25:09+02:00
Review: approve (.ah-out/review/desktop-session-ports/T1.verdict.json)
Änderung: Neues Modul `session.rs` (SPDX-Header): verwalteter Zustand `SessionState` (async-Sperre um `Option<Session>`; `Session{server_url, access, refresh, username, is_admin, generation}`) und `authed_send`, das eine Anfrage mit dem aktuellen Access-Token schickt und bei 401 genau einmal erneuert: Unter der Sperre wird nur erneuert, wenn die Generation noch die gesehene ist, sonst nur wiederholt; die Erneuerung selbst ist eine übergebene Funktion (später `auth::try_refresh`, `auth.rs:132`). Scheitert sie, ist die Session leer und das Ergebnis ein eigener Fehler `SessionExpired`. In `main.rs` (`:74-76`) registriert, noch ohne Aufrufer. `tokio`-Feature `sync` ausdrücklich in `Cargo.toml` (`:21`; heute nur über Tauri vorhanden). Tests mit dem lokalen Testserver wie in `auth.rs` (`serve_one` `:373`): zwei gleichzeitige 401 → eine Erneuerung, beide Wiederholungen mit dem neuen Token; Erneuerung scheitert → Session leer, `SessionExpired`; ohne Session → Fehler ohne Netzzugriff.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session::
Doku: keine (intern, noch ohne Aufrufer)

### T2 — Login, Abmelden und GET-Pfade nutzen den Session-Zustand; Keyring-Tokens weg  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/session.rs, apps/desktop/src-tauri/src/error.rs, apps/desktop/src-tauri/src/proxy.rs, apps/desktop/src-tauri/src/notifications.rs, apps/desktop/src-tauri/src/enrollment.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @a52d2eeb 2026-10-19T08:00:25+02:00
Review: approve (.ah-out/review/desktop-session-ports/T2.verdict.json)
Änderung: `login` (`auth.rs:61`) schreibt in `SessionState` statt in den Keyring (`save_session_to_keyring` `:267` entfällt) und behält bis T5 die IPC-Form von `AuthSession` (`models.rs:143`); die Tokens fallen erst in T5 zusammen mit `types.ts` weg, sonst wäre `types.parity.test.ts` dazwischen rot. `authenticated_get` (`:161`) läuft über `authed_send`; `current_access_token` (`:261`, R-0402 T5) und `load_session_from_keyring` (`:274`) entfallen. `stored_server_url` (`:253`) liest den Zustand. `logout` (`:214`) meldet am Server ab und leert den Zustand. Der Start löscht `auth|jwt`, `auth|refresh`, `auth|server_url` einmal (best effort, in `setup`, `main.rs:77-90`). Die Commands `fetch_connections_jwt` (`commands.rs:297`), `fetch_tunnels` (`:371`), `start_tunnel` (`:308`) und `refresh_tunnel` (`:321`) nehmen kein `server_url`/`token`/`username` mehr (aus dem Zustand). Tests: Login füllt den Zustand; Abmelden leert ihn; der Start löscht alte `auth|*`-Einträge (`keyring_store::memory()`); ein GET an eine fremde URL bekommt kein Token (Ersatz für den T5-Test). Dazu in `session.rs` (Prüfer-Hinweise zu T1): `authed_send` prüft vor dem Setzen des Tokens selbst, dass die fertige Anfrage an die Origin der Session geht (`build_split`, `validation::same_server_destination`), sonst Fehler ohne Senden; die Erneuerung läuft unter einer Gesamtfrist (`tokio::time::timeout`), bei Ablauf wie bei einem Fehler: Session leer, `SessionExpired`; `Renewed` braucht nur das Token-Paar (ein scheiterndes `/me` nach der Rotation darf die neuen Tokens nicht verwerfen); das `expect(dead_code)` auf Modulebene entfällt. Tests: Anfrage an eine fremde Origin → kein Token, nichts gesendet; Erneuerung über der Frist → `SessionExpired`, Session leer.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- auth::
Doku: keine (intern; Doku mit T5)
Abhängt von: T1
Test-Löschung: apps/desktop/src-tauri/src/auth.rs::the_keyring_access_token_wins_over_the_passed_one — Keyring-Session entfällt, ersetzt durch die Tests am Session-Zustand (T1, T2); apps/desktop/src-tauri/src/auth.rs::without_a_session_the_passed_access_token_is_used — es gibt kein übergebenes Token mehr; apps/desktop/src-tauri/src/auth.rs::authenticated_get_sends_the_keyring_access_token — ersetzt durch „GET nimmt das Token aus dem Zustand“; apps/desktop/src-tauri/src/auth.rs::authenticated_get_sends_no_access_token_off_the_logged_in_server — gleichwertig ersetzt mit Zustand statt Keyring

### T3 — api_proxy erneuert und meldet das Ende der Session  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/proxy.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/session.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/main.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f5f00ac3 2026-10-19T08:17:50+02:00
Review: approve (.ah-out/review/desktop-session-ports/T3.verdict.json)
Änderung: `api_proxy` (`commands.rs:148`) nimmt nur noch `method`, `path`, `body`; `proxy::forward` (`:37-91`) baut die URL aus `session.server_url + path` (`validate_proxy_path`, `validation.rs:151`, bleibt; `require_pinned_destination` `:176` bekommt die Session-URL) und schickt über `authed_send`, erneuert also bei 401. Ohne Session: der bekannte Fehler „Keine aktive Sitzung“ (`validation.rs:184`). Endet die Session (`SessionExpired`), sendet Rust das Event `session-expired`. Tests: 401 → Erneuerung → Wiederholung erfolgreich; Erneuerung scheitert → Fehler und Event-Aufruf (über eine austauschbare Senke); Pfad-Injection weiter abgewiesen. Dazu (Prüfer-Hinweise zu T1/T2): `#[expect(clippy::too_many_arguments)]` an `api_proxy` entfällt; der Text „Keine aktive Sitzung — Anfrage abgelehnt“ hat nur noch eine Quelle (heute in `session.rs` und `validation.rs`); der Kommentar in `validation.rs` beim Pfad-Pin nennt `authed_send` statt `authenticated_get`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- proxy::
Doku: keine (intern; Doku mit T5)
Abhängt von: T2

### T4 — SSE und Token-Ausgabe aus dem Zustand  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/notifications.rs, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/session.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @b57228c8 2026-10-19T08:43:49+02:00
Review: approve (.ah-out/review/desktop-session-ports/T4.verdict.json)
Änderung: `start_notification_stream` (`commands.rs:354`) ohne `server_url`/`token`; der Stream (`notifications.rs:49`, `:80`, `:118`) holt vor jedem (Neu-)Verbinden das aktuelle Token aus dem Zustand und erneuert bei 401 über denselben Weg; scheitert das, `session-expired` statt `notification-stream-auth-failed` (`:104`, entfällt). `export_browser_p12` (`commands.rs:132`) und `mint_token` (`enrollment.rs:473`) nehmen Session-URL und Token aus dem Zustand (`:483-487`). Tests: der SSE-Verbindungsaufbau nimmt nach einer Erneuerung das neue Token (reine Funktion für Header-Bau und Entscheidung „neu verbinden / Session zu Ende“); `mint_token` ohne Session → „Keine aktive Sitzung“.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- notifications::
Doku: keine (intern; Doku mit T5)
Abhängt von: T3

### T14 — Die Zertifikatswahl gehört zur Session  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/session.rs, apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/proxy.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/notifications.rs, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/frpc.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @d6d0b77f 2026-10-19T09:09:19+02:00
Review: approve (.ah-out/review/desktop-session-ports/T14.verdict.json)
Änderung: `login` hält die Wahl „selbstsignierte Zertifikate erlauben“ in der `Session` fest; alle Wege über die Session (`authed_send`-Aufrufer, die Erneuerung über `try_refresh`, SSE, Token-Ausgabe) bauen ihren Client mit diesem Wert statt mit einem Wert je Aufruf aus der Webview. Die Commands dieser Wege nehmen den Parameter nicht mehr (die UI schickt ihn bis T5 weiter, Tauri ignoriert ihn). Eine Änderung der Einstellung wirkt ab der nächsten Anmeldung. Eingeschriebene Geräte (mTLS mit gepinnter CA) bleiben unverändert. Tests: Session mit `false` → die Erneuerung nimmt den Client ohne TOFU, auch wenn ein Aufruf `true` wollte; Session mit `true` → TOFU wie heute. Dazu (Prüfer-Hinweis zu T4): Der SSE-Stream vergleicht das `SignedIn`, das `authed_send` zurückgibt, mit der Session, mit der er startete, und endet bei Abweichung; Test dazu.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session::
Doku: keine (intern; Doku mit T5)
Abhängt von: T4

### T5 — UI ohne Tokens; abgelaufene Session führt zum Login  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/auth.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/api/request.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `AuthSession` in `types.ts` (`:59-65`) und in `models.rs` (`:143`) gleichzeitig nur noch `serverUrl`, `username`, `isAdmin`; Rust-Test in `auth.rs`: Login gibt keine Tokens aus (JSON genau `serverUrl`/`username`/`isAdmin`); die Bridge-Funktionen `apiProxy` (`:146`), `fetchConnectionsJwt` (`:164`), `startTunnel` (`:214`), `refreshTunnel` (`:222`), `fetchTunnels` (`:238`), `startNotificationStream` (`:261`), `exportBrowserP12` (`:128`) verlieren `serverUrl`/`token`; `apiRequest` (`request.ts:29-51`), `reloadForMode` (`connections.ts:105`), `activateNotifications` (`notifications.ts:102`), `startIfServerMode` bzw. der Takt aus R-0402 (`tunnel.ts`), `onExportBrowserCert` (`SettingsModal.svelte:247`) rufen ohne sie. AppShell hört auf `session-expired` und ruft `logoutAndReload` (R-0429 T1) mit der Statusmeldung „Sitzung abgelaufen – bitte neu anmelden“ (DE+EN in `dictionaries.ts`). Test-Fixtures mit `token`/`refreshToken` ziehen mit (api/{servers,connections,frp,ansible,provisioning,monitoring,notifications}.test.ts, request.test.ts, session.test.ts, stores/{connections.server,infra,notifications,tunnel}.test.ts, NotificationPrefs/ServerConnectionModal/TunnelModal/ProvisioningTab-Tests, SettingsModal.export.test.ts); das sind Anpassungen, keine Löschungen. Neuer Fall: `session-expired` führt zu `logoutAndReload`. Die Session-Commands verlieren in der Bridge auch `allowSelfSigned` (T14); der Kommentar zu `REQUEST_TIMEOUT_MS` (`request.ts:27`) rechnet Erneuerung (bis 30 s) und Wiederholung mit ein. Doku DE+EN: Server-Mode-Flow in `desktop.html` (`:133`, `:142-144`, Event-Zeile `:93`); der Token-Pin heißt dort `session::authed_send` statt `auth::stored_server_url` (`:134`); im TOFU-Abschnitt (T14): „Selbstsignierte Zertifikate erlauben“ wirkt ab der nächsten Anmeldung, und der Browser-Export nimmt die Wahl der Session (README und `desktop.html` hat doc-drift #218 neu gefasst: Stellen neu greppen) und `README.md` (`:99`, `:109`, `:465`); CHANGELOG Fixed (8-h-Abbruch, Abmelden durch gleichzeitige Erneuerung, verstummter Stream).
Verify: bash scripts/dev/verify.sh desktop-ui desktop-rs --strict
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html · README.md · CHANGELOG.md
Abhängt von: T14

### T6 — Live-E2E: Login, Seiten und Abmelden ohne Tokens in der Webview  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/logout.live.js
Änderung: `logout.live.js` ruft nach dem Login `invoke('api_proxy', {method:'GET', path:'/api/servers'})` ohne Token auf und bekommt Daten (die Session liegt in Rust), und nach dem Abmelden scheitert derselbe Aufruf mit „Keine aktive Sitzung“. Das Verify ist der Lint der Specs; der echte Beweis kommt aus dem Sammellauf.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T5

## Block B — eigene lokale Visitor-Ports

### T7 — Visitor-Ports und -Adressen im geprüften Wert umschreiben  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs
Änderung: Reine Funktion `remap_visitors(&mut toml::Value, ports: &dyn Fn(&str, u16) -> u16) -> Vec<VisitorBinding>`: setzt je `[[visitors]]` `bindAddr = "127.0.0.1"` und `bindPort` auf den gelieferten lokalen Port; `VisitorBinding{name, server_port, local_port}`. Server-`bindPort` außerhalb 1–65535 oder ein anderer `bindAddr` als `127.0.0.1` wird abgewiesen, falls R-0428 (T12 von R-0402) das nicht schon tut. Die Config für frpc entsteht aus dem Wert über den `toml`-Serializer statt aus dem Server-Text; die Identitätspfade (`rewrite_identity_paths` `:225`) setzt sie im Wert, sodass der Serializer escaped (behebt R-0425, falls beim Baustart noch offen; Offene Frage 2 der Spec). Tests: Ports und Adressen umgeschrieben, Namen und alle übrigen Schlüssel unverändert; ungültige Server-Werte abgewiesen; ein Windows-Pfad mit `\U` ergibt gültiges TOML.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- remap_visitors
Doku: keine (intern; Doku mit T11)

### T8 — Prozessübergreifende Portkarte mit Sperre  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/port_registry.rs, apps/desktop/src-tauri/src/main.rs
Änderung: Neues Modul `port_registry.rs` (SPDX-Header): `app_data_dir/port-registry.json` (0600), geschrieben unter `File::lock` auf eine Sperrdatei daneben, atomar (temp + rename wie `storage.rs`). `assign(owner, visitors: &[(name, server_port)]) -> Vec<(name, local_port)>`: vorhandener Eintrag (owner, name) bleibt ohne Bind-Test; sonst der Server-Port, wenn kein anderer Eintrag ihn hält und ein Bind-Test auf `127.0.0.1` gelingt; sonst der erste freie Port im Ausweichbereich 23000–23999 (Konstante; Offene Frage 1). Einträge des Besitzers, die nicht mehr übergeben werden, gehen. `owner` ist heute `default`. Tests mit Temp-Verzeichnis: klebrige Zuteilung; Server-Port frei → gleich; belegt (Test hält einen Listener) → Ausweichbereich; zwei Besitzer mit demselben Server-Port → verschiedene lokale Ports; zwei Handles nacheinander auf dieselbe Datei sehen sich; kaputte Datei → leer neu begonnen, mit Log.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- port_registry
Doku: keine (intern; Doku mit T11)

### T9 — Abgleich arbeitet mit der umgeschriebenen Fassung  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/ui/src/lib/bridge/types.ts
Änderung: `reconcile` (`frpc.rs:633`) ruft nach `validate_visitor_toml` (`:643`) die Portkarte und `remap_visitors`; `Applied` (`:62`) hält die umgeschriebene Fassung und die Zuordnungen, `plan_refresh` (`:398`) vergleicht Umgeschriebenes mit Umgeschriebenem, `Sidecar::write` (`:455`) bekommt den serialisierten Wert. `TunnelStatus` (`models.rs:155`, `types.ts`) liefert die Zuordnungen (`bindings: [{name, serverPort, localPort}]`; `types.parity.test.ts` zieht mit). Bestehende Tests mit Rohtext-Vergleich (`refresh_reloads_behind_the_running_head_and_keeps_the_process` `:1294`, `refresh_config_fills_in_the_identity_dir_behind_the_head` `:1530`) prüfen künftig die umgeschriebene Fassung. Neue Tests: Server-Port belegt → frpc bekommt den Ausweichport; zweiter Abgleich mit derselben Server-TOML → `Unchanged`, kein Reload (klebrig).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- refresh_
Doku: keine (intern; Doku mit T11)
Abhängt von: T7, T8

### T10 — Rust löst Tunnel-Ziele mit der Portkarte auf  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/commands.rs
Änderung: `resolve_connection` (`commands.rs:381`) nimmt die Zuordnungen des laufenden frpc aus `FrpcState`; die reine Funktion in `tunnel.rs` (`:55`) übersetzt (1) über `connection_id` und Admin-Mapping wie heute, der `visitor_port` wird dabei auf den lokalen Port abgebildet, (2) wörtlich: Host `127.0.0.1`/`localhost` und Port gleich einem Server-Port der Zuordnungen → lokaler Port (und `url` bei Web wie heute). Ohne laufenden Tunnel bleibt die Verbindung unverändert. Die neun bestehenden Tests in `tunnel.rs` bleiben gültig (lokal = Server-Port); neue Tests: Mapping-Pfad mit abweichendem lokalen Port; wörtlicher Pfad ohne Mapping (Nicht-Admin); Port nicht in der Karte → unverändert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tunnel::
Doku: keine (intern; Doku mit T11)
Abhängt von: T9

### T11 — Connect-Flow löst immer auf; Doku zu lokalen Ports  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Änderung: `performConnect` (`connectFlow.ts:209-218`) ruft `resolveConnection` auch ohne Admin-Mappings (heute nur bei `mappings.length > 0`), damit Nicht-Admins die wörtliche Auflösung bekommen. Neuer Vitest-Fall: leere Mappings → `resolve_connection` wird trotzdem gerufen und sein Ergebnis geöffnet. Doku DE+EN: `frp-tunnel.html` (`:95`, `:105`, `:114`: der Server-Visitor-Port ist der Wunschport, bei Belegung weicht der Desktop in 23000–23999 aus; Fehlersuche über die Tunnel-Anzeige), `desktop.html` (`:145`, `:147`, `:155`: Umschreiben nach der Prüfung, Auflösung in Rust). CHANGELOG Fixed (Tunnel-Ziele für Nicht-Admins), Changed (lokale Ports).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html · docs/developer/desktop.html + docs/en/developer/desktop.html · CHANGELOG.md
Abhängt von: T10

### T12 — Live-E2E: belegter Visitor-Port, Tunnel verbindet trotzdem  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/tunnel-connect.live.js
Änderung: Vor dem Login belegt der Spec den Visitor-Port eines geseedeten STCP-Tunnels auf `127.0.0.1` mit einem `node:net`-Listener (Port über `adminToken()`, `live.js:129-160`, und `GET /api/frp/tunnels`). Nach dem Login zeigt `invoke('tunnel_status')` für diesen Visitor einen anderen lokalen Port, `invoke('resolve_connection', …)` liefert ihn für die verknüpfte Verbindung, und eine TCP-Verbindung aus Node auf diesen Port wird angenommen (frpc lauscht). `scripts/` bleibt unberührt. Das Verify ist der Lint der Specs; der echte Beweis kommt aus dem Sammellauf (`desktop_e2e_connect_tunnel.sh`).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T10

### T13 — Gespeichertes Passwort nur für die Auflösung über die Portkarte  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/mod.rs
Änderung: `open_connection_stored` nimmt eine gesetzte `credential_connection` nur an, wenn `connection` in Host und Port genau deren Auflösung über die Zuordnungen des laufenden frpc ist (dieselbe reine Funktion wie `resolve_connection` aus T10), oder ohne laufenden Tunnel ihr gleicht. Die Prüfung aus R-0429 T9 (`check_credential_connection`: gleiche `id`, `kind`, `username`, `domain`) bleibt davor; die heutige Loopback-Regel wird durch den Vergleich mit der Auflösung ersetzt. Sonst `AppError::Validation`, bevor ein Passwort geladen wird. Die Entscheidung ist eine reine Funktion mit den Zuordnungen als Eingabe. cargo-Tests `stored_password_key_*` (zuerst rot): Auflösung über das Mapping und wörtlich → erlaubt; ein Loopback-Port, der nicht der Auflösung entspricht → abgewiesen; ohne laufenden Tunnel nur dieselbe Verbindung.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- stored_password_key
Doku: keine (intern)
Abhängt von: T10
