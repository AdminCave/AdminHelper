<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-rdp-2 — Eingebettetes RDP Stufe 3: Kanäle im Backend

Roadmap R-1099, R-1092 (Zug `tasks/kern-rdp-2.md`). Stufe 3 aus dem Bauplan von `docs/features/arch-rdp-embedded.md`
(Tabelle „Bauplan für R-1075“, Bedingung 12). Kevins Entscheidung vom 2026-11-06 steht in R-1099: die Kanäle kommen
im Backend aus den Verbindungs-Optionen (`drives`, `audio`), das Laufwerk ist der Downloads-Ordner wie im Mockup, die
Zwischenablage ist standardmäßig an; die Schalter in der Tab-Leiste kommen mit `kern-rdp-1`. Stand
`origin/main@ddfec795`, IronRDP an der gepinnten Revision `f96f664`.

## Problem / Motivation
- **R-1099:** Die eingebettete Sitzung baut keinen Kanal auf: `config()` setzt `ClipboardType::Disable` und
  `with_rdpdr(false)` (`apps/desktop/src-tauri/src/rdp_embedded/session.rs:418-420`), Audio ist nicht gebaut
  (`ironrdp-client` ohne Feature `sound`, `apps/desktop/src-tauri/Cargo.toml:81`). Der OS-Client bekommt dieselben
  Optionen dagegen schon (`connection/rdp.rs:908`, `drivestoredirect`, `audiomode`).
- **R-1092:** Die Probe aus R-1074 T4 endete gegen Windows im Kanal-Lauf mit einem Absturz (Einzelheiten nur
  privat). Bis das geklärt ist, bleibt Audio unter Windows aus (Bedingung 12).

## Ziel & Nicht-Ziele
Ziel:
- Die eingebettete Sitzung liest `options.rdp` der Verbindung:
  - **Zwischenablage** immer an; Text und Bilder, wie die nativen IronRDP-Backends sie tragen, keine Dateien.
  - **Audio:** `local` oder ungesetzt → Wiedergabe lokal, `remote` → auf dem Server, `off` → aus. Das Mikrofon
    bleibt aus. Unter Windows bleibt Audio in jedem Fall aus (Bedingung 12).
  - **Laufwerk:** `drives: true` gibt den Downloads-Ordner des Nutzers als Laufwerk frei, sonst kein Laufwerk.
    Drucker, Ports und Smartcard bleiben aus.
- Lässt sich das Laufwerk nicht anlegen (kein Downloads-Ordner), startet die Sitzung ohne Laufwerk und meldet das
  in der Statusmeldung der Sitzung, statt zu scheitern.
- Das Linux-Paket bringt seine neue Laufzeit-Abhängigkeit (libasound) mit, CI und Release bauen mit
  `libasound2-dev`.
- R-1092 wird auf einem Windows-CI-Lauf reproduziert und eingegrenzt; das Ergebnis bleibt privat.

Nicht-Ziele:
- Schalter in der Tab-Leiste (`kern-rdp-1`, Mockup).
- Freie Wahl des freigegebenen Ordners, mehrere Laufwerke, Dateien über die Zwischenablage (Bauplan „später“).
- `gateway`, `printers` und `nla = false` für die eingebettete Sitzung (sie ignoriert sie weiter; eigene
  Roadmap-Zeile).
- Audio unter Windows freischalten: dafür braucht Bedingung 12 eine Abnahme auf einem Windows mit Audiogerät.

## Betroffene Komponenten & Dateien
- Desktop (Rust): `apps/desktop/src-tauri/Cargo.toml` (Feature `sound`, neue Abhängigkeit `ironrdp-rdpdr-native`
  an derselben Revision), `Cargo.lock`, `src/rdp_embedded/session.rs` (`Target`, `config()`, `start_attempt()`),
  `src/rdp_embedded/mod.rs` (`prepare()` übernimmt die Optionen, `rdp_session_start` den Downloads-Ordner über
  `app.path().download_dir()`), `src/rdp_embedded/license_gate.rs` (Gates bleiben, Abhängigkeiten neu bewertet).
- Paketierung und CI: `apps/desktop/src-tauri/tauri.conf.json` (deb/rpm-Abhängigkeit), `.github/workflows/ci.yml`
  und `.github/workflows/release.yml` (`libasound2-dev`), `scripts/vm/bootstrap_linux.sh:118`, `DEVELOPMENT.md`.
- Doku: `docs/developer/desktop.html:250` (DE+EN), `THIRD_PARTY_LICENSES.md`, `changelog.d/kern-rdp-2.md`.

## Datenmodell / API / Migrationen
Kein neues Feld, keine Migration, kein neuer Tauri-Befehl. Die Optionen `drives` und `audio` gibt es seit
`kern-verbindungen-3` (`models.rs`, `RdpConnectionOptions`); die eingebettete Sitzung liest sie jetzt auch.

## Externe Integrationen
- IronRDP (`f96f664`): `ironrdp_client::ConfigBuilder::with_clipboard`, `with_sound`, `with_audio_mode`
  (`ironrdp_cfg::AudioMode`), `with_audio_capture`, `with_rdpdr`, `with_drive_redirection`;
  `RdpClient::with_cliprdr_backend_factory` und `with_rdpdr_backend_factory`; `ironrdp-rdpdr-native`
  (`NixRdpdrBackendFactory`, `WindowsRdpdrBackendFactory`); `ironrdp-cliprdr-native::WinClipboard::new`. Gelesen im
  Quelltext der Revision. Ohne eigene Fabrik nähme `ClipboardType::Enable` unter Windows ein Backend mit
  Dateiübertragung; der Desktop setzt deshalb dort eine eigene Fabrik ohne Dateien.
- `AudioMode::PlayOnServer` setzt an dieser Revision kein `INFO_REMOTECONSOLEAUDIO`; `remote` wirkt damit wie aus,
  bis IronRDP es verdrahtet (MS-RDPBCGR 2.2.1.11.1.1, nicht verifiziert gegen einen Server).
- CPAL nutzt unter Linux ALSA (`libasound2`). Tauri-Bundler: `bundle.linux.deb.depends`, `bundle.linux.rpm.depends`
  (<https://v2.tauri.app/reference/config/#debconfig>); vor der Task gegen die Doku prüfen.

## Trade-offs & Alternativen
- **Laufwerk fehlt → Sitzung ohne Laufwerk** statt Abbruch: Der Nutzer kommt auf den Server; die Statusmeldung
  nennt den Grund. Empfohlen.
- **Zwischenablage mit Bildern:** Die nativen Backends tragen Text und Bilder; nur Text verlangte einen eigenen
  Filter um beide Backends. Empfehlung: Bilder mitnehmen (Offene Frage 1).
- **Audio-Standard an** (`audio` ungesetzt → lokal) wie der OS-Client (`audiomode:i:0` ist dort Standard).

## Risiken & Rollback
- **Neue Laufzeit-Abhängigkeit unter Linux:** Fehlt libasound, startet der Desktop nicht. Das Paket nennt sie;
  AppImage nicht verifiziert.
- **Laufwerk:** schreibbarer Zugriff des Servers auf den Downloads-Ordner (Risikopfad, `security`). IronRDP
  verhindert Pfade außerhalb der Wurzel (`openat2` ohne Symlinks unter Linux), unter Windows nicht verifiziert.
- **Code hinter FFI** (CPAL) im App-Prozess (Restrisiko der Architektur-Spec).
- Rollback per Revert der Task-Commits; Daten ändern sich nicht.

## Doku-Impact
`docs/developer/desktop.html` DE+EN (Abschnitt „Eingebettetes RDP (Backend)“: Kanäle), `DEVELOPMENT.md`
(`libasound2-dev`), `THIRD_PARTY_LICENSES.md` (neue Crates), `changelog.d/kern-rdp-2.md`.

## Offene Fragen
1. Zwischenablage: Text und Bilder (Empfehlung, native Backends) oder nur Text (eigener Filter)?
2. R-1092: Die Windows-Probe läuft als GitHub-Actions-Lauf; im öffentlichen Repo sind Lauf und Log öffentlich
   sichtbar. Empfehlung: ein privates Wegwerf-Repo unter `AdminCave` (Windows-Minuten zählen dort doppelt), nach
   dem Lauf gelöscht. Kevins Entscheidung (Restrisiko, Kosten).
