<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent Windows: Datenverzeichnis mit festen Rechten anlegen — Task-Ledger
Status: aktiv · Branch: feature/agent-windows-datadir · Review: pro Task
Spec: keine eigene Datei (kleines Härtungs-Paket, Reihenfolge Kevin 2026-10-16)
Heavy: linux-full + windows — `apps/agent/internal/config` und die Aufrufer in `monitor`, `frpc` und `enroll` liegen auf dem Provisionierungs- und Enrollment-Pfad des Agents und laufen im Sammellauf über `main` (`/feature-build` §5); `windows` über den CI-Job `agent-windows` (go test nativ unter Windows; der Pool hat keine Windows-Vorlage)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: Der Agent legt sein Datenverzeichnis unter `%ProgramData%\AdminHelper` (samt `frp`, `frp\pki`, `logs` und dem
Identitätsordner) vor der ersten Nutzung mit festen Rechten an: nur SYSTEM und Administratoren, mit einer gegen
Vererbung geschützten ACL. Ein vorhandenes Verzeichnis mit anderem Eigentümer oder als Reparse-Point übernimmt er nicht.
Ein bestehendes Verzeichnis von SYSTEM oder Administratoren (Update) bleibt erhalten und bekommt die geschützte ACL neu.
Linux bleibt unverändert (`0700`). Zeilenangaben: main@b2091886.

### T1 — Gemeinsamer Helfer `EnsureSecureDir` und die Eigentümer-Entscheidung  [x]
Komponente: agent · Dateien: apps/agent/internal/config/securedir.go, apps/agent/internal/config/securedir_linux.go, apps/agent/internal/config/securedir_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6650b190 2026-10-18T07:26:00+02:00
Review: approve (.ah-out/review/agent-windows-datadir/T1.verdict.json)
Änderung: Neuer plattformneutraler Einstieg `EnsureSecureDir(dir string) error`, der das Verzeichnis sicher herstellt, und eine eigene, testbare Funktion `trustedOwner(sid string) bool` (SYSTEM `S-1-5-18` oder Administratoren `S-1-5-32-544`, wie `lockOwnerAllowed` in `enroll/lock.go:84`). Die Linux-Implementierung (`securedir_linux.go`, heute `SecureDir`) bleibt im Verhalten gleich: `MkdirAll(dir, 0o700)` und `Chmod(0o700)`; die Windows-Seite kommt in T2. `securedir.go` ist neu (SPDX-Header). Test in `securedir_linux_test.go`: `EnsureSecureDir` auf einem neuen und auf einem offen angelegten Verzeichnis ergibt `0700`; `trustedOwner` mit SYSTEM, Administratoren und einer anderen SID.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (intern)

### T2 — Windows: Verzeichnis mit geschützter ACL anlegen, keinen fremden Bestand übernehmen  [?] (Runde 2: Weg entschieden (Kevin 2026-10-18/20), siehe Aenderung)
Komponente: agent · Dateien: apps/agent/internal/config/securedir_windows.go, apps/agent/internal/config/securedir_windows_test.go, apps/agent/internal/config/securedir_linux.go
Änderung: `EnsureSecureDir` (Windows) legt `dir` mit geschütztem Security-Descriptor an (`windows.CreateDirectory` mit `windows.SecurityDescriptorFromString("O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")`, `golang.org/x/sys/windows`, vgl. `enroll/lock_windows.go`). Existiert der Pfad, arbeitet der Agent über Handles statt über den Pfad: Er öffnet `dir` einmal so, dass kein Reparse-Point verfolgt wird (`FILE_FLAG_OPEN_REPARSE_POINT|FILE_FLAG_BACKUP_SEMANTICS`), und liest, prüft und ändert Eigentümer, DACL und Kinder nur über dieses Handle und über Handles, die relativ dazu geöffnet sind. Dafür aktiviert er `SeTakeOwnershipPrivilege` (nicht verifiziert, ob es im Token von LocalSystem schon aktiv ist) und setzt per `SetSecurityInfo` zuerst den Eigentümer Administratoren und die geschützte DACL. War `dir` ein Reparse-Point oder gehörte es weder SYSTEM noch den Administratoren, entfernt er den Bestand von oben nach unten über Handles (je Ebene zuerst Eigentümer und geschützte DACL, dann aufzählen, Löschen per `FILE_DISPOSITION_INFO`) und legt `dir` neu an. Ein behaltener Ordner (Eigentümer SYSTEM oder Administratoren, kein Reparse-Point) verliert seine direkten Kinder, die Reparse-Points sind oder weder SYSTEM noch den Administratoren gehören; ein Kind mit vertrauenswürdigem Eigentümer bekommt eine zurückgesetzte DACL (explizite Einträge weg, Vererbung vom geschützten Ordner), sein Inhalt bleibt. Aufgeräumt wird vor dem Setzen der DACL des Ordners. Scheitert ein Schritt, gibt `EnsureSecureDir` einen Fehler zurück. Der Helfer `config.OwnByAdministrators(path)` (unter Linux ohne Wirkung) bleibt für Dateien, die ohne eigenen Descriptor entstehen; T3/T4 legen neue Dateien mit `O:BA` im Descriptor an. Tests windows-getaggt (CI-Job `agent-windows`): Anlegen setzt eine geschützte DACL ohne geerbte Einträge; ein vorhandenes Verzeichnis des Runners bleibt mit Inhalt erhalten; ein Ordner mit anderem Eigentümer (Eigentümer-Abfrage als Naht) wird neu angelegt; ein Verzeichnis-Reparse-Point wird nicht übernommen, und Descriptor und Inhalt seines Ziels sind vorher und nachher gleich; eine Junction unter `dir` wird nicht verfolgt, außerhalb von `dir` ändert sich nichts; ein offen gehaltenes fremdes Kind im behaltenen Ordner führt zum Fehler; ein Kind mit einem zusätzlichen Zugriffseintrag hat danach nur die vererbte DACL. Kevin 2026-10-18/20: Eigentümer übernehmen, Kinder-DACL zurücksetzen, Umbau auf Handles.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (intern)
Abhängt von: T1

### T3 — Aufrufer in monitor und frpc auf `EnsureSecureDir` umstellen  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/monitor.go, apps/agent/internal/frpc/apply.go
Änderung: Das Paar `os.MkdirAll(dir, 0700)` und `_ = config.SecureDir(dir)` wird je Stelle zu `if err := config.EnsureSecureDir(dir); err != nil { return … }`, der Fehler wird also behandelt statt verworfen: `monitor.go:58-62` (`monitorDir`) und `frpc/apply.go:56-61` (`frpDir`, `pkiDir`). Linux unverändert (`0700`); die Orchestrierungstests laufen über `ADMINHELPER_*_DIR` auf `t.TempDir()` und bleiben grün. Jede Datei, die monitor und frpc hier schreiben, geht danach durch `config.OwnByAdministrators` (Kevin 2026-10-18); das Log-Verzeichnis entsteht über `EnsureSecureDir`, bevor der Logger es öffnet.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (intern)
Abhängt von: T1

### T4 — Aufrufer in enroll (Identität und Sperre) auf `EnsureSecureDir` umstellen  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/enroll/lock.go
Änderung: Dieselbe Umstellung an den drei Identitäts-Stellen: `enroll.go:145-149` (`Store`), `enroll.go:170-173` (`CheckStorable`) und `enroll/lock.go:44-47` (`LockIdentity`) rufen `config.EnsureSecureDir(dir)` und geben dessen Fehler zurück, statt das Ergebnis von `SecureDir` zu verwerfen. Linux unverändert; die vorhandenen enroll-, lock- und renew-Tests bleiben grün. Jede Datei der Identität und die Sperrdatei gehen durch `config.OwnByAdministrators`, und `Store`/`CheckStorable` sichern zuerst den Elternordner mit `EnsureSecureDir`, dann `identity` (Kevin 2026-10-18).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (intern)
Abhängt von: T1

### T5 — Doku und CHANGELOG  [ ]
Komponente: agent · Dateien: CHANGELOG.md, docs/developer/agent.html, docs/en/developer/agent.html
Änderung: CHANGELOG unter `## [Unreleased]`, `### Changed`: Der Agent legt unter Windows sein Datenverzeichnis vor der ersten Nutzung mit festen Rechten an (nur SYSTEM und Administratoren) und übernimmt kein vorhandenes Verzeichnis mit anderem Eigentümer. `docs/developer/agent.html:78` und `docs/en/developer/agent.html:78`: den Absatz zur Härtung des Datenverzeichnisses entsprechend ergänzen (DE und EN im selben Commit).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: CHANGELOG.md (Changed) · docs/developer/agent.html + docs/en/developer/agent.html (DE+EN)
Abhängt von: T2
