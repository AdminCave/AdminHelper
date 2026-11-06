<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-rdp-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-2 · Review: pro Task
Spec: docs/features/kern-rdp-2.md (Roadmap R-1099, R-1092)
Heavy: linux-full + windows — linux-full: neue Kanäle in der eingebetteten Sitzung, die `desktop_e2e_rdp_embedded` (xrdp-Container) im Sammellauf fährt, und eine neue Laufzeit-Abhängigkeit des Linux-Pakets; windows = die CI-Jobs `rust-windows` und `tauri-build-smoke` (der Pool hat keine Windows-Vorlage): Zwischenablage-Fabrik und Laufwerk sind `cfg(windows)`-Code. PR merged Kevin (`.github/workflows/`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@ddfec795`, IronRDP `f96f664`. Kevins Entscheidung vom 2026-11-06 in R-1099.

### T1 — Desktop: Zwischenablage in der eingebetteten Sitzung (R-1099)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Änderung: `config()` setzt `ClipboardType::Enable` (Linux: natives Backend, Text und Bilder). Unter Windows setzt `start_attempt()` eine eigene Fabrik (`RdpClient::with_cliprdr_backend_factory`) mit `WinClipboard::new` ohne Dateiübertragung und einem Proxy über `RdpInputSender::send_clipboard`; die Instanz lebt so lange wie die Sitzung. Der Test `session_configures_tls_gfx_and_no_channels` wird zu einem Test der Kanal-Konfiguration (Zwischenablage an, Drucker/Ports/Smartcard aus).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T5

### T2 — Desktop: Audio aus den Optionen, libasound in Paket und CI (R-1099)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/tauri.conf.json, .github/workflows/ci.yml, .github/workflows/release.yml, scripts/vm/bootstrap_linux.sh, DEVELOPMENT.md
Änderung: Feature `sound` für `ironrdp-client`. `prepare()` gibt `options.rdp.audio` in den `Target`; `config()` setzt `with_sound`/`with_audio_mode`: `local` oder ungesetzt → `RedirectToClient`, `remote` → `PlayOnServer`, `off` → aus; `with_audio_capture(false)`; unter `cfg(windows)` immer aus (Bedingung 12). `libasound2-dev` in den Tauri-Schritten von `ci.yml` und `release.yml`, in `bootstrap_linux.sh` und `DEVELOPMENT.md`; deb/rpm-Abhängigkeit in `tauri.conf.json` nach der Tauri-Doku (vorher lesen). Tests je Audio-Wert und für Windows. Neun Dateien, weil die Abhängigkeit ohne die Build-Pakete in jedem CI-Job rot wäre.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: DEVELOPMENT.md · sonst → T5
Abhängt von: T1

### T3 — Desktop: Downloads-Ordner als Laufwerk bei `drives: true` (R-1099)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Änderung: Abhängigkeit `ironrdp-rdpdr-native` an derselben Revision. `rdp_session_start` löst `app.path().download_dir()` auf, `prepare()` legt mit `drives: true` den Ordner in den `Target`; `start_attempt()` setzt `with_rdpdr(true)` und eine Fabrik (`NixRdpdrBackendFactory::new(<ordner>).with_drive(1, "Downloads")`, unter Windows `WindowsRdpdrBackendFactory` mit `RedirectedDrive`), sonst `with_rdpdr(false)`. Fehlt der Ordner oder scheitert die Fabrik, startet die Sitzung ohne Laufwerk und die Statusmeldung nennt den Grund. Tests: mit/ohne `drives`, fehlender Ordner, kein Drucker/Port/Smartcard. Risikopfad: `security`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: → T5
Abhängt von: T2

### T4 — R-1092: Windows-Probe des Absturzes reproduzieren und eingrenzen  [?] (Wo läuft die Probe: privates Wegwerf-Repo (Empfehlung) oder Wegwerf-Branch im öffentlichen Repo mit öffentlichem Log?)
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs
Änderung: Die Probe aus R-1074 T4 an IronRDP `f96f664` auf einem Windows-Runner, ohne Merge; Ergebnis und Logs nur unter `tasks/private/spikes/`. Reproduziert sich der Absturz: Mail-Entwurf an Devolutions unter `tasks/private/`, Kevin schickt ab. Im Baum ändert sich nur der Kommentar am Windows-Gate aus T2 (Verweis auf R-1092, neutral); Audio unter Windows bleibt aus.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: keine (Ergebnis privat)
Abhängt von: T2

### T5 — Doku und CHANGELOG (R-1099)  [ ]
Komponente: desktop-rs · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, THIRD_PARTY_LICENSES.md, changelog.d/kern-rdp-2.md
Änderung: Abschnitt „Eingebettetes RDP (Backend)“ DE+EN: Zwischenablage, Audio (Windows aus), Downloads-Laufwerk statt „keine Kanäle“. `THIRD_PARTY_LICENSES.md` mit `scripts/gen-third-party-licenses.sh` neu erzeugen. Changelog-Fragment (ohne Umlaute) unter `### Added`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- license_gate
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
- Laufwerk fehlt → Sitzung ohne Laufwerk mit Hinweis statt Abbruch (Spec, Trade-offs).
- `audio` ungesetzt → lokal, wie der Standard des OS-Clients.
