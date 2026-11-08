# Eingebettetes RDP: Pin immer, Stufe 2 Tab — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-1 · Review: pro Task
Spec: docs/features/kern-rdp-1.md (Roadmap R-1141, R-1098)
Heavy: linux-full — Desktop-Journey: der RDP-Tab gegen den xrdp-Container (neue Live-Spec) und `desktop_e2e_rdp_embedded` laufen im Sammellauf; IronRDP-Quelle und TLS-Prüfung ändern sich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1141: Pin immer über eine IronRDP-Option (Fork-Revision, Upstream-PR)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/tofu.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, docs/features/arch-rdp-backend.md, THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @7f2099fbf 2026-11-08T16:00:31+01:00
Review: approve (.ah-out/review/kern-rdp-1/T1.verdict.json)
Änderung: Fork `AdminCave/IronRDP`, Branch auf `f96f664` plus eine additive Option in `ironrdp-tls` (und ihr Weg durch `ironrdp-client`), mit der der Prüf-Callback jedes Leaf-Zertifikat sieht, auch nach bestandener strenger Prüfung; Test in der IronRDP-Testsuite, Upstream-PR gegen `master` nach `AGENTS.md`/`STYLE.md` (Kevin 2026-11-08: Weg (c)). Der Desktop bezieht alle `ironrdp-*` aus der Fork-Revision und setzt die Option; `tofu.rs` behandelt ein CA-gültiges Zertifikat ohne Pin wie ein unbekanntes (`certificate`, Grund `unknown`). Test: Handshake mit einem Zertifikat einer Test-CA, der die Plattform-Wurzeln vertrauen (`SSL_CERT_FILE`), ohne Pin → `certificate`; mit Pin → verbunden; Gegenprobe ohne die Option rot. `arch-rdp-backend.md` Offene Frage 1 auf erledigt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T8

### T2 — R-1098: Backend Stufe 2 — Statistik, Leistungsprofil, Strg+Alt+Entf, Screenshot, Verbindungsinfo  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/capabilities.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @24f409f0d 2026-11-08T16:21:34+01:00
Review: approve (.ah-out/review/kern-rdp-1/T2.verdict.json)
Änderung: Die Sitzung meldet je Sekunde fps, Mbit/s, Auflösung und, wenn bekannt, Codec und RTT (`NetworkCharacteristics`) als Text-Nachricht auf dem Frame-WebSocket; `rdp_performance_profile` wird auf `with_performance_flags` abgebildet (Auto wie LAN, Niedrig ohne Hintergrund, Themes, Animationen); Strg+Alt+Entf als Eingabe-Nachricht (Scancode-Folge); ein Befehl speichert das letzte Bild als PNG über den Rust-Speichern-Dialog; ein Befehl liefert die Verbindungsinfo (Ziel, Tunnel ja/nein, TLS-Version, CredSSP, Fingerprint). Tests je Teil, Neuverbindung behält die Statistik konsistent.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T8
Abhängt von: T1

### T3 — R-1098: Einstellung `rdp_client` (Wire-Vertrag)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/bridge/types.parity.test.ts, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/migration.rs
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @095d273cd 2026-11-08T16:40:18+01:00
Review: approve (.ah-out/review/kern-rdp-1/T3.verdict.json)
Änderung: `Settings.rdp_client` (`embedded` | `os`) mit `#[serde(default)]`, Standard `os` bis R-1090 (Bedingung 4); UI-Typ und Parity-Test; Test: eine Einstellungsdatei ohne das Feld liest sich als `os`, Rundreise beider Werte.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T8

### T4 — R-1098: UI-Bibliothek der Sitzung — WebSocket, Renderer, Tastatur, Maus  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/rdp/frameSocket.ts, apps/desktop/ui/src/lib/rdp/frameSocket.test.ts, apps/desktop/ui/src/lib/rdp/renderer.ts, apps/desktop/ui/src/lib/rdp/renderer.test.ts, apps/desktop/ui/src/lib/rdp/input.ts, apps/desktop/ui/src/lib/rdp/input.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e469a5618 2026-11-08T17:01:07+01:00
Review: approve (.ah-out/review/kern-rdp-1/T4.verdict.json)
Änderung: Neue Dateien mit SPDX-Header. Frame-Client (Token als erste Nachricht, 14-Byte-Kopf lesen, `ack` je Bild, Statistik-Nachrichten, Schließen); Renderer mit WebGL-Textur und 2d-Rückfall, eingepasst mit Seitenverhältnis; `KeyboardEvent.code` → Set-1-Scancode mit E0, Maus in Desktop-Koordinaten, Rad; Tastatur-Fang mit Freigabe durch Strg+Alt+Pos1 und bei Fokusverlust; Bridge-Aufrufe der Befehle. Unit-Tests je Modul (Kopf, Gegendruck, Abbildungstabelle, Koordinaten bei Einpassung, Fang/Freigabe).
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T8
Abhängt von: T2

### T5 — R-1098: RDP-Tab — Sitzungsansicht, Phasen, Menü, Statuszeile, Zertifikatsdialog  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/components/terminal/RdpSession.test.ts, apps/desktop/ui/src/components/terminal/SessionTabs.svelte, apps/desktop/ui/src/components/terminal/SessionTabs.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neue Komponente mit SPDX-Header; RDP-Sitzungen als eigene Art im Tab-Store (Start, Phasen aus `rdp-session`, Stopp beim Schließen, Abmelden, Fensterende); Ansicht nach dem Mockup (DesignSystem `ui_kits/adminhelper/rdp.jsx`): Kopf mit Trennen, Neu verbinden, Strg+Alt+Entf, Screenshot, Verbindungsinfo, Leistungsprofil; Phasen-Overlays; Fuß mit Auflösung, Codec, fps, Mbit/s, RTT („—“ ohne Meldung) und dem Hinweis „Strg+Alt+Pos1 Tastatur freigeben“; Zertifikatsdialog (Fingerprint, Grund unbekannt/geändert) → `rdp_trust_certificate` → Neustart. Kein Abdocken (Stufe 5). Tests: Phasen, Dialog, Schließen stoppt, Menüaktionen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T8
Abhängt von: T4

### T6 — R-1098: Connect-Flow — `rdp_client`, Split-Button, Rückfall, Einstellungen  [ ]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/components/terminal/ConnectButton.svelte, apps/desktop/ui/src/components/terminal/ConnectButton.test.ts, apps/desktop/ui/src/components/settings/RdpSection.svelte, apps/desktop/ui/src/components/settings/RdpSection.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Doppelklick, Enter, *Verbinden* und Schnellzugriff öffnen RDP nach `rdp_client`; der Pfeil am Knopf wählt den Client je Start (wie SSH); `ERR_RDP_OS_CLIENT` startet den OS-Client mit Hinweis; Einstellung *Client für RDP* in *Einstellungen → RDP*. Ohne gespeichertes Passwort fragt der Passwort-Dialog, und `rdp_session_start` nimmt das getippte Passwort einmalig an (Kevin 2026-11-08); dazu der Parameter im Backend (`mod.rs`, Zeroizing, gleiche Prüfungen wie beim OS-Client-Weg). Tests je Weg, auch Rückfall, Einstellung und das getippte Passwort (Rust: angenommen, nicht gespeichert, gleiche Ablehnungen).
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T8
Abhängt von: T3, T5

### T7 — R-1098: Live-Spec — RDP-Tab gegen xrdp  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/rdp-embedded.live.js, scripts/tests/desktop_e2e_connect.sh
Änderung: Neue Spec mit SPDX-Header: `rdp_client` auf AdminHelper, Verbindung `rdp-direct` öffnen, Zertifikat bestätigen, Tab zeigt `verbunden` und ein Bild (Canvas nicht leer), Taste erreicht den Server, Trennen; der Orchestrator prüft serverseitig über das xrdp-Log. Läuft im Sammellauf (Heavy linux-full).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T8
Abhängt von: T6

### T8 — R-1098, R-1141: Doku DE+EN und Changelog  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-rdp-1.md
Änderung: Eingebettetes RDP in `desktop.html` DE+EN (Pin immer, Fork-Revision, neue Befehle und WebSocket-Nachrichten, Tab statt „keine Oberfläche“); `admin/index.html` DE+EN (Einstellung *Client für RDP*, Bedienung des Tabs, Tastatur-Fang, Rückfall); Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-rdp-1.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5, T6, T7

### T9 — R-1098: Strg+Alt+Entf gegen Windows prüfen (Bedingung 6)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs
Änderung: Im privaten Wegwerf-Repo von R-1092 (Kevin 2026-11-08) schickt die Probe die Strg+Alt+Entf-Folge aus T2 an den Windows-Runner und hält fest, ob der Sicherheitsbildschirm erscheint; Ergebnis nur unter `tasks/private/spikes/`. Im Baum ändert sich nur der Kommentar an der Folge (neutral).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: keine (Ergebnis privat)
Abhängt von: T2

## Entscheidungen
- 2026-11-08 Gate: Start ohne gespeichertes Passwort mit einmal getipptem Passwort an `rdp_session_start` (Kevin 2026-11-08, Offene Frage 1)
- 2026-11-08 Gate: Strg+Alt+Entf gegen Windows als Probe im privaten Wegwerf-Repo von R-1092 (Kevin 2026-11-08, Offene Frage 2)
- 2026-11-08 T2: Mbit/s ist die vom Server gemessene Bandbreite (`NetworkCharacteristics.bandwidth_kbps`/1000), RTT dessen `average_rtt_ms`; beides nur, wenn gemeldet. IronRDP (Fork c39d48e) gibt weder Transport-Bytezähler noch den Codec noch die TLS-Version an den Client weiter: Codec und TLS-Version fehlen in Statistik und Verbindungsinfo
- 2026-11-08 T2: fps zählt die Bilder, die der Frame-WebSocket je Sekunde an die Webview schickt; keine Statistik vor dem ersten Bild; eine Neuverbindung (Watchdog oder IronRDP) setzt RTT und Bandbreite zurück, Auflösung bleibt bis zum nächsten Bild
- 2026-11-08 T2: Leistungsprofil `Auto` wie `Lan`; das eigene Profil der Verbindung vor dem der Einstellungen (wie `RdpOptions::with_overrides`)
- 2026-11-08 T2: Verbindungsinfo: Ziel `host:port` der gespeicherten Verbindung, Tunnel ja/nein mit Name, CredSSP, Zertifikat `pinned`/`trust_all`, Fingerprint = der Pin (bei `trust_all` keiner); Screenshot = PNG des ganzen Desktops zum Zeitpunkt des Aufrufs, Standardname `rdp-<jjjjmmtt-hhmmss>.png`
- 2026-11-08 T4: Die Canvas hat die Desktopgröße und wird per CSS `object-fit: contain` eingepasst; `toDesktop` rechnet über `fitRect` zurück, Punkte in den Balken landen am Rand
- 2026-11-08 T4: Auch ein unlesbares Bild wird quittiert, sonst hielte der Gegendruck des Servers die Sitzung an; ein Rad-Ereignis ist eine Raste (±120), Pause hat keinen einfachen Set-1-Code und wird nicht gesendet
- 2026-11-08 T4: Der IPC-Inventartest liest Befehle jetzt auch aus `rdp_embedded/` und nimmt Pfade in `generate_handler!` mit ihrem letzten Segment; bisher fielen die RDP-Befehle aus dem Abgleich. Die Befehlstabelle der Entwicklerdoku nennt dafür `rdp_session_screenshot` und `rdp_session_info` (die Beschreibung zieht T8 nach)
