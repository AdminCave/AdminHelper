# Eingebettetes RDP: Gateway, Drucker, NLA; Windows-Probe — Task-Ledger
Status: bereit · Branch: feature/kern-rdp-3 · Review: am Ende
Spec: docs/features/kern-rdp-3.md (Roadmap R-1163, R-1092)
Heavy: linux-full + windows — linux-full: `config()` der eingebetteten Sitzung ändert sich, `desktop_e2e_rdp_embedded` (xrdp-Container) fährt im Sammellauf; windows = die CI-Jobs `rust-windows` und `tauri-build-smoke` (der Pool hat keine Windows-Vorlage)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Desktop: Gateway und Drucker an den OS-Client, NLA aus ohne CredSSP (R-1163)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/mod.rs, apps/desktop/src-tauri/src/rdp_embedded/session.rs, apps/desktop/src-tauri/src/error.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-3.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @73bfb9b54 2026-11-08T08:59:20+01:00
Review: am Ende (Branch-Review)
Änderung: `prepare()` lehnt eine Verbindung mit gesetztem `gateway` oder `printers: true` mit der neuen `AppError`-Variante ab (Code `ERR_RDP_OS_CLIENT`, Text nennt den Grund); `Target` trägt `credssp` (`nla != Some(false)`), `config()` setzt `with_credssp(target.credssp)`. Tests: Ablehnung je Grund samt Code, `printers: false` startet, `nla: false` baut einen Connector ohne CredSSP. Doku: Fehlervertrag und Absatz „Kanäle“ DE+EN, Changelog.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-3.md

### T2 — R-1092: Windows-Probe des Absturzes reproduzieren und eingrenzen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @d16d0fdc6 2026-11-08T09:57:58+01:00
Review: am Ende (Branch-Review)
Änderung: Die Probe aus R-1074 T4 an IronRDP `f96f664` in einem privaten Wegwerf-Repo unter `AdminCave` auf einem Windows-Runner (Kevin 2026-11-06/2026-11-08), mit Absturzabbild und Varianten, die die Kanäle einzeln abschalten; Ergebnis und Logs nur unter `tasks/private/spikes/`, das Repo danach gelöscht. Liegt die Ursache in Fremdcode: Mail-Entwurf unter `tasks/private/`, Kevin schickt ab. Im Baum ändert sich nur der Kommentar am Windows-Gate von `audio_mode()` (neutral, Verweis auf R-1092); Audio unter Windows bleibt aus.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded
Doku: keine (Ergebnis privat)
Abhängt von: T1

## Entscheidungen
- 2026-11-08 T1: IronRDP f96f664 hat einen RD-Gateway-Client hinter dem Feature `gateway` (ironrdp-mstsgu); der Rueckfall auf den OS-Client bleibt (Kevin 2026-11-08), der Gateway-Weg ist R-1191
- 2026-11-08 T2: Absturz 5/5 reproduziert, Ursache in Fremdcode und dort schon öffentlich gemeldet (Einzelheiten nur privat); kein Mail-Entwurf, ein Kommentar-Entwurf für Kevin; Umweg ist R-1192
