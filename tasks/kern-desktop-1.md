<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-desktop-1 · Review: pro Task
Spec: docs/features/kern-desktop-1.md (Roadmap R-0876, R-0930, R-0932, R-0931, R-0870, R-0948)
Heavy: linux-full — Desktop-Journeys: Sync, Client-Cache mit Geräte-Identität, RDP-Start, Geräte-Reset und Tunnel-Abgleich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@fd3a3b32`, vor dem Schreiben neu greppen; Pfade ohne Präfix unter
`apps/desktop/src-tauri/src/`. Neue Code-Strings englisch, CHANGELOG umlautfrei in `changelog.d/kern-desktop-1.md`.
`security` zusätzlich bei T1, T2, T3, T4 (und wo `review.sh risk` es verlangt). Nicht anfassen: `enrollment.rs`,
`ProvisioningTab.svelte` (offener Branch feature/ca-rotation).

### T1 — Sync-Antworten begrenzt lesen (R-0876)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sync.rs, changelog.d/kern-desktop-1.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @c5a43031 2026-10-29T18:43:37+01:00
Review: approve (.ah-out/review/kern-desktop-1/T1.verdict.json)
Änderung: `fetch` (`sync.rs:35`) und `fetch_server_connections` (`:81`) lesen die Antwort wie `ansible.rs:71-104`: über die deklarierte Länge abgewiesen, sonst stückweise bis 16 MiB; die Fehlermeldung zitiert die Antwort nicht. Test zuerst rot: übergroße Antwort des Test-Servers → Fehler, die bisherigen Verbindungen bleiben.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sync
Doku: changelog.d/kern-desktop-1.md

### T2 — Client-Cache: kein Ablegen nach einem Invalidate (R-0930)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/http_client.rs, changelog.d/kern-desktop-1.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @fd7e085c 2026-10-29T18:46:34+01:00
Review: approve (.ah-out/review/kern-desktop-1/T2.verdict.json)
Änderung: `invalidate_client_cache` (`http_client.rs:108`) erhöht eine Generation; `client_for` (`:60-102`) merkt sie vor dem Bauen und legt den Client (`:101`) nur ab, wenn sie unverändert ist. Einzelheiten privat (tasks/private). Test zuerst rot: ein Invalidate zwischen Bauen und Ablegen → der nächste Aufruf baut neu.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- http_client
Doku: changelog.d/kern-desktop-1.md

### T3 — RDP-Start nach Fristende, Pin-Laden unter der Sperre (R-0932)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/tofu.rs, changelog.d/kern-desktop-1.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @8e42d009 2026-10-29T18:49:54+01:00
Review: approve (.ah-out/review/kern-desktop-1/T3.verdict.json)
Änderung: `open_rdp` (`connection/rdp.rs:127-136`) prüft vor `check_rdp_auth`, ob die Frist schon abgelaufen ist, und endet dann mit `TIMEOUT_MESSAGE`, ohne einen Prozess zu starten; `KeyringPinStore::load` (`tofu.rs:211`) liest nach einem Cache-Fehltreffer unter der Sperre je Identität. Einzelheiten privat. Tests je Regel, zuerst rot.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-desktop-1.md

### T4 — Geräte-Reset: blockierend auslagern, beide Teilfehler melden (R-0931, R-0870 Rust-Teil)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, changelog.d/kern-desktop-1.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @dd1f9b01 2026-10-29T18:52:22+01:00
Review: approve (.ah-out/review/kern-desktop-1/T4.verdict.json)
Änderung: `reset_device_identity_in` (`commands.rs:146-155`) führt `tofu::forget_pin` über `blocking()` wie `reset_server_cert_pin` (`:86-92`); scheitert das Pin-Löschen nach einem Reset `LocalOnly`, nennt der Fehler beides (Widerruf nur lokal, Pin nicht gelöscht). Test (Naht für `forget_pin`): Fehlerpfad mit beiden Teilfehlern.
Beweis: Code-Lesung `commands.rs:146-155` (origin/main@fd3a3b32; Fund aus feature/desktop-blocking T9) · `commands.rs:146-149` (feature/desktop-hardening-3@cdb0dfd1)
Dedup-Key: bug:desktop:commands.rs:reset-device-identity-blocking
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- commands
Doku: changelog.d/kern-desktop-1.md

### T5 — Einstellungen: Zustand nach gescheitertem Geräte-Reset neu laden (R-0870)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.identity.test.ts, changelog.d/kern-desktop-1.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @afc2981b 2026-10-29T18:57:17+01:00
Review: approve (.ah-out/review/kern-desktop-1/T5.verdict.json)
Änderung: Im `catch` von `onResetDeviceIdentity` (`SettingsModal.svelte:202`) lädt die UI den Identitätszustand neu (`refreshDeviceIdentity()`), statt `deviceEnrolled` stehen zu lassen. Test zuerst rot: Reset scheitert, die Identität ist danach weg → die Einstellungen zeigen das Gerät nicht mehr als registriert, der Fehler wird gemeldet.
Beweis: Code-Lesung `SettingsModal.svelte:196` (feature/desktop-hardening-3@cdb0dfd1)
Dedup-Key: bug:desktop:SettingsModal.svelte:reset-failure-state
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.identity.test.ts
Doku: changelog.d/kern-desktop-1.md

### T6 — Tunnel-Abgleich meldet einen verweigerten Zugriff (R-0948, Rust)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, changelog.d/kern-desktop-1.md, apps/desktop/src-tauri/src/models.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @29508b93 2026-10-29T19:00:56+01:00
Review: approve (.ah-out/review/kern-desktop-1/T6.verdict.json)
Änderung: Antwortet der Server auf das Visitor-Bundle mit 403 (`carries_bundle`, `frpc.rs:278`), stoppt der Abgleich frpc wie bisher, und `TunnelRefresh` trägt zusätzlich den Grund (`refused` mit HTTP-Code 403); bei 404 und allen anderen Ausgängen fehlt er. Tests: 403 → Grund gesetzt, 404 → keiner.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc
Doku: → T7

### T7 — Tunnel-Hinweis mit Code in der UI (R-0948, UI)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/lib/stores/tunnel.test.ts, apps/desktop/ui/src/lib/i18n/de.json, apps/desktop/ui/src/lib/i18n/en.json, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, changelog.d/kern-desktop-1.md, apps/desktop/ui/src/lib/stores/settings.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @aee29e0b 2026-10-29T19:06:43+01:00
Review: approve (.ah-out/review/kern-desktop-1/T7.verdict.json)
Änderung: `TunnelRefresh` in `types.ts` bekommt das Feld aus T6; `tunnel.ts` (`:216`) zeigt bei einem Stopp mit Grund einen Hinweis mit dem Code (DE+EN), statt still auf `stopped` zu gehen. Test: Stopp mit Grund → Hinweis mit Code; Stopp ohne Grund → kein Hinweis.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/tunnel.test.ts src/lib/i18n/i18n.test.ts
Doku: docs/admin/frp-tunnel.html + EN (Hinweis bei verweigertem Zugriff) · changelog.d/kern-desktop-1.md
Abhängt von: T6

### T8 — Entwickler-Doku: verweigerter Tunnel-Zugriff und `refused` (R-0948, Abschlussprüfung)  [ ]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html
Änderung: `docs/developer/desktop.html` (`:181` IPC-Tabelle, `:261` Abgleich) + EN: `refresh_tunnel` liefert auch `refused`; bei 403 stoppt der Abgleich frpc und meldet die Verweigerung einmal in der Statusleiste, bei 404 still wie bisher.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/desktop.html + EN
Task-Review: am Ende

## Entscheidungen
- T3: Die Fristprüfung steht am Anfang von `check_rdp_auth` (einziger Aufrufer `open_rdp`), nicht in `open_rdp`: dort ist sie ohne AppHandle testbar; Wirkung gleich (kein xfreerdp, `TIMEOUT_MESSAGE`).
- T6: `TunnelRefresh` liegt in `models.rs`, nicht in `frpc.rs` (Datei nachgetragen); `refused` als `Option<u16>` (HTTP-Code), Weg über ein kleines `BundleReply`. Changelog-Eintrag für beide mit T7.
- T7: Die Übersetzungen stehen in `i18n/dictionaries.ts` (die im Plan genannten `de.json`/`en.json` gibt es nicht); der Hinweis geht über `reportError` und kommt je Verweigerung einmal (Ticks danach still, neu nach einem Lauf ohne Verweigerung oder einer neuen Aktivierung), damit die Statusleiste nicht jede Minute dieselbe Meldung zeigt.
