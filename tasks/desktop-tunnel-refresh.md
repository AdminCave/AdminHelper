<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Tunnel übernimmt Änderungen selbst — Task-Ledger
Status: aktiv · Branch: feature/desktop-tunnel-refresh · Review: pro Task
Spec: docs/features/desktop-tunnel-refresh.md (Roadmap R-0402, R-0389, R-0390)
Heavy: linux-full + scenario --agents 1 --tunnel --desktop + windows — Desktop-Tunnel (CLAUDE.md §5): `desktop_e2e_tunnel.sh` mit dem erweiterten `tunnel-start.live.js` im Sammellauf (`run.sh e2e`, beweist Reload ohne Neustart gegen echtes frps); `scenario` vor dem Merge, weil der Desktop-Tunnel den FRP-Datenpfad berührt (der GUI-Visitor selbst läuft dort nicht; Kevin 2026-10-16: reicht, der Desktop-Beweis ist T9; Multibox erlaubt); `windows` für Sidecar und lokale Admin-API auf 127.0.0.1 (Firewall-Abfrage nicht verifiziert)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: Desktop fragt alle 60 s ab; 404 von `visitor-bundle` heißt „keine Tunnel“ (kein neuer API-Vertrag); Reload für Visitors, Neustart für Common; Restrisiko Token-Rotation hingenommen; R-0389 und R-0390 vor dem automatischen Neustart; Knopf „Neu verbinden“ an der Tunnel-Anzeige, nur bei getrenntem Tunnel (T10, T11); `scenario` ohne GUI-Visitor reicht, der Desktop-Beweis ist T9.

### T1 — Ein Stopp macht das spätere Terminated alt (R-0389)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @d7b11995 2026-10-16T13:26:12+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T1.verdict.json)
Änderung: `stop_frpc` (`frpc.rs:323`) erhöht die Generation wie `start_frpc` (`:273`), über eine reine Methode an `FrpcProcess` (`:43`), damit das späte `Terminated` des gestoppten Prozesses als alte Generation gilt und `frpc-terminated` (`:303`) nicht mehr ans UI geht. Neuer cargo-Test `stop_makes_a_late_terminated_stale`: nach dem Stopp liefert `reconcile_terminated` (`:69`) für die vorige Generation `false`; der bestehende Test `reconcile_terminated_clears_state_only_for_the_current_generation` (`:449`) bleibt. Doku: im Abschnitt „Status & Events“ (`desktop.html:146`, DE+EN) ein Halbsatz, dass auch ein Stopp den alten Prozess verstummen lässt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- late_terminated
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:146`)
Beweis: main@b84b9495 · `sed -n 323,330p apps/desktop/src-tauri/src/frpc.rs` → `stop_frpc` ohne `generation += 1`; `tunnel.ts:64-69` setzt `idle`, `markTerminated` (`:72`) überschreibt ohne Zustandsprüfung
Orakel: mutation-sample — nach dem Fix macht das Entfernen der Erhöhung im Stopp den neuen Test rot
Dedup-Key: bug:desktop:tunnel.ts:stop-then-terminated
HEAD: b84b9495
Semantik: docs/developer/desktop.html:146 — „<code>frpc-terminated</code> meldet nur der laufende frpc-Prozess“

### T2 — frpc-error nur für die laufende Generation (R-0390)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @c2da85dd 2026-10-16T13:37:11+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T2.verdict.json)
Änderung: Der Log-Task sendet `frpc-error` (`frpc.rs:306-308`) nur, wenn sein Prozess noch die laufende Generation ist — dieselbe Prüfung wie für `Terminated` (`:289-305`), als reine Methode an `FrpcProcess`; ein vergifteter Lock meldet wie heute. Neuer cargo-Test `stale_error_is_not_announced_while_a_newer_frpc_runs`. Ob ein getöteter Sidecar überhaupt `CommandEvent::Error` liefert, bleibt unbelegt; die Prüfung ist davon unabhängig richtig.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- stale_error
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:146`, die Regel nennt jetzt beide Ereignisse)
Beweis: main@b84b9495 · `sed -n 306,309p apps/desktop/src-tauri/src/frpc.rs` → `CommandEvent::Error` ohne Generationsprüfung vor `emit("frpc-error", …)`
Orakel: mutation-sample — Bedingung entfernt → neuer Test rot
Dedup-Key: bug:desktop:frpc.rs:error-old-generation
HEAD: b84b9495
Semantik: docs/developer/desktop.html:146 (wie T1)

### T3 — Abgleich entscheiden: 404, Vergleich, lokaler Kopf  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @9be606ef 2026-10-16T13:50:18+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T3.verdict.json)
Änderung: Drei reine Bausteine, noch ohne Aufrufer im Ablauf: (a) `fetch_visitor_bundle` (`frpc.rs:90`) unterscheidet 404 („keine Tunnel“, beide Server-Fälle `generate_router.py:35` und `:150`) von jedem anderen Fehler; (b) eine Entscheidungsfunktion über die geparste Server-TOML (`toml::Value`): frpc läuft nicht → Start; Wurzeltabelle ohne `visitors` verschieden → Neustart; nur `visitors` verschieden → Reload; sonst unverändert; (c) der lokale Kopf (`loginFailExit = false`, `webServer.addr = "127.0.0.1"`, `webServer.port`, `webServer.user`, `webServer.password`), der **nach** `validate_visitor_toml` (`:151`) vor die Server-TOML gestellt wird. Tests mit dem Präfix `refresh_`: alle Entscheidungsfälle (Visitor neu, weg, Secret/Port geändert; Token, `serverAddr`, `serverPort`, `user`, `transport` geändert; gleiche TOML anders formatiert → unverändert), Kopf + Server-TOML parsen mit `loginFailExit = false` und gesetztem Passwort in der Wurzel, eine Server-TOML mit `webServer` oder `loginFailExit` wird weiter abgewiesen (Allow-List unverändert), 404 → „keine Tunnel“, 500 → Fehler.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- refresh_
Doku: keine (intern; der Ablauf kommt mit T4)
Beweis: main@b84b9495 · `sed -n 90,106p apps/desktop/src-tauri/src/frpc.rs` → jede Nicht-2xx-Antwort wird „Visitor-Bundle konnte nicht geladen werden“; `git grep -n loginFailExit apps/` → kein Treffer
Dedup-Key: bug:desktop:tunnel.ts:no-refresh-no-retry
HEAD: b84b9495
Semantik: docs/developer/desktop.html:145 — „<code>start_tunnel</code> lädt das <em>Visitor-Bundle</em> … und startet anschließend <code>frpc -c &lt;config&gt;</code> als Sidecar“ (nur einmal; das gewollte Verhalten steht in der Spec)

### T4 — Abgleich ausführen: refresh_tunnel mit Reload über die lokale Admin-API  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/models.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @29da0473 2026-10-16T14:31:28+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T4.verdict.json)
Änderung: `FrpcProcess` hält die zuletzt angewandte Server-TOML und Port/Benutzer/Passwort der Admin-API; ein neuer Command `refresh_tunnel` (`commands.rs` neben `:307`, registriert in `main.rs:103-104`) führt den Plan aus T3 aus, serialisiert über eine Async-Sperre: Start/Neustart mit neuem Kopf (Port per Bind auf `127.0.0.1:0`, 32 Zufallsbytes über `crate::tofu::ring_provider()`), Reload mit altem Kopf per `GET http://127.0.0.1:<port>/api/reload` (eigener reqwest-Client, `no_proxy`, Basic-Auth, Timeout 5 s; scheitert er → Neustart), 404 → Stopp mit Generation +1, jeder andere Fehler lässt den laufenden Prozess unangetastet. `start_tunnel` (`frpc.rs:344`, `commands.rs:307`) läuft über denselben Abgleich. `TunnelStatus` (`models.rs:155`) bekommt `visitors` (Namen der angewandten Visitors). Tests mit Präfix `refresh_`: Reload-Anfrage gegen einen lokalen tokio-Listener (Pfad `/api/reload`, `Authorization: Basic …`), Reload-Fehler führt zum Neustart-Zweig, `visitors` aus einer TOML. Doku: „Tunnel starten“ (`desktop.html:145`, DE+EN) beschreibt den Abgleich, Reload/Neustart und die lokale Admin-API.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- refresh_
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:145`)
Abhängt von: T1, T3
Beweis: main@b84b9495 · `sed -n 344,355p apps/desktop/src-tauri/src/frpc.rs` → Bundle einmal holen, schreiben, starten; kein zweiter Weg
Dedup-Key: bug:desktop:tunnel.ts:no-refresh-no-retry
HEAD: b84b9495

### T5 — Der Takt nimmt das aktuelle Access-Token aus dem Keyring  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/frpc.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5a2cf0bd 2026-10-16T14:56:34+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T5.verdict.json)
Änderung: Ein kleiner Leser in `auth.rs` liefert das Access-Token aus dem Keyring (`KEYRING_JWT_KEY`, `auth.rs:11`; `load_session_from_keyring` `:260`); `refresh_tunnel` verwendet es, wenn vorhanden, sonst das übergebene. Hintergrund: `authenticated_get` erneuert bei 401 (`auth.rs:183-203`) und speichert das neue Token nur im Keyring; ohne diesen Leser liefe nach acht Stunden jeder 60-s-Takt in einen Refresh mit Rotation. Test mit `keyring_store::memory()`: Keyring-Token gesetzt → es wird verwendet; leer → das übergebene. Risikopfad Auth: `security`-Prüfer.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- access_token
Doku: keine (intern)
Abhängt von: T4

### T6 — Tunnel-Store: Takt alle 60 s, Single-Flight, Leerlauf ohne Tunnel  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/lib/stores/tunnel.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @edfab4a0 2026-10-16T15:31:51+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T6.verdict.json)
Änderung: `refreshTunnel` in der Bridge (`index.ts` neben `:213`, Typen `types.ts:67`). `startIfServerMode` (`tunnel.ts:36`) wird zur Aktivierung: sofort ein Abgleich, dann alle 60 s, mit Generationszähler gegen überholte Aktivierungen wie `notifications.ts:100-132`; `stop()` (`:64`) beendet den Takt. Ein laufender Abgleich lässt den nächsten Takt aus; `refreshNow()` hängt sich an ihn an. Nach jedem Abgleich werden die Mappings neu geladen (Fehler → alte bleiben). `stopped` → „idle“, Mappings leer, keine Meldung; Fehler → Anzeige bleibt, eine Meldung je Fehlerserie. Die Aufrufer (`AppShell.svelte:134`, `SettingsModal.svelte:226`, `stores/settings.ts:113`) bleiben unverändert; jede Abmeldung und jeder Moduswechsel läuft über `stop()` (`settings.ts:117`, `:130`, `:150`). Vitest mit Fake-Timern: erster Abgleich sofort, nächster nach 60 s, kein Überlappen bei langsamem Abgleich, `stopped` ohne Meldung, Fehler ohne Abbau, `stop()` beendet den Takt, überholte Aktivierung räumt sich auf.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/tunnel.test.ts
Doku: keine (intern; sichtbare Doku in T8)
Abhängt von: T4

### T7 — Unerwartetes Ende: Neustart mit Backoff 5–60 s  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/lib/stores/tunnel.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @50c07562 2026-10-16T16:50:31+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T7.verdict.json)
Änderung: `markTerminated` (`tunnel.ts:72`) und `markError` (`:76`) setzen bei aktivem Takt „disconnected“ und planen einen Abgleich nach 5 s, dann 10, 20, 40, 60 s (Deckel); ein Abgleich mit `started`/`restarted` setzt die Pause zurück; `stop()` und das Ende des Takts brechen den geplanten Neustart ab. Vitest mit Fake-Timern: Folge der Pausen, Rücksetzen nach Erfolg, kein Neustart nach `stop()`, eine Meldung je Serie.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/tunnel.test.ts
Doku: keine (intern; sichtbare Doku in T8)
Abhängt von: T2, T6

### T8 — Tunnel-Dialog fragt sofort ab; Admin-Doku und CHANGELOG  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/TunnelModal.svelte, apps/desktop/ui/src/components/infra/TunnelModal.test.ts, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, CHANGELOG.md, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @096e606b 2026-10-16T17:15:17+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T8.verdict.json)
Änderung: Nach erfolgreichem Anlegen, Ändern und Löschen (`TunnelModal.svelte:76-78`, `:100-106`) ruft der Dialog `refreshNow()` aus dem Tunnel-Store; ein Fehler dort ändert das Speichern-Ergebnis nicht. Test: je Aktion genau ein `refreshNow`, auch bei dessen Fehler schließt der Dialog. Doku DE+EN: `frp-tunnel.html:71` (Token-Rotation: Desktop übernimmt innerhalb von 60 s mit kurzem Abbruch, kein Handgriff) und `:92` (Secret-Rotation: kein Neustart im Desktop mehr nötig); CHANGELOG-Eintrag.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/TunnelModal.test.ts
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html (`:71`, `:92`) · CHANGELOG
Abhängt von: T6

### T9 — Live-E2E: ein neuer Tunnel wird ohne Neustart übernommen  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/tunnel-start.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @a24303c8 2026-10-16T17:25:47+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T9.verdict.json)
Änderung: Nach „connected“ liest die Spec `tunnel_status` (`connectedSince`, `visitors`), legt über die GUI (`gotoInfrastructure`, `openServerTab('tunnels')` aus `test/lib/live.js:223`/`:233`, wie `tunnel-create.live.js`) einen zweiten STCP-Tunnel am gesäten Server an und wartet bis 20 s, bis `visitors` dessen Visitor enthält; `connectedSince` bleibt gleich (Reload, kein Neustart), die Anzeige bleibt „connected“. Der Orchestrator `scripts/tests/desktop_e2e_tunnel.sh` bleibt unverändert. Der Live-Lauf gehört zu `Heavy:`.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T4, T6, T8

### T10 — Tunnel-Store: `reconnectNow()` verwirft den geplanten Neustart und gleicht sofort ab  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/lib/stores/tunnel.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ad3bc89d 2026-10-16T17:50:59+02:00
Review: approve (.ah-out/review/desktop-tunnel-refresh/T10.verdict.json)
Änderung: Neue exportierte Funktion `reconnectNow()` im Tunnel-Store: bei aktivem Takt verwirft sie einen geplanten Backoff-Neustart (T7), setzt die Pause auf 5 s zurück und ruft `refreshNow()` (T6, reiht während eines laufenden Abgleichs genau einen Folgelauf ein); ohne aktiven Takt (abgemeldet, lokaler Modus) tut sie nichts. Vitest mit Fake-Timern, zuerst rot: nach `markTerminated` und `reconnectNow()` genau ein sofortiger Abgleich und kein weiterer zum alten Backoff-Zeitpunkt; scheitert dieser, beginnt die Pause wieder bei 5 s; nach `stop()` löst `reconnectNow()` nichts aus.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/tunnel.test.ts
Doku: keine (intern; sichtbar mit T11)
Abhängt von: T7

### T11 — Tunnel-Anzeige: Knopf „Neu verbinden“, nur bei getrenntem Tunnel  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/TunnelIndicator.svelte, apps/desktop/ui/src/components/TunnelIndicator.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html
Änderung: `TunnelIndicator.svelte` (Anzeige `:28-33`, Zustände `:15-25`) zeigt bei `$tunnel.ui === 'disconnected'` neben „Tunnel getrennt“ einen kleinen Knopf „Neu verbinden“ (`tunnel.reconnect`, DE neben `dictionaries.ts:191`, EN neben `:815`), der `reconnectNow()` (T10) ruft; in jedem anderen Zustand gibt es keinen Knopf, während eines Abgleichs (`connecting`) erst recht nicht. Neue Testdatei mit SPDX-Header (`// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`), zuerst rot: Knopf nur bei `disconnected`; ein Klick ruft `reconnectNow` genau einmal; bei `connected`, `connecting`, `idle` kein Knopf. Doku DE+EN: ein Satz in der Fehlerbehebung (`frp-tunnel.html:113-114`, EN an der entsprechenden Stelle), dass der Desktop sich selbst wieder verbindet und „Neu verbinden“ das sofort anstößt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/TunnelIndicator.test.ts
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html (Fehlerbehebung)
Abhängt von: T10

Kevin 2026-10-16 (nach dem Review von T4): Die Prüfung der Visitor-TOML im Desktop wird enger, als eigene Task im Bündel (T12); der Server-Teil (Zeichen in Tunnel- und Servernamen) folgt später.

### T12 — Visitor-TOML: nur die vom Server erzeugten Schlüssel, keine Template-Ausdrücke  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Änderung: `validate_visitor_table` (`frpc.rs:263`) lässt unter `auth` und `transport` nur genau die Schlüssel zu, die der Server erzeugt (`generate_visitor_toml`, `_tls_client_block` in `apps/server/app/modules/frp/config_generator.py:218`, `:81`): `auth.method` nur mit dem Wert `token`, `auth.token`, die dort erzeugten `transport.tls.*`-Schlüssel; jeder weitere Schlüssel unter diesen Tabellen wird abgewiesen wie ein unbekannter Wurzelschlüssel. frp rendert Config-Dateien als Go-Template, deshalb darf die fertige Config (`frpc_config`, Kopf plus Server-TOML) kein `{{` enthalten. Tests: jede vom Server erzeugte Form besteht (Fixtures nach dem Generator, mit und ohne TLS-Block); ein zusätzlicher Schlüssel unter `auth` oder `transport`, `auth.method` ungleich `token` und ein `{{` in einem beliebigen Wert werden abgewiesen. Mutationsprobe in einer Kopie: Jede gelockerte Prüfung macht einen Test rot. Doku: der Satz zur Allow-List in `desktop.html:145` (DE+EN) nennt die engere Prüfung.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- visitor
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:145`)
Abhängt von: T4

Kevin 2026-10-16 (nach dem Review von T6): Der Abmelde-Knopf der Kopfzeile stoppt den Tunnel, als eigene Task im Bündel (T13).

### T13 — Abmelden über die Kopfzeile stoppt den Tunnel  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/settings.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, apps/desktop/ui/src/components/AppShell.svelte
Änderung: Der Abmelde-Knopf der Kopfzeile (`AppShell.svelte:276`) ruft `logout()` aus `stores/session.ts` (`:114`) und läuft an `stop()` des Tunnel-Stores vorbei: frpc läuft nach dem Abmelden weiter, die Mappings der vorigen Sitzung bleiben im Store. Neue exportierte Funktion in `stores/settings.ts` neben `serverLogout` (`:148`): zuerst `tunnelStore.stop()` (ein Fehler wird ignoriert wie dort), dann `logout()` aus `session.ts`; `connections.json` bleibt unberührt (kein `reloadForMode`). `AppShell.svelte:276` ruft sie. `session.ts` importiert den Tunnel-Store nicht (`tunnel.ts` importiert `session.ts`). Tests in `settings.test.ts`, zuerst rot: `stopTunnel` vor `bridge.logout`; ein Fehler beim Stoppen verhindert das Abmelden nicht; danach steht der Tunnel-Store auf „idle“ ohne Mappings, und nach 60 s Fake-Timer folgt kein weiterer `refreshTunnel`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/settings.test.ts
Doku: keine (intern)
Abhängt von: T6
