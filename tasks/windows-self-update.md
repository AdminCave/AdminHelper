# Windows-Agent: signiertes Self-Update über :8445 — Task-Ledger
Status: bereit · Branch: feature/windows-self-update · Review: pro Task
Spec: docs/features/windows-self-update.md (Roadmap R-1581)
Heavy: windows — Tausch, Health-Check und Rollback sind Windows-Code; Beweis über die Windows-Jobs der PR-CI; den Gateway-Teil prüft der integration-stack-Job der PR-CI
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — selfupdate: minisign-Prüfung, signierte Liste, Versionsvergleich, Download  [x]
Komponente: agent · Dateien: apps/agent/internal/selfupdate/minisign.go, apps/agent/internal/selfupdate/minisign_test.go, apps/agent/internal/selfupdate/fetch.go, apps/agent/internal/selfupdate/fetch_test.go, apps/agent/go.mod, apps/agent/go.sum, THIRD_PARTY_LICENSES.md, apps/agent/internal/selfupdate/testdata/adminhelper-agent.exe, apps/agent/internal/selfupdate/testdata/frpc.exe, apps/agent/internal/selfupdate/testdata/SHA256SUMS, apps/agent/internal/selfupdate/testdata/SHA256SUMS.legacy.minisig, apps/agent/internal/selfupdate/testdata/SHA256SUMS.minisig, apps/agent/internal/selfupdate/testdata/SHA256SUMS.othercomment.minisig, apps/agent/internal/selfupdate/testdata/SHA256SUMS.wrongkey.minisig, apps/agent/internal/selfupdate/testdata/test.pub, apps/agent/internal/selfupdate/testdata/VERSION
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @9f78af5fc 2026-11-20T18:19:46+01:00
Review: approve (.ah-out/review/windows-self-update/T1.verdict.json)
Änderung: Neues Paket (SPDX-Header). Die minisign-Prüfung nimmt nur `ED` (Ed25519 über BLAKE2b-512) mit passender Key-ID und prüft die globale Signatur über Signatur und Trusted Comment; Legacy `Ed` wird abgelehnt. Der Schlüssel ist eine Konstante, ein Test hält sie im Gleichlauf mit `MINISIGN_PUBKEY` in `scripts/update.sh:48`. `Check` lädt `/windows/SHA256SUMS` und `.minisig` von `https://<host>:8445` mit der gepinnten Gateway-CA, prüft sie und liest `VERSION`. Ist sie echt größer als die eigene (keine dev-Builds, keine gemerkte Fehlversion), lädt es beide .exe in einen Staging-Ordner und prüft deren SHA-256. Fixtures erzeugt das echte minisign 0.12 (gültig, gefälscht, falscher Schlüssel, Legacy), Server per httptest.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/selfupdate/...
Doku: → T5

### T2 — Windows: Tagesplan, abgelöster Helfer, Tausch mit .old, Health-Check, Rollback, AUTO_UPDATE=0  [x]
Komponente: agent · Dateien: apps/agent/internal/selfupdate/apply_plan.go, apps/agent/internal/selfupdate/apply_plan_test.go, apps/agent/internal/selfupdate/apply_windows.go, apps/agent/internal/selfupdate/apply_windows_test.go, apps/agent/internal/selfupdate/schedule.go, apps/agent/internal/selfupdate/schedule_test.go, apps/agent/cmd/adminhelper-agent/run_windows.go, apps/agent/cmd/adminhelper-agent/main.go, apps/agent/internal/service/selfupdate_windows.go, apps/agent/cmd/adminhelper-agent/run_other.go, apps/agent/internal/selfupdate/fetch.go, apps/agent/internal/selfupdate/fetch_test.go, apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/cmd/adminhelper-agent/run_windows_test.go, apps/agent/internal/service/selfupdate_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a68089524 2026-11-20T18:48:10+01:00
Review: approve (.ah-out/review/windows-self-update/T2.verdict.json)
Änderung: Der Dienst prüft einmal am Tag mit zufälligem Versatz (Zeitpunkt im Datenordner gemerkt). Bei `AUTO_UPDATE=0` in der Agent-Konfiguration prüft er nie. Bei einem neuen, geprüften Release startet er die neue Binary aus dem Staging-Ordner abgelöst, mit dem versteckten Unterbefehl `self-update-apply`. Der Helfer stoppt den Dienst, sichert beide .exe als `.old`, legt die neuen ab und startet. Er wartet bis 15 min auf die Gesund-Marke, die der Dienst nach seinem ersten vollständigen Zyklus mit der neuen Version schreibt. Sonst stoppt er, stellt `.old` her, startet und merkt die Version als gescheitert. Die Reihenfolge liegt plattformunabhängig in `apply_plan.go` mit Hooks, wie `install_plan.go`, und wird mit Fakes getestet (Erfolg, Start scheitert, Marke bleibt aus, Fehler beim Sichern); der Windows-Teil über die Windows-Jobs.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/selfupdate/... ./internal/service/... ./internal/frpc/... ./cmd/adminhelper-agent/
Doku: → T5
Abhängt von: T1

### T3 — Gateway: /windows/ auf der Repo-Ebene :8445  [x]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4c0256888 2026-11-20T18:24:38+01:00
Review: approve (.ah-out/review/windows-self-update/T3.verdict.json)
Änderung: `location ~ ^/(apt|rpm|freebsd|windows)/` (nginx.conf:242) samt Kommentar. Der Container-Test liefert eine Datei unter `/windows/` aus und zeigt, dass Pfade außerhalb weiter 404 sind.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: → T5

### T4 — Release: signierter windows/-Satz im Agent-Repo-Asset  [x]
Komponente: scripts · Dateien: apps/agent/build-windows-update.sh, scripts/tests/windows_update_set_test.sh, scripts/tests/run.sh, .github/workflows/release.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a0a1b0553 2026-11-20T18:30:47+01:00
Review: approve (.ah-out/review/windows-self-update/T4.verdict.json)
Änderung: `build-windows-update.sh` (SPDX) legt aus Agent-.exe, frpc.exe und Version `windows/` an (`VERSION`, beide .exe, `SHA256SUMS`) und signiert mit minisign. Der Trusted Comment trägt das Tag. Danach prüft es gegen den Schlüssel aus `scripts/update.sh`. `release.yml` ruft es in einem Schritt vor „Build signed agent repo“ mit `MINISIGN_SECRET_KEY` (Schlüsseldatei nur im Schritt, per trap gelöscht) und kopiert `windows/` neben `freebsd/` ins Repo. Der Test signiert mit einem Wegwerf-Schlüssel und prüft Inhalt, `minisign -V` und den Abbruch bei falschem Schlüssel.
Verify: bash scripts/dev/verify.sh scripts --strict -- windows_update_set_test
Doku: → T5

### T5 — Doku: automatisches Update unter Windows, Release-Schritt  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/windows-self-update.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1f0ca7cac 2026-11-20T18:54:06+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Absatz „Automatisches Update“ im Windows-Abschnitt (Rhythmus, Signatur, Rollback, `AUTO_UPDATE=0`). Der Release-Schritt kommt in cicd.html. Changelog-Fragment deutsch, umlautfrei, `- **Windows-Agent: …:** …`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

### T6 — Doku: Pin-Stellen des minisign-Schlüssels, Schlüsselwechsel, Update-Ordner  [x]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @447cc379a 2026-11-20T19:10:56+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschlussprüfung (reviewer branch, wichtig): Die Anleitung zum Scharfschalten nennt `ReleasePublicKey` in `apps/agent/internal/selfupdate/minisign.go` als dritte Pin-Stelle, dazu den Hinweis, dass ein Schlüsselwechsel installierte Windows-Agents bis zu einem Update von Hand von weiteren Updates abschneidet. Nit: Im Update-Ordner landen nur die beiden .exe, nicht `VERSION` und `SHA256SUMS`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Kevin 2026-11-20: täglich automatisch, abschaltbar per Config; ein PR samt release.yml, Kevin merged.
- HEAD beim Plan: 534598254.
- T2: Der Update-Client nimmt die TLS-Einstellungen des Agents (CACERT/INSECURE aus der Sync-Config): :8445 liefert dasselbe Zertifikat wie :443; echt macht ein Release allein die minisign-Signatur über SHA256SUMS.
- T2: Gesund heißt: der Dienst der neuen Version beendet seinen ersten Zyklus (nicht durch Stop abgebrochen). Ein Zyklus mit Serverfehler zählt mit, sonst rollte ein Server-Ausfall jedes Update zurück.
- T2: Rollback über service.Restore (Stopp, .old zurück, Start) statt über install: der frpc-Pin der neuen Binary wiese das alte frpc ab.
- T2: Die gescheiterte Version steht in einer eigenen Datei `failed` neben `state.json`; nur ein neueres Release wird wieder versucht.
- T2: `AUTO_UPDATE` überlebt ein neues Provisionieren (writeSyncConfig übernimmt den Schlüssel), sonst schaltete jedes Re-Provisionieren das Update still wieder ein; dafür `apps/agent/internal/frpc/apply.go` in T2 und `./internal/frpc/...` im Verify.
