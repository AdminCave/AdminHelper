# Eingebettetes RDP: Auflösung einmal, OpenH264-Restfenster, Live-Test nach dem Resize — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-10 · Review: am Ende
Spec: docs/features/kern-rdp-10.md (Roadmap R-1198, R-1278, R-1283)
Heavy: linux-full — der Live-Test xrdp_live_session läuft im CI-Job rdp-embedded und im Teil gui des Sammellaufs; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1198: session_info nutzt die Auflösung aus prepare  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @441536207 2026-11-10T19:05:43+01:00
Review: am Ende (Branch-Review)
Änderung: `prepare` gibt neben dem `Target` die `ResolvedConnection` zurück; `rdp_session_start` reicht genau sie an `session_info`, der zweite Aufruf von `resolve_connection` entfällt. Die Tests von `prepare` folgen der neuen Rückgabe; ein Test prüft, dass die Auflösung aus `prepare` den Tunnel nennt, den `session_info` zeigt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::tests
Doku: keine (intern)

### T2 — R-1278: Zähler vor dem Lesen der Einstellung festhalten  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/rdp_embedded/openh264.rs, changelog.d/kern-rdp-10.md
Beweis: reviewer kern-rdp-9 branch 2026-11-10, openh264.rs:168 (`removals(&dir)` erst nach dem Lesen von `rdp_h264` in `h264_library`)
Änderung: `openh264::mark(base)` liefert den Zähler; `h264_library` holt ihn vor `load_settings`, `ensure` nimmt ihn entgegen und `install` schreibt nur bei unveränderter Marke. Test (erst rot): Marke holen, `remove`, dann `ensure_on` mit einem Download-Stub bzw. `install` mit der alten Marke: kein Ordner.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::openh264
Doku: changelog.d/kern-rdp-10.md

### T3 — R-1283: Live-Test übersteht das Resize gegen xrdp  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs, changelog.d/kern-rdp-10.md, apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f8764330f 2026-11-10T19:04:32+01:00
Review: am Ende (Branch-Review)
Beweis: PR #438 Lauf 42796178873 Job 129761820879 (main@8dd290b61 grün): „expected a picture, got Some(Err(Protocol(ResetWithoutClosingHandshake)))“ in der Resize-Phase; xrdp.log: „Core reset done“, „xrdp_egfx_create“, dann „SSL_read … unexpected eof“
Dedup-Key: bug:desktop:session.rs:xrdp_live_session_resize_reset
Änderung: Der Live-Test bekommt einen Logger und gibt beim Abbruch die gemeldete Phase aus. Mit lokaler Reproduktion (frischer Container je Lauf) die Ursache des Abbruchs nach Deactivate/Reactivate finden und beheben; Beweis: wiederholte Läufe von desktop_e2e_rdp_embedded ohne Abbruch, die Zahl steht in `## Entscheidungen`. Liegt die Ursache im Fork, gehört der Fork-Commit samt neuer `rev` (Cargo.toml, Cargo.lock) in diese Task.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::session
Doku: changelog.d/kern-rdp-10.md

## Entscheidungen
- 2026-11-10 T3: Ursache im Fork: xrdp sendet waehrend Deactivate/Reactivate PDUs auf statischen Kanaelen, `ConnectionActivationSequence` dekodierte jedes MCS-SDI als I/O-PDU und brach ab (Laenge 0x0400 sogar als Redirection gelesen) — Fork-Commit 2f1f0e30 stellt solche Frames zurueck, `ironrdp-client` verarbeitet sie nach der Finalisierung in Reihenfolge; Verwerfen haette Kanaldaten (rdpdr, cliprdr) verloren
- 2026-11-10 T3: in der Erstverbindung werden zurueckgestellte Kanal-Frames nicht nachgereicht, nur nicht mehr zum Fehler — der Message-Kanal faengt connection.rs vorher ab, ein eigener Nachreich-Pfad dort waere neue Fork-Flaeche ohne Befund
- 2026-11-10 T3: Beweis lokaler Repro (frischer xrdp-Container je Lauf, xrdp_live_session): vor dem Fix 1 von 15 rot, mit rev 2f1f0e30 0 von 30 rot; Fork-Test channel_pdu_during_activation_is_deferred rot ohne die Weiche
