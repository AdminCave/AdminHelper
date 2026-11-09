# Eingebettetes RDP: Live-Spec Stufe 5 und H.264 unter Linux

Zug `kern-rdp-5`, Roadmap R-1101 (Rest: Live-Spec) und R-1102 (H.264 unter Linux). Grundlage: Bauplan in
`docs/features/arch-rdp-embedded.md` (Bedingung 7, K1, K11), Stufe 4 und 5 aus `kern-rdp-4` (PR #420).

## Problem / Motivation

- **R-1101:** Der Code für Abdocken und zwei Monitore kam mit `kern-rdp-4`. Es fehlt die Live-Spec gegen den
  xrdp-Container (kern-rdp-4 T11, verschoben: die dritte Prüfrunde brauchte Kevins Wort, erteilt 2026-11-09).
- **R-1102:** Unter Linux dekodiert der eingebettete Client kein H.264 (Bedingung 7: kein aus Quellen gebautes
  OpenH264, es trägt keine Patentlizenz). Gegen Windows fällt die Sitzung deshalb auf RemoteFX Progressive zurück:
  bei gleicher Bandbreite 36–65 % Qualität und 67–79 % eines Kerns statt 100 % und rund 40 % (T4 der Arch-Spec).
  Kevin 2026-11-02: H.264 unter Linux über Ciscos Binary, zur Laufzeit geladen.

## Ziel & Nicht-Ziele

Ziel:
- Die Live-Spec `rdp-embedded.live.js` deckt Abdocken, Andocken und den Hinweis-Pfad für zwei Monitore ab.
- Unter Linux lädt der Desktop Ciscos `libopenh264-2.6.0-linux64.8.so` von `ciscobinary.openh264.org` (https),
  prüft den SHA-256 gegen den einen gepinnten Wert und legt die Datei ins App-Datenverzeichnis. Der Dekoder entsteht
  über `OpenH264Decoder::from_library_path` (`ironrdp-egfx`, Feature `openh264-libloading`); `openh264-sys2` prüft
  den Hash beim Laden ein zweites Mal gegen seine Liste (`src/blobs/hashes.txt`).
- **Standard an, automatisch** (Kevin 2026-11-09): Die erste eingebettete RDP-Sitzung lädt das Binary, wenn es
  fehlt. Ein Schalter in den Einstellungen („RDP“) schaltet H.264 ab und löscht die Datei, Einschalten lädt sie neu.
  Am Schalter steht „OpenH264 Video Codec provided by Cisco Systems, Inc.“ und Ciscos Lizenztext.
- Windows bleibt bei Media Foundation; der Schalter erscheint nur unter Linux.

Nicht-Ziele: kein gebündeltes oder aus Quellen gebautes OpenH264; kein Encoder; kein Download beim Paket-Install
(`.deb`-Postinst); keine weiteren Plattformen (macOS baut der Desktop nicht).

## Betroffene Komponenten & Dateien

- `apps/desktop/e2e/test/specs/rdp-embedded.live.js` (R-1101, Patch aus kern-rdp-4 T11).
- `apps/desktop/src-tauri/Cargo.toml`, `Cargo.lock`: `ironrdp-egfx` (Fork-Revision wie die übrigen `ironrdp-*`) nur
  für `target_os = "linux"` mit `openh264-libloading`, dazu ein bzip2-Dekoder (Cisco liefert `.so.bz2`).
- `apps/desktop/src-tauri/src/rdp_embedded/openh264.rs` (neu, SPDX): URL, Hash, Laden, Löschen, Status.
- `apps/desktop/src-tauri/src/rdp_embedded/session.rs` (`config()`, `ConfigBuilder::with_h264_decoder`),
  `rdp_embedded/mod.rs` (Modul, Befehl), `main.rs` (Befehl registrieren).
- `apps/desktop/src-tauri/src/models.rs`: `Settings.rdp_h264: bool`, Standard `true`.
- `apps/desktop/src-tauri/src/rdp_embedded/license_gate.rs`: das Gate gegen `openh264-sys2` wird zum Gate gegen
  dessen Feature `source` (die C-Quellen von OpenH264).
- `apps/desktop/ui/src/lib/bridge/types.ts`, `lib/models/settings.ts`, `components/settings/RdpSection.svelte`,
  `SettingsDialog.svelte`, `lib/i18n/dictionaries.ts`.
- `THIRD_PARTY_LICENSES.md` (neu erzeugt: bzip2-Crate, `openh264`-Crates).

## Datenmodell / API / Migrationen

- Keine Alembic-Migration, kein Server- oder Web-Vertrag. `settings.json` bekommt `rdp_h264` mit Serde-Default
  `true`; ältere Dateien lesen sich weiter.
- Tauri-IPC: Feld `rdpH264` in `Settings` (Bridge-Typen), Befehl `openh264_remove` (löscht die Datei beim
  Ausschalten).

## Externe Integrationen

- Cisco: `https://www.openh264.org/BINARY_LICENSE.txt` (Bedingungen: eigener Download auf das Gerät, Nutzer kann
  ein- und ausschalten, Hinweis am Schalter, voller Lizenztext dort, wo Lizenzen stehen; nicht vorab gebündelt),
  `https://www.openh264.org/faq.html`. Binary `https://ciscobinary.openh264.org/libopenh264-2.6.0-linux64.8.so.bz2`,
  geprüft 2026-11-09: entpackt SHA-256 `2f0cde7c6a6abcf5cae76942894ea42897fa677bce4ed6c91a24dd1b041d5f04`, gleich
  dem Eintrag in `openh264-sys2` 0.9.9 `src/blobs/hashes.txt`.
- `ironrdp-egfx` (Fork): `OpenH264Decoder::from_library_path`; `ironrdp-client`: `H264DecoderFactory::new`,
  `ConfigBuilder::with_h264_decoder`.

## Trade-offs & Alternativen

- **Auslöser:** automatisch und Standard an (Kevins Wahl) gegen Schalter mit Standard aus oder eine vom Nutzer
  gewählte Datei. Die FAQ nennt den Download „at the time the product … is installed“; der Download zur Laufzeit
  ist ein Restrisiko, das Kevin 2026-11-09 hingenommen hat.
- **Wann geladen:** beim Start einer Sitzung mit kurzer Frist (die Datei hat rund 0,6 MB), scheitert er, läuft die
  Sitzung ohne H.264 und die nächste versucht es erneut. Ein Laden im Hintergrund beim App-Start würde ohne
  RDP-Nutzung Netz kosten.
- **bzip2:** reiner Rust-Dekoder statt `libbz2` über C, damit kein weiterer C-Build in den Desktop kommt.

## Risiken & Rollback

- Fremder nativer Code im Prozess: nur die eine Datei mit gepinntem Hash, geprüft vor dem Schreiben und beim
  Laden; Schreiben atomar (temporäre Datei, dann umbenennen). `security` prüft T2.
- Ein falscher Dekoder würde das Bild zerstören: ein Rundlauf-Test kodiert ein Bild mit dem Cisco-Binary und
  dekodiert es über `OpenH264Decoder`. Gegen Windows (AVC) ist er im Pool nicht live prüfbar (xrdp sendet kein
  H.264), nicht verifiziert bis R-0541.
- Rollback: Schalter aus; im Code `with_h264_decoder(None)`.

## Doku-Impact

`docs/developer/desktop.html` und `docs/admin/index.html` (DE+EN): H.264 unter Linux, Schalter, Download,
Lizenzhinweis; Bedingung 7 in `docs/features/arch-rdp-embedded.md` mit Verweis auf R-1102;
`changelog.d/kern-rdp-5.md`.

## Offene Fragen

Keine (Auslöser und dritte Prüfrunde: Kevin 2026-11-09).
