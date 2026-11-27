# Desktop-Zuverlaessigkeit: Sitzung, Zertifikat, Tunnel, RDP, SFTP, Ping, Feed — Task-Ledger
Status: geplant · Branch: feature/kern-desktop-6 · Review: pro Task
Spec: docs/features/kern-desktop-6.md (Roadmap R-1709, R-1689, R-1691, R-1707, R-1708, R-1710, R-1711)
Heavy: linux-full — Desktop-Journeys (Login, Tunnel, Verbindungen) und Web-Client-Auth; kein Stack-, PKI-Server- oder Install-Pfad geaendert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27 (Notizen der sieben Zeilen): alle angenommen; R-1709 Transportfehler, 502, 503, 504 beenden die Sitzung nicht, 400/401/500 weiter; R-1710 Einstellung je Workspace, Standard an.
- Plan: die eigene Frist der Erneuerung (Desktop 30 s) und ein Timeout beenden die Sitzung weiter, Desktop und Web gleich; der Grund (rotiertes Token) steht schon im Code und in der Doku, `a_renewal_past_the_deadline_ends_the_session` bleibt.
- Plan: R-1691 liest den Login-Zustand aus den frpc-Logzeilen (frp v0.72.0 client/service.go:369-389), nicht aus `/api/status` (kein Login-Zustand dort) und nicht per Bind-Probe.
- Plan: R-1689 ein Code `ERR_DEVICE_CERT_INVALID` fuer beide Wege (lokal abgelaufen, nginx-495-Seite).

### T1 — Erneuerung: Transportfehler und 502/503/504 behalten die Sitzung, Desktop (R-1709)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/session.rs, apps/desktop/src-tauri/src/auth.rs
Änderung: `try_refresh` unterscheidet einen Fehlschlag ohne Urteil des Servers (Transportfehler ausser Timeout, 502, 503, 504) von einer Ablehnung; `send_renewing` behält bei ersterem Slot und Generation, sendet kein Ablauf-Ereignis und gibt einen Verbindungsfehler zurück (nicht `SessionExpired`). Tests: 502/503/504 und ein nicht erreichbarer Server lassen die Sitzung stehen, ein spaeteres 401 mit gelungener Erneuerung wiederholt; `a_failed_renewal_ends_the_session` (400/401/500) und die Fristen-Tests bleiben.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session::
Doku: → T12

### T2 — Erneuerung: Netzfehler und 502/503/504 behalten die Sitzung, Web (R-1709)  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts
Änderung: `tryRefresh` liefert drei Ausgaenge (erneuert, abgelehnt, nicht erreichbar); bei „nicht erreichbar“ (fetch-TypeError, 502, 503, 504) wirft `request` einen `ApiError` mit dem Status bzw. 503, ohne `onAuthFailure`; ein Timeout gilt als abgelehnt wie bisher. Tests in `client.test.ts` je Ausgang, der bestehende Fehlschlag-Test bleibt fuer 401/400/500.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts
Doku: → T12

### T3 — Abgelaufenes Geraete-Zertifikat: stabiler Code vor und nach dem Senden (R-1689)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/auth.rs, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/error.rs
Änderung: neuer `AppError::DeviceCertInvalid` (`ERR_DEVICE_CERT_INVALID`); `login` prueft bei gehaltener Identitaet das Leaf (`not_after` <= jetzt, testbare Funktion mit `now`) und sendet dann nichts; `login_failure` erkennt 400 mit „The SSL certificate error“ (nginx 495). Tests: Leaf-Pruefung mit Zeit vor/nach Ablauf, `login_failure` fuer beide nginx-Seiten, Code-Tabelle in `error.rs`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- auth::
Doku: → T12

### T4 — Login-Hinweis fuer ein ungueltiges Geraete-Zertifikat (R-1689)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/Login.revoked.test.ts
Änderung: `ERR_DEVICE_CERT_INVALID` zeigt einen eigenen Hinweis (DE+EN) mit demselben Ausweg wie `ERR_CERT_REVOKED` (Identitaet zuruecksetzen, Token-Formular). Test im bestehenden Revoked-Test: Hinweis und Knopf erscheinen, der rohe Code nicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login.revoked.test.ts
Doku: → T12
Abhängt von: T3

### T5 — Tunnel-Status traegt den frps-Login (R-1691)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs
Änderung: der Log-Task setzt aus den Zeilen von frpc einen Login-Zustand im `FrpcState` (Start: verbindet; „login to server success“: angemeldet; „try to connect to server“ oder „connect to server error“: kein Kontakt), nur fuer die eigene Generation; `TunnelStatus` liefert ihn. Tests: Zeilen-Auswertung als reine Funktion mit den woertlichen v0.72.0-Zeilen, Generationswechsel setzt zurueck.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc::
Doku: → T12

### T6 — Tunnel-Anzeige: kein Kontakt zum Tunnel-Server (R-1691)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/lib/stores/tunnel.test.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/components/TunnelIndicator.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `TunnelStatus` im IPC-Typ um den Login-Zustand; der Store macht aus laufend + angemeldet „verbunden“, aus laufend + kein Kontakt einen neuen Zustand mit eigenem Text (DE+EN) im Indikator, laufend + verbindet bleibt „verbindet“. Tests im Store.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/tunnel.test.ts
Doku: → T12
Abhängt von: T5

### T7 — xfreerdp mit Passwort: ein Ereignis je Versuch (R-1707)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/rdp.rs
Änderung: der Exit-Thread wartet die Leser ab und entscheidet per `emitted.swap`, wie `wait_interactive`; die Entscheidung als testbare Funktion. Test mit einem Fake-Programm (`sh -c`), das vor der Frist ohne Fehlerzeile endet: genau ein Ereignis.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- connection::rdp::
Doku: keine (Fehlerverhalten ohne dokumentierte Beschreibung; CHANGELOG in T12)

### T8 — SFTP-Upload ueber eine Teil-Datei (R-1708)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs
Änderung: Upload nach `.<name>.ah-part` im Zielordner, danach Umbenennen (Ueberschreiben: `posix-rename@openssh.com`, wenn russh-sftp es anbietet, sonst Ziel entfernen und umbenennen), bei jedem Fehler die Teil-Datei entfernen. Tests gegen OpenSSH-sftp-server: abgebrochener Upload laesst die alte Datei unveraendert und keine Teil-Datei; Ueberschreiben nur auf Wunsch bleibt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp::
Doku: → T12

### T9 — Einstellung „Erreichbarkeit pruefen“ je Workspace, Backend (R-1710)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/storage.rs
Änderung: `Settings.probe_reachability` (Default an) im Meta von `workspace.json` wie `favorite_connections`; alte Datei ohne Feld liest sich als an. Tests in `storage.rs`: Default, Speichern je Workspace, zwei Workspaces getrennt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage::
Doku: → T12

### T10 — Ping-Spalte folgt der Einstellung (R-1710)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.test.ts, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/components/settings/WorkspaceSection.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Schalter in den Workspace-Einstellungen (DE+EN); ist er aus, startet die Seite keine Probe und die Spalte bleibt leer, ein Umschalten wirkt ohne Neustart. Tests im Store/der Seite.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connections.test.ts
Doku: → T12
Abhängt von: T9

### T11 — Feed: ein Abruf zur Zeit, ein Nachlauf (R-1711)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/notifications.ts, apps/desktop/ui/src/lib/stores/notifications.test.ts
Änderung: `loadFeed` haelt den laufenden Abruf; weitere Aufrufe waehrenddessen ergeben hoechstens einen Nachlauf, eine aeltere Antwort ueberschreibt keine neuere. Test: viele Ereignisse waehrend eines Abrufs ergeben zwei Abrufe.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/notifications.test.ts
Doku: keine (internes Verhalten ohne Doku-Stelle)

### T12 — Doku DE+EN und CHANGELOG (alle Zeilen)  [ ]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, changelog.d/kern-desktop-6.md
Änderung: Erneuerung (was die Sitzung beendet), abgelaufenes Geraete-Zertifikat und sein Ausweg, Tunnel-Zustand „kein Kontakt“, Upload ueber Teil-Datei, Schalter der Ping-Spalte; Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/… DE+EN · changelog.d/kern-desktop-6.md
Task-Review: am Ende
