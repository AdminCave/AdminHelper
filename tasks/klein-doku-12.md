# klein-doku-12 — Task-Ledger
Status: aktiv · Branch: feature/klein-doku-12 · Review: pro Task
Spec: docs/features/klein-doku-12.md (Roadmap R-1774, R-1802)
Heavy: none — Doku, Kommentare und ein Quelltext-Test
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server-Kommentare nennen .bootstrap_setup (R-1774)  [ ]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/app/main.py
Änderung: der Kommentar vor `ADMIN_PASSWORD` und der Docstring von `ensure_admin` sagen, dass der einmalige Setup-Token in `DATA_DIR/.bootstrap_setup` liegt (0600, Klartext); `.bootstrap_token` hält nur den Hash. Vorher an `BOOTSTRAP_TOKEN_FILE`/`BOOTSTRAP_SETUP_FILE` im Code prüfen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: keine (Kommentare)

### T2 — curl-Regex des Download-Tests (R-1802)  [ ]
Komponente: server · Dateien: apps/server/tests/test_ci_workflow.py
Änderung: `test_every_download_of_the_release_retries` fügt Backslash-Fortsetzungen zu einem Aufruf zusammen, bevor es die Flags prüft, und erkennt `curl` auch am Zeilenende; eine Gegenprobe (kleiner Test mit umbrochenem und mit flaglosem curl) zeigt, dass die Prüfung fallen kann.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: keine (Test)

### T3 — Doku: cicd.html, installation.html, Changelog (R-1774, R-1802)  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, docs/admin/installation.html, changelog.d/klein-doku-12.md
Änderung: "sobald scharf geschaltet" entfällt (SHA256SUMS.minisig gibt es immer), die Jobliste der `release.yml`-Zeile nennt `image-pins`, `pkg-signing-key` und `freebsd-pkg-tool` (DE+EN, gegen `release.yml` geprüft); DE `installation.html` Zeile 87 bekommt den STCP-Visitor-Hinweis der EN-Seite (6000-6999 bindet lokal am Desktop-Client). Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Dateien selbst
Task-Review: am Ende

## Entscheidungen
- 2026-11-27: Der Wortlaut der R-1802-Nits stand nur im Prüfer-Urteil von ci-22; die Lesart (Jobliste, curl-Fortsetzungszeilen) stammt aus dem Code. Das Branch-Review prüft sie.
