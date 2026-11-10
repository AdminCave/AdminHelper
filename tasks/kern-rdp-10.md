# Eingebettetes RDP: Auflösung einmal, OpenH264-Restfenster, Live-Test nach dem Resize — Task-Ledger
Status: geplant · Branch: feature/kern-rdp-10 · Review: am Ende
Spec: docs/features/kern-rdp-10.md (Roadmap R-1198, R-1278, R-1283)
Heavy: linux-full — der Live-Test xrdp_live_session läuft im CI-Job rdp-embedded und im Teil gui des Sammellaufs; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1198: session_info nutzt die Auflösung aus prepare  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Änderung: `prepare` gibt neben dem `Target` die `ResolvedConnection` zurück; `rdp_session_start` reicht genau sie an `session_info`, der zweite Aufruf von `resolve_connection` entfällt. Die Tests von `prepare` folgen der neuen Rückgabe; ein Test prüft, dass die Auflösung aus `prepare` den Tunnel nennt, den `session_info` zeigt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::tests
Doku: keine (intern)

### T2 — R-1278: Zähler vor dem Lesen der Einstellung festhalten  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/rdp_embedded/openh264.rs, changelog.d/kern-rdp-10.md
Beweis: reviewer kern-rdp-9 branch 2026-11-10, openh264.rs:168 (`removals(&dir)` erst nach dem Lesen von `rdp_h264` in `h264_library`)
Änderung: `openh264::mark(base)` liefert den Zähler; `h264_library` holt ihn vor `load_settings`, `ensure` nimmt ihn entgegen und `install` schreibt nur bei unveränderter Marke. Test (erst rot): Marke holen, `remove`, dann `ensure_on` mit einem Download-Stub bzw. `install` mit der alten Marke: kein Ordner.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::openh264
Doku: changelog.d/kern-rdp-10.md

### T3 — R-1283: Live-Test übersteht das Resize gegen xrdp  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs, changelog.d/kern-rdp-10.md
Beweis: PR #438 Lauf 42796178873 Job 129761820879 (main@8dd290b61 grün): „expected a picture, got Some(Err(Protocol(ResetWithoutClosingHandshake)))“ in der Resize-Phase; xrdp.log: „Core reset done“, „xrdp_egfx_create“, dann „SSL_read … unexpected eof“
Dedup-Key: bug:desktop:session.rs:xrdp_live_session_resize_reset
Änderung: Der Live-Test bekommt einen Logger und gibt beim Abbruch die gemeldete Phase aus. Mit lokaler Reproduktion (frischer Container je Lauf) die Ursache des Abbruchs nach Deactivate/Reactivate finden und beheben; Beweis: wiederholte Läufe von desktop_e2e_rdp_embedded ohne Abbruch, die Zahl steht in `## Entscheidungen`. Liegt die Ursache im Fork, gehört der Fork-Commit samt neuer `rev` (Cargo.toml, Cargo.lock) in diese Task.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::session
Doku: changelog.d/kern-rdp-10.md

## Entscheidungen
