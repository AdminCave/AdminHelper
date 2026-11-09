# Eingebettetes RDP: OpenH264 auf Ciscos aktuelle Version — Task-Ledger
Status: erledigt · Branch: feature/kern-rdp-6 · Review: pro Task
Spec: docs/features/kern-rdp-6.md (Roadmap R-1200)
Heavy: none — kein Stack-, Gateway-, PKI- oder Install-Pfad, keine neue Abhängigkeit; Beweis ist der Rundlauf-Test mit dem echten Cisco-Binary in desktop-rs, Windows über die Windows-CI-Jobs
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1200: OpenH264 2.7.0 pinnen und gegen den eigenen Pin laden  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/openh264.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @e55115733 2026-11-09T10:17:07+01:00
Review: approve (.ah-out/review/kern-rdp-6/T1.verdict.json)
Änderung: Auf dem Fork `AdminCave/IronRDP` (Branch `adminhelper-pin`) ein Commit mit `OpenH264Decoder::from_api` und Test; alle `ironrdp-*` auf die neue Revision, Fork-Kommentar ergänzen. `openh264.rs`: URL, SHA-256 und Dateiname von 2.7.0; `decoder_factory` prüft den Hash der Datei gegen den Pin und lädt über `from_blob_path_unchecked` und `from_api`; `ensure` löscht andere Dateien in `openh264/`. Tests: Rundlauf mit dem echten 2.7.0, Datei mit fremdem Hash wird nicht geladen, eine alte 2.6.0-Datei verschwindet.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T2

### T2 — Doku OpenH264 2.7.0 (DE+EN), Changelog  [x]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-6.md, docs/features/kern-rdp-6.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @2b1a49b48 2026-11-09T10:22:09+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitt „H.264 unter Linux“: Version 2.7.0, zweite Prüfung gegen den eigenen Pin statt der Liste von `openh264-sys2`, alte Dateien werden geräumt; Changelog-Eintrag ASCII unter `### Changed`, ohne Angriffspfad.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-6.md
Task-Review: am Ende
Abhängt von: T1

## Entscheidungen
- 2026-11-09 Geprüft: `openh264-sys2` 0.9.9 (neueste) kennt in `src/blobs/hashes.txt` nur 2.6.0; `from_library_path` von `ironrdp-egfx` lädt über `from_blob_path` mit dieser Liste. Daher der Fork-Konstruktor `from_api` (Spec, Trade-offs).
