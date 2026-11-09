# Eingebettetes RDP: OpenH264 auf Ciscos aktuelle Version

Zug `kern-rdp-6`, Roadmap R-1200. Grundlage ist `kern-rdp-5` (PR #421, R-1102). Seitdem lädt der Desktop unter Linux
Ciscos OpenH264-Binary und nutzt es als H.264-Dekoder.

## Problem / Motivation

Gepinnt ist `libopenh264-2.6.0-linux64.8.so`. Am 2026-10-22 hat Cisco 2.7.0 veröffentlicht, mit Korrekturen im
Dekoder; Details stehen in der privaten Roadmap. Der Pin steigt nur mit einem App-Release. Der Desktop soll deshalb
Ciscos aktuelle Version laden (Kevin 2026-11-09: 2.6.0 mergen, den Wechsel als nächsten Kern-Zug).

Was im Weg steht: `OpenH264Decoder::from_library_path` (`ironrdp-egfx`) lädt über
`openh264::OpenH264API::from_blob_path`. Diese Funktion lädt nur Dateien, deren SHA-256 in der Liste von
`openh264-sys2` steht (`src/blobs/hashes.txt`). In 0.9.9, der neuesten Version, stehen dort nur 2.6.0-Binaries
(geprüft 2026-11-09).

## Ziel & Nicht-Ziele

Ziel:
- `openh264.rs` pinnt `libopenh264-2.7.0-linux64.8.so.bz2` und den SHA-256 der entpackten Datei. Der Hash steht in
  Ciscos `libopenh264-2.7.0-linux64.8.so.signed.sha256.txt` und stimmt mit zwei eigenen Downloads über https überein.
- Der Dekoder lädt die Bibliothek ohne die Liste von `openh264-sys2`. Er nutzt `OpenH264API::from_blob_path_unchecked`,
  davor steht unsere eigene Prüfung gegen den einen gepinnten Hash. Damit gilt die zweite Hash-Prüfung beim Laden
  weiter, nur gegen unseren Pin.
- Ältere Bibliotheken im Ordner `openh264/` werden beim nächsten Laden gelöscht, so bleibt 2.6.0 nicht liegen.
- Der Rundlauf-Test (kodieren und dekodieren mit dem echten Cisco-Binary) beweist, dass 2.7.0 zu den Bindings
  passt. Die ABI-Nummer ist dieselbe (`.8`), die Struktur-Kompatibilität ist nicht verifiziert, bis der Test grün ist.

Nicht-Ziele: kein Wechsel der Lieferweise (Laufzeit-Download bleibt), kein Upstream-PR (Kevins Wort), keine
Aktualisierung zur Laufzeit ohne Release.

## Betroffene Komponenten & Dateien

- Fork `AdminCave/IronRDP`, Branch `adminhelper-pin`: ein Commit in `crates/ironrdp-egfx/src/decode.rs`, der
  `OpenH264Decoder::from_api(api: openh264::OpenH264API)` ergänzt (Feature `openh264-libloading`), mit Test in
  der IronRDP-Suite. `from_library_path` bleibt unverändert.
- `apps/desktop/src-tauri/Cargo.toml`, `Cargo.lock`: alle `ironrdp-*` auf die neue Fork-Revision; Kommentar zum
  Fork um den dritten Commit ergänzen.
- `apps/desktop/src-tauri/src/rdp_embedded/openh264.rs`: URL, Hash, Dateiname; `decoder_factory` prüft den Hash
  und lädt per `from_blob_path_unchecked` und `from_api`; `ensure` räumt fremde Dateien im Ordner; Tests.
- Doku: `docs/developer/desktop.html` und `docs/en/developer/desktop.html` (Abschnitt „H.264 unter Linux“),
  `changelog.d/kern-rdp-6.md`.

## Datenmodell / API / Migrationen

Keine Einstellung, kein Befehl und kein IPC ändert sich. Auf der Platte: Die Datei unter `openh264/` heißt künftig
`libopenh264-2.7.0-linux64.8.so`. Die alte Datei löscht `ensure`.

## Externe Integrationen

- Cisco: `https://ciscobinary.openh264.org/libopenh264-2.7.0-linux64.8.so.bz2` antwortete am 2026-11-09 mit 200.
  Release-Notizen: https://github.com/cisco/openh264/releases/tag/v2.7.0
- `openh264-sys2` 0.9.9: `from_blob_path_unchecked` ist `unsafe` und verlangt, dass die Datei zur Plattform und zur
  Version der Bindings passt. Den ersten Teil sichert unser Pin, den zweiten der Rundlauf-Test.

## Trade-offs & Alternativen

- **Fork-Konstruktor `from_api` (Empfehlung):** Der Eingriff ist klein und additiv, der Dekoder-Code von IronRDP
  (Annex B, YUV) bleibt eine Quelle.
- Eigener `H264Decoder` direkt über den Crate `openh264`: kein Fork-Commit, aber eine Kopie der
  Umwandlungslogik aus `decode.rs`. Diese Kopie driftet.
- Warten auf ein `openh264-sys2` mit 2.7.0 in der Liste: Ein Termin ist nicht bekannt, der Pin bliebe offen.

## Risiken & Rollback

- Weicht die ABI von 2.7.0 von den Bindings ab, schlägt der Rundlauf-Test fehl. Dann bleibt der Pin bei 2.6.0, und
  die Zeile geht mit Befund an Kevin.
- `unsafe`-Aufruf: Er ist nur mit vorheriger Hash-Prüfung erreichbar. Die Prüfung und der Aufruf stehen in einer
  Funktion, die der Test abdeckt.
- Rollback: die Task-Commits per `git revert`; die alte Fork-Revision bleibt im Fork-Branch erreichbar.

## Doku-Impact

Entwickler-Doku DE+EN, Abschnitt „H.264 unter Linux“: Version, zweite Prüfung gegen den eigenen Pin, Aufräumen alter
Dateien. Admin-Doku nennt keine Version (geprüft) und bleibt. Changelog: Eintrag unter `### Changed`.

## Offene Fragen

Keine. Ein Upstream-PR zu `from_api` ist Kevins Wort und gehört nicht zu diesem Zug.
