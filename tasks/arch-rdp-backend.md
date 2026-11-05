<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Eingebettetes RDP Stufe 1: Backend — Task-Ledger
Status: aktiv · Branch: feature/arch-rdp-backend · Review: pro Task
Spec: docs/features/arch-rdp-backend.md (Roadmap R-1097)
Heavy: linux-full — neue Desktop-Suite `desktop_e2e_rdp_embedded` (xrdp-Container, GUI-Teil des E2E-Layers) im Sammellauf; vor dem Merge dieser Schritt einmal auf einer Pool-VM der eigenen Lane (`run.sh e2e --strict --part gui --step desktop_e2e_rdp_embedded`). Kein `windows`: Den Windows-Pfad (Media Foundation) bauen und testen `rust-windows` und `tauri-build-smoke`; Desktop-GUI unter Windows bleibt nicht verifiziert (R-1090).
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `reviewer` je Task (ein Prüfer für den Zug, fortgesetzt); `security` dazu bei T2 (Risikopfad `tofu.rs`), T3
(Token und lokaler Port) und T5 (Passwort aus dem Keyring an IronRDP).
Reihenfolge: T1 zuerst (Abhängigkeit). T2, T3 und T4 hängen nur an T1. T5 braucht T2 bis T4, T6 braucht T5, T7 zuletzt.
Überlappung: `THIRD_PARTY_LICENSES.md` ändert auch `feature/kern-laufzeit-2` (PR #400, anderer Abschnitt); vor dem Push
`origin/main` hineinmergen.

## Tasks

### T1 — IronRDP als Abhängigkeit, Lizenz-Gates, THIRD_PARTY_LICENSES  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs (neu, SPDX), apps/desktop/src-tauri/src/rdp_embedded/license_gate.rs (neu, SPDX), THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @7fbdf2b1 2026-11-05T09:36:56+01:00
Review: approve (.ah-out/review/arch-rdp-backend/T1.verdict.json)
Änderung:
- `Cargo.toml`: `ironrdp-client` und `ironrdp-tls` als Git-Abhängigkeit auf Revision
  `f96f664abf0bdfe547f222bcd37e09899f00f310`.
  - `ironrdp-client` ohne Default-Features, nur mit `clipboard` und `rdpdr`. Ohne `rustls` und `udp`, denn beide
    ziehen `aws-lc-rs`; `sound` bleibt aus (Spec E2).
  - `ironrdp-tls` ohne Default-Features, mit `rustls-ring`.
  - Ein Kommentar begründet die Feature-Wahl (Bedingungen 7 und 8, E2).
- `rdp_embedded/mod.rs`: das Modul, zunächst nur mit `#[cfg(test)] mod license_gate;`, eingebunden in `main.rs`.
- `license_gate.rs`: Test je verbotenem Paket (`aws-lc-rs`, `aws-lc-sys`, `openh264-sys2`) und die Gegenprobe `ring`.
  - Aufruf: `$CARGO tree --locked --offline -e normal,build -i <paket>` in `CARGO_MANIFEST_DIR`.
  - „Fehlt“ heißt: Exit ≠ 0 mit „did not match any packages“, oder Exit 0 mit leerer Ausgabe.
  - Jeder andere Ausgang ist rot, auch ein Startfehler von `cargo`.
- `THIRD_PARTY_LICENSES.md` Abschnitt 3:
  - neu erzeugt mit `scripts/gen-third-party-licenses.sh` (direkte Abhängigkeiten, Lizenzverteilung);
  - Apache-NOTICE nachgezogen, falls ein neues Paket eine trägt.
- Das erste CI-Ergebnis von `rust`, `rust-windows` und `tauri-build-smoke` zeigt, ob Systempakete fehlen. Fehlen
  welche: STOPP, Frage an Kevin (Workflow).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- license_gate
Doku: THIRD_PARTY_LICENSES.md · Entwickler-Doku → T7

### T2 — RDP-TOFU: Pin-Identität, Entscheidung, Prüf-Callback, Befehl `rdp_trust_certificate`  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tofu.rs, apps/desktop/src-tauri/src/rdp_embedded/tofu.rs (neu, SPDX), apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/test-fixtures/README.md, docs/features/arch-rdp-backend.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @59ea14b4 2026-11-05T10:01:03+01:00
Review: approve (.ah-out/review/arch-rdp-backend/T2.verdict.json)
Abhängt von: T1
Änderung:
- `tofu.rs` (Risikopfad), keine Verhaltensänderung:
  - `PinStore` (`tofu.rs:95`), `KeyringPinStore::production` (`tofu.rs:161`), `decide` (`tofu.rs:83`) und
    `PinDecision` (`tofu.rs:70`) werden `pub(crate)`.
  - Ein Speicher-Helfer schreibt einen bestätigten Pin unter der Sperre seiner Identität.
- `rdp_embedded/tofu.rs`:
  - `pin_identity(workspace, conn, resolved)`: `rdp/<workspace>/<host>:<port>` direkt,
    `rdp/<workspace>/<tunnel>/<host>:<port>` über einen Tunnel, mit Host und Port der gespeicherten Verbindung; IPv6 in
    Klammern; `%` und `/` in Tunnelname und Host kodiert.
  - `CertPolicy`: `TrustAll` aus `trust_cert`, sonst `Pinned(Option<fp>)` mit dem Endpoint der Sitzung (IronRDP-
    `Destination`), vorab aus dem Keyring gelesen. Ein Lesefehler startet nicht (fail closed).
  - `validation_callback(policy, report)` für IronRDP, die Regeln:
    - `TrustAll` nimmt an.
    - Ein passender Pin nimmt an.
    - Ohne Pin lehnt der Callback ab und meldet „unknown“ mit dem Fingerprint (`tofu.rs:40`).
    - Ein abweichender Pin lehnt ab und meldet „changed“.
    - Ein anderer Endpoint (Server-Umleitung) lehnt ab und meldet nichts zur Bestätigung.
    - Der Callback schreibt nie einen Pin.
  - Befehl `rdp_trust_certificate(identity, fingerprint)`: prüft Präfix `rdp/<workspace>/` des eigenen Prozesses (im
    Launcher keiner) und 64 Hex-Zeichen und speichert über `KeyringPinStore`. Er wird in `main.rs` registriert.
- Tests:
  - Identitäten: direkt, Tunnel, IPv6, je Workspace, Kodierung.
  - Entscheidungstabelle der vier Fälle; der Callback meldet Fingerprint und Grund.
  - Lesefehler heißt kein Start.
  - Trust-Befehl: Eingabeprüfung, dann Speichern und erneutes Lesen mit dem Speicher-Keyring.
  - Ein echter Handshake gegen einen In-Process-TLS-Server mit selbstsigniertem Zertifikat (Muster `test_tls.rs`):
    `ironrdp_tls::upgrade_with_certificate_validation_callback_for_endpoint` fragt den Callback. Eine Ablehnung bricht
    den Handshake ab, ein Pin lässt ihn durch. Die rustls-Konfiguration von IronRDP findet `ring` ohne Panic.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tofu
Doku: → T7

### T3 — Bildweg: lokaler WebSocket mit Token, Bildpuffer, Gegendruck, Eingabe; CSP  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs (neu, SPDX), apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/tauri.conf.json, apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock
Abhängt von: T1
Änderung:
- `frame_ws.rs`, Server und Anmeldung:
  - Der Server bindet `127.0.0.1:0`; das Token sind 32 Zufallsbytes aus dem Krypto-RNG (hex).
  - Die erste Textnachricht muss das Token sein: Vergleich in konstanter Zeit, Frist 5 s. Sonst schließt der Server,
    ein zweiter Client wird abgewiesen.
- `frame_ws.rs`, Bild und Eingabe:
  - Ein Bildpuffer in Desktop-Größe nimmt die `DesktopUpdate`-Rechtecke auf (`0x00RRGGBB`) und führt ein
    umschließendes Schmutz-Rechteck.
  - Nach jeder `ack`-Quittung geht höchstens ein Bild (Kopf nach Spec, RGBA).
  - Eingaben (`key`, `mouse`, `close`) werden in einen Enum geparst; Fehlerhaftes wird verworfen.
- `Cargo.toml`: `tokio-tungstenite` 0.29 (schon im Lock über IronRDP), `tokio` um `rt`.
- `tauri.conf.json:16`: `connect-src` um `ws://127.0.0.1:*`; `script-src` bleibt unverändert.
- Tests mit echtem WebSocket-Client:
  - Anmeldung: falsches Token, keine Anmeldung binnen Frist, zweiter Client.
  - Der Server lauscht nur auf 127.0.0.1.
  - Gegendruck: zehn Updates vor der Quittung ergeben genau ein Bild mit dem umschließenden Rechteck und den neuesten
    Pixeln.
  - Kopf-Layout; Eingaben gültig und ungültig.
  - Die CSP enthält den Eintrag, und `script-src` ist unverändert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frame_ws
Doku: → T7

### T4 — Watchdog gegen Bildstillstand  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/watchdog.rs (neu, SPDX), apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Abhängt von: T1
Änderung:
- Reine Zustandsmaschine mit eingespeister Zeit. Sie bekommt `login_complete`, `frame`, `input_sent` und `tick(now)` und
  antwortet `Ok` oder `Reconnect`.
- Regeln:
  - Kein erstes Bild binnen N s nach `LoginComplete` heißt Reconnect.
  - Eine Eingabe ohne Bild binnen N s heißt Reconnect.
  - Ein ruhiger Desktop ohne Eingabe löst nie aus.
  - Nach M Neuverbindungen ohne Bild meldet sie `GiveUp`.
- N und M sind Konstanten mit Begründung (T2 der R-1074-Probe).
- Tests: jede Regel, die Grenzwerte und der ruhige Desktop über eine lange Zeit.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- watchdog
Doku: → T7

### T5 — Sitzung: IronRDP-Konfiguration, Sitzungs-Thread, Start/Stop, Phasen-Events, xrdp-Integrationstest  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs (neu, SPDX), apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/mod.rs
Abhängt von: T2, T3, T4
Änderung:
- `session.rs`, Konfiguration:
  - Feste Größe; `with_compression(false)` und `with_graphics_pipeline(true)` (Bedingungen 1 und 9).
  - `with_tls(true)` und `with_credssp(true)`; Strict mit dem Callback aus T2.
  - H.264 nach Plattform-Default: Windows Media Foundation, Linux keiner (Bedingung 7). Keine Kanäle.
- `session.rs`, Sitzungs-Thread:
  - Ein Thread mit `current_thread`-Laufzeit und `LocalSet` trägt `RdpClient` (`with_desktop_updates`) und den
    WebSocket aus T3; Panics fängt er ab.
  - Die Events gehen an Bildpuffer und Watchdog. `AutoReconnecting` wird beantwortet. Logon-Infos wie
    `SESSION_CONTINUE` sind keine Fehler (Bedingung 11).
  - Ein Watchdog-Reconnect baut `RdpClient` neu; `Terminated` und `ConnectionFailure` werden Phasen.
- `mod.rs`:
  - `RdpSessions` (Tauri-State), Phasen über eine Senke: Tauri-`emit` im Betrieb, ein Kanal im Test.
  - Befehle `rdp_session_start` und `rdp_session_stop`, in `main.rs` registriert.
- Der Start folgt `open_connection_stored` (`commands.rs:421`):
  - Schnappschuss der Sitzung, dann `reject_foreign_port` (`commands.rs:370`, wird `pub(crate)`);
  - `checked_password_source` (`connection/mod.rs:182`, wird `pub(crate)`), `resolve_connection`;
  - `load_password_keyring` (`password.rs:121`); das Passwort bleibt in `Zeroizing`;
  - den Pin vorab lesen (T2).
- Tests ohne Netz:
  - Start lehnt ab: falsche Art, fremder Port, Passwortquelle, die nicht passt, Keyring-Lesefehler beim Pin.
  - Stop einer unbekannten ID; Phasenfolge mit einer gefälschten Event-Quelle.
- `#[ignore]`-Integrationstest `xrdp_live_session`, Ziel aus der Umgebung, gestartet vom Skript in T6:
  - erster Kontakt meldet `certificate` (unknown) mit dem Fingerprint des Containers;
  - Pin speichern, Neustart, `connected`;
  - WebSocket: falsches Token wird abgewiesen, richtiges bekommt ein Bild in Sollgröße;
  - ohne Quittung kein zweites Bild, trotz Eingabe; mit Quittung das nächste;
  - ein falscher Pin meldet `certificate` (changed);
  - Stop meldet `disconnected` und schließt den Socket.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T7

### T6 — xrdp-Suite: Container mit GFX und Skript im E2E-Layer  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_rdp_embedded.sh (neu, SPDX), scripts/tests/xrdp-gfx/Dockerfile (neu, SPDX), scripts/tests/xrdp-gfx/entrypoint.sh (neu, SPDX)
Abhängt von: T5
Änderung:
- `xrdp-gfx/Dockerfile`, neu geschrieben, ohne Lab-Daten:
  - Debian trixie per Digest; xrdp 0.10 mit `xorgxrdp` und einer schlanken X-Sitzung.
  - Nutzer `e2e`/`e2e`; selbstsigniertes Zertifikat beim Start.
  - `entrypoint.sh` startet `xrdp-sesman` und `xrdp` im Vordergrund.
- `desktop_e2e_rdp_embedded.sh`, Vorbedingungen:
  - Es prüft `cargo tauri` wie jede `desktop_e2e_*`-Suite: Exit 75, „SKIP: tauri-cli“, der Vertrag aus
    `desktop_e2e_skip_test.sh`.
  - Dazu `e2e_require docker openssl`.
- `desktop_e2e_rdp_embedded.sh`, Ablauf:
  - Image bauen, Container auf `127.0.0.1:<frei>` starten, Bereitschaft über das Log abwarten.
  - Den Fingerprint des Container-Zertifikats mit `openssl` lesen.
  - Den Rust-Test fahren: `cargo test --locked -- --ignored --exact rdp_embedded::session::tests::xrdp_live_session`,
    das Ziel per Umgebung.
  - Grün nur bei „1 passed“. Aufräumen per `trap`.
- Live-Beleg vor dem Merge: dieser Schritt auf einer Pool-VM (Heavy-Zeile). Lokal das Image und der ignorierte Test
  von Hand gegen den Container (Dev-Box ohne tauri-cli); das Ergebnis kommt in den Commit-Body.
Verify: bash scripts/dev/verify.sh scripts --strict -- desktop_e2e_skip_test
Doku: → T7

### T7 — Doku DE+EN, CHANGELOG, Binärgröße  [ ]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/arch-rdp-backend.md
Abhängt von: T6
Task-Review: am Ende
Änderung:
- `desktop.html` DE und EN:
  - neuer Abschnitt „Eingebettetes RDP (Backend)“ mit Sitzung, Befehlen, Event `rdp-session`, WebSocket-Protokoll,
    Watchdog, xrdp-Suite und Binärgröße;
  - „TLS-Zertifikat-Pinning (TOFU)“ um die RDP-Pins (je Workspace), die CA-Regel, `SSLKEYLOGFILE` und das
    Zielzertifikat, das ein umleitender Server meldet (IronRDP nimmt es ohne unseren Callback an);
  - die Befehlsliste um die drei Befehle.
- Binärgröße: Release-Build (`cargo build --release --locked`) von `origin/main` und vom Branch, die Differenz in die
  Doku und in den PR.
- `changelog.d/arch-rdp-backend.md` (`### Added`, umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/arch-rdp-backend.md

### T8 — Audit-Ausnahme RUSTSEC-2023-0071 (`rsa` über IronRDP)  [?] (RUSTSEC-2023-0071 (rsa, Marvin, ohne Fix) im Desktop hinnehmen und per .cargo/audit.toml ausnehmen? Empfehlung: ja, kein privater RSA-Schlüssel im genutzten Anmeldeweg)
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/.cargo/audit.toml (neu), apps/desktop/src-tauri/src/rdp_embedded/license_gate.rs, docs/features/arch-rdp-backend.md
Abhängt von: T1
Änderung:
- Befund aus dem Review von T1: `rsa 0.10.0-rc.18` kommt über `picky`, `sspi` und `winscard` (IronRDP) in den Build
  (`cargo tree -e normal,build -i rsa`). Für `rsa` gilt RUSTSEC-2023-0071 (Marvin: Timing-Seitenkanal bei Operationen
  mit dem privaten Schlüssel), eine gepatchte Version gibt es nicht. `cargo audit` (`audit.yml`, Job `rust`) wird
  damit rot.
- Bei „hinnehmen“: `.cargo/audit.toml` neben `Cargo.lock` mit `ignore = ["RUSTSEC-2023-0071"]` und Begründung.
  - Die Sitzung meldet sich mit dem Passwort über CredSSP/NTLM an; einen privaten RSA-Schlüssel nutzt IronRDP nur bei
    Smartcard- und Entra-Anmeldung, beide nutzt die Sitzung nicht; Standard-RDP-Sicherheit bleibt aus (Spec).
  - `cargo audit` liest die Datei aus dem Arbeitsverzeichnis des Jobs, der Workflow bleibt unverändert (Probe auf
    dem Lockfile von T1: rc 1 ohne, rc 0 mit der Datei).
  - Ein Test in `license_gate.rs` hält die Ausnahmeliste bei genau diesem Advisory.
- Spec-Abschnitt „Risiken“ um den Fall ergänzt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- license_gate
Doku: docs/features/arch-rdp-backend.md · Entwickler-Doku → T7

## Entscheidungen
- 2026-11-05 T1: `tokio-tungstenite` 0.29 als direkte Abhängigkeit mit `default-features = false` und `rustls-tls-native-roots` — `ironrdp-client` ruft `client_async_tls` ohne Feature-Gate (RDCleanPath-Transport, `connect_rdcleanpath_transport`) und baut ohne TLS-Feature nicht; rustls ohne Default-Features hält den Provider bei ring, `aws-lc-rs` bleibt draußen (`cargo tree -i`).
- 2026-11-05 T1: Die Lizenz-Gates fragen `cargo tree --locked --offline -e normal,build -i <crate>`, nicht `Cargo.lock` oder `cargo-license` — beide führen `aws-lc-rs`/`aws-lc-sys` über das Default-Feature `aws-lc-rs` von `sspi` (`rustls?/aws-lc-rs`), obwohl sie nicht gebaut werden; THIRD_PARTY_LICENSES nennt das ausdrücklich.
- 2026-11-05 T1: Die Apache-Pflichtliste der Rust-Crates (Abschnitt 3 und „NOTICE") aus dem gebauten Graphen neu erhoben statt nur ergänzt — `borsh-derive`, `encoding_rs`, `unicode-ident` sind dort nicht mehr Apache-pflichtig, neu sind `cryptoki`, `cryptoki-sys`, `flagset`, `gethostname` (IronRDP/sspi) und `target-lexicon`; keines liefert eine NOTICE-Datei.
- 2026-11-05 T1: Der Befund RUSTSEC-2023-0071 (`rsa` über IronRDP, ohne Fix) wird eine eigene Frage-Task (T8) statt T1 anzuhalten: die Abhängigkeit selbst deckt Kevins Entscheidung R-1074 (IronRDP nativ), die Ausnahme im Audit ist hingenommenes Restrisiko und seine Entscheidung; T8 offen hält den Abschluss (`review.sh final`) auf, die übrigen Tasks laufen weiter.
- 2026-11-05 T2: `rdp_trust_certificate` schreibt über `KeyringPinStore::store` (Identitäts-Sperre, Cache) statt eines neuen Helfers; dafür sind `PinDecision`, `decide`, `PinStore`, `KeyringPinStore` und `production` in `tofu.rs` jetzt `pub(crate)`, ohne Verhaltensänderung. Die RDP-Pins teilen den Keyring-Namensraum `tofu|cert|…` mit den Server-Pins; das Präfix `rdp/` trennt sie, und der Befehl nimmt nur Identitäten mit diesem Präfix an.
- 2026-11-05 T2 (security, Runde 1): Die Pin-Identität trägt die Workspace-ID (`rdp/<workspace>/…`) statt des Keyring-Präfixes `keyring_prefix()` — der ist für migrierte Workspaces leer (`legacy_keys`), die ID nie; `rdp_trust_certificate` nimmt nur Identitäten des Workspaces aus `workspace::current()` an. Der Callback ist an den Endpoint der Sitzung (`Destination::to_string()`, wie IronRDP ihn übergibt) gebunden und lehnt jedes andere Ziel ohne Meldung ab; `TrustAll` bleibt `/cert:ignore` und nimmt weiter alles an.
