# Eingebettetes RDP: Live-Spec Stufe 5, H.264 unter Linux — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-5 · Review: pro Task
Spec: docs/features/kern-rdp-5.md (Roadmap R-1101, R-1102)
Heavy: linux-full — Desktop-Journeys: die Live-Spec Abdocken/Multi-Monitor gegen den xrdp-Container läuft im Sammellauf; neue Abhängigkeiten im Desktop-Build (ironrdp-egfx mit libloading, bzip2); Windows über die Windows-CI-Jobs
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1101: Live-Spec Abdocken und Multi-Monitor  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/rdp-embedded.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @7da1335e1 2026-11-09T06:00:09+01:00
Review: approve (.ah-out/review/kern-rdp-5/T1.verdict.json)
Änderung: Den Patch aus kern-rdp-4 T11 anwenden (tasks/private/carry/kern-rdp-5-T11-rdp-embedded-spec.patch): gegen den xrdp-Container zeigt Abdocken das Bild im neuen Fenster ohne `reconnecting`, Andocken holt es zurück, die Sitzung ist dieselbe; Multi-Monitor nur, wenn der Webdriver-Treiber zwei Bildschirme sieht, sonst der Hinweis-Pfad. Dritte Prüfrunde mit frischem Prüfer (Kevin 2026-11-09), höchstens zwei Runden in diesem Zug.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Abdocken und Multi-Monitor dokumentiert mit kern-rdp-4)

### T2 — R-1102: OpenH264 von Cisco laden und als H.264-Dekoder nutzen (Linux)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/openh264.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/rdp_embedded/license_gate.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/main.rs
Änderung: Neues Modul `openh264.rs` (SPDX-Header) mit gepinnter URL `https://ciscobinary.openh264.org/libopenh264-2.6.0-linux64.8.so.bz2` und dem SHA-256 der entpackten Datei; Laden über reqwest, Entpacken mit einem reinen Rust-bzip2, Hash prüfen, atomar ins App-Datenverzeichnis schreiben; Löschen als Befehl `openh264_remove`. `Settings.rdp_h264` (Serde-Default `true`). `config()` setzt unter Linux mit `rdp_h264` den Dekoder über `OpenH264Decoder::from_library_path` (`ironrdp-egfx`, Feature `openh264-libloading`, nur `target_os = "linux"`); fehlt die Datei, lädt der Sitzungsstart sie mit kurzer Frist, scheitert das, läuft die Sitzung ohne H.264. Das Lizenz-Gate prüft statt der Abwesenheit von `openh264-sys2` die Abwesenheit seines Features `source`. Tests: falscher Hash wird abgelehnt und nicht geschrieben, Löschen, Standard der Einstellung, Rundlauf Kodieren/Dekodieren mit dem echten Cisco-Binary.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4
Test-Löschung: apps/desktop/src-tauri/src/rdp_embedded/license_gate.rs::license_gate_openh264_sys2_is_not_built — ersetzt durch ein Gate gegen das Feature `source` von openh264-sys2: R-1102 (Kevin 2026-11-02) lädt Ciscos Binary, damit ist der Crate selbst unter Linux im Graph, die C-Quellen nicht

### T3 — R-1102: Schalter H.264 in den RDP-Einstellungen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/components/settings/RdpSection.svelte, apps/desktop/ui/src/components/settings/RdpSection.test.ts, apps/desktop/ui/src/components/settings/SettingsDialog.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/bridge/index.ts
Änderung: `rdpH264` in den Bridge-Typen und im Standard (`true`); in der RDP-Sektion unter Linux ein Schalter „H.264 (OpenH264)“ mit dem Hinweis „OpenH264 Video Codec provided by Cisco Systems, Inc.“ und Ciscos vollem Lizenztext (aufklappbar); Ausschalten ruft beim Speichern `openh264_remove`. Tests: Schalter nur unter Linux, Hinweis und Lizenztext sichtbar, Ausschalten ruft den Befehl.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T4
Abhängt von: T2

### T4 — Doku H.264 unter Linux (DE+EN), Changelog  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/index.html, docs/en/admin/index.html, docs/features/arch-rdp-embedded.md, changelog.d/kern-rdp-5.md, THIRD_PARTY_LICENSES.md
Änderung: Entwickler-Doku: Laden, Hash, Datei, Gate, Befehl `openh264_remove`; Admin-Doku: Schalter, automatischer Download, Lizenzhinweis; Bedingung 7 der Arch-Spec mit Verweis auf R-1102; `THIRD_PARTY_LICENSES.md` neu erzeugt (`scripts/gen-third-party-licenses.sh`); Changelog-Eintrag ASCII.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-rdp-5.md
Task-Review: am Ende
Abhängt von: T2, T3

## Entscheidungen
- 2026-11-09 Kevin: OpenH264 automatisch und Standard an; der Download zur Laufzeit (FAQ: „at install time“) ist hingenommenes Restrisiko. T11 aus kern-rdp-4 darf eine dritte Prüfrunde bekommen.
- 2026-11-09 Geprüft: Cisco bietet `libopenh264-2.6.0-linux64.8.so.bz2` über https; entpackt SHA-256 `2f0cde7c…5d04` = Eintrag in `openh264-sys2` 0.9.9 `src/blobs/hashes.txt`.
