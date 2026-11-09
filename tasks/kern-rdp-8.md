# Eingebettetes RDP: Sitzungsende ohne Anzeige, Umleitungen, TLS-Schlüssel — Task-Ledger
Status: erledigt · Branch: feature/kern-rdp-8 · Review: pro Task
Spec: docs/features/kern-rdp-8.md (Roadmap R-1199, R-1145)
Heavy: none — kein Stack-, Gateway-, PKI- oder Install-Pfad; die Desktop-GUI-Journeys starten keine eingebettete RDP-Sitzung gegen einen Server
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1199: Eine Sitzung ohne Client endet nach einer Frist  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @fc4d39478 2026-11-09T14:34:33+01:00
Review: approve (.ah-out/review/kern-rdp-8/T1.verdict.json)
Änderung: `serve` startet eine Frist (`NO_CLIENT_DEADLINE`, 60 s, im Server einstellbar wie `login_deadline`), sobald kein Bildschirm einen streamenden Client hat, und hebt sie mit dem nächsten Login auf; läuft sie ab, endet `serve` wie nach `close`. Tests: ohne Client endet `serve` nach der Frist; ein Client, der geht und innerhalb der Frist wiederkommt, hält die Sitzung; ein streamender Client hält sie über die Frist hinaus.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T2 — R-1145: Der RDP-Client folgt keiner Server-Umleitung  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/session.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @767e46700 2026-11-09T14:54:13+01:00
Review: approve (.ah-out/review/kern-rdp-8/T2.verdict.json)
Änderung: Im Fork `AdminCave/IronRDP` (Branch `adminhelper-pin`) ein Commit: `ironrdp-client` bekommt einen Konfigurationsschalter, mit dem `follow_server_redirection` einen Fehler liefert, bevor `config.destination` sich ändert; Test im Fork. Alle `ironrdp-*` auf die neue Revision, Fork-Kommentar ergänzen. `session.rs` schaltet das Folgen ab; Test auf die gebaute Konfiguration.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T3 — R-1145: Die App schreibt keine TLS-Sitzungsschlüssel  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/rdp_embedded/tofu.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5ceebc546 2026-11-09T14:59:15+01:00
Review: approve (.ah-out/review/kern-rdp-8/T3.verdict.json)
Änderung: `main` nimmt `SSLKEYLOGFILE` vor dem ersten Thread aus der Umgebung (eigene Funktion, Test: gesetzt → danach nicht gesetzt).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T4 — Doku: Sitzung ohne Client, Umleitung, Schlüssel-Log (DE+EN), Changelog  [x]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-8.md, docs/features/kern-rdp-8.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @8569634a5 2026-11-09T15:05:42+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Bild-Server-Absatz: eine Sitzung ohne Client endet nach 60 s; Callback-Liste: der Client folgt keiner Umleitung, die App startet ohne `SSLKEYLOGFILE`. Changelog in ASCII, ohne Angriffspfad.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-8.md
Task-Review: am Ende
Abhängt von: T1, T2, T3

## Entscheidungen
- Plan: R-1199 über die Frist aus der Roadmap-Zeile, 60 s; das Beenden beim Start von main (kern-rdp-4) bleibt.
