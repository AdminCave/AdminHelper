# Eingebettetes RDP: Sitzungsende ohne Anzeige, Umleitungen, TLS-Schlüssel — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-8 · Review: pro Task
Spec: docs/features/kern-rdp-8.md (Roadmap R-1199, R-1145)
Heavy: none — kein Stack-, Gateway-, PKI- oder Install-Pfad; die Desktop-GUI-Journeys starten keine eingebettete RDP-Sitzung gegen einen Server
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1199: Eine Sitzung ohne Client endet nach einer Frist  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs
Änderung: `serve` startet eine Frist (`NO_CLIENT_DEADLINE`, 60 s, im Server einstellbar wie `login_deadline`), sobald kein Bildschirm einen streamenden Client hat, und hebt sie mit dem nächsten Login auf; läuft sie ab, endet `serve` wie nach `close`. Tests: ohne Client endet `serve` nach der Frist; ein Client, der geht und innerhalb der Frist wiederkommt, hält die Sitzung; ein streamender Client hält sie über die Frist hinaus.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T2 — R-1145: Der RDP-Client folgt keiner Server-Umleitung  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/rdp_embedded/session.rs
Änderung: Im Fork `AdminCave/IronRDP` (Branch `adminhelper-pin`) ein Commit: `ironrdp-client` bekommt einen Konfigurationsschalter, mit dem `follow_server_redirection` einen Fehler liefert, bevor `config.destination` sich ändert; Test im Fork. Alle `ironrdp-*` auf die neue Revision, Fork-Kommentar ergänzen. `session.rs` schaltet das Folgen ab; Test auf die gebaute Konfiguration.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T3 — R-1145: Die App schreibt keine TLS-Sitzungsschlüssel  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/main.rs
Änderung: `main` nimmt `SSLKEYLOGFILE` vor dem ersten Thread aus der Umgebung (eigene Funktion, Test: gesetzt → danach nicht gesetzt).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T4 — Doku: Sitzung ohne Client, Umleitung, Schlüssel-Log (DE+EN), Changelog  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-8.md
Änderung: Bild-Server-Absatz: eine Sitzung ohne Client endet nach 60 s; Callback-Liste: der Client folgt keiner Umleitung, die App startet ohne `SSLKEYLOGFILE`. Changelog in ASCII, ohne Angriffspfad.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-8.md
Task-Review: am Ende
Abhängt von: T1, T2, T3

## Entscheidungen
- Plan: R-1199 über die Frist aus der Roadmap-Zeile, 60 s; das Beenden beim Start von main (kern-rdp-4) bleibt.
