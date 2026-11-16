<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-12 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-12 · Review: pro Task
Spec: docs/features/klein-nachlese-12.md (Roadmap R-1505, R-1507, R-1509, R-1510, R-1511, R-1512, R-1514; R-1506 abgelehnt: bereits behoben)
Heavy: none — Agent-Unit-Tests, Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1505, R-1510: cachedVhosts cached keinen Fehler aus dem ctx des Aufrufers  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhost_cert.go, apps/agent/internal/probe/web_vhost_cert_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @dccb97cf2 2026-11-16T13:26:36+01:00
Review: approve (.ah-out/review/klein-nachlese-12/T1.verdict.json)
Beweis: reviewer kern-monitoring-28 T3 2026-11-15 · Dedup-Key: REF:agent:web_vhost_cert.go:cachedVhosts
Änderung: Endet `WebVhosts` mit einem Fehler, während `ctx.Err() != nil`, wird nichts gemerkt; ein Aufrufer mit beendetem `ctx` liest nach dem Lock nicht mehr (der Lock bleibt ein Mutex: die Wartezeit ist durch toolTimeout begrenzt). Test erst rot: erster Aufruf mit abgelaufenem ctx, zweiter mit frischem ctx liest neu.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe -run 'CallersOwn|WaiterWhose|Vhost'
Doku: keine (interner Cache)

### T2 — R-1507: RunCapped beendet die Prozessgruppe  [x]
Komponente: agent · Dateien: apps/agent/internal/execx/execx.go, apps/agent/internal/execx/execx_unix.go, apps/agent/internal/execx/execx_other.go, apps/agent/internal/execx/execx_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @75259e1ee 2026-11-16T13:34:50+01:00
Review: approve (.ah-out/review/klein-nachlese-12/T2.verdict.json)
Beweis: reviewer kern-monitoring-28 T6 2026-11-15 · Dedup-Key: REF:agent:execx.go:RunCapped-orphan
Änderung: `RunCapped` startet das Kommando in eigener Prozessgruppe (`Setpgid`, `cmd.Cancel` sendet SIGKILL an die Gruppe); nur Unix, andere Plattformen unverändert (Build-Tags, SPDX in neuen Dateien). Test erst rot: `sh -c` mit Enkel, nach Frist ist der Enkel weg. Windows-Build: `GOOS=windows go vet ./internal/execx/`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/execx
Doku: keine (interner Aufruf)

### T3 — R-1509: web_vhosts, App bei abweichender Namensreihenfolge  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/web_vhosts.go, apps/agent/internal/probe/web_vhosts_test.go, apps/agent/internal/execx/execx_unix_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @23be76ec9 2026-11-16T13:41:28+01:00
Review: approve (.ah-out/review/klein-nachlese-12/T3.verdict.json)
Beweis: kern-monitoring-28 T7 review 2026-11-15 · Dedup-Key: REF:agent:web_vhosts.go:uniqueVhosts-app
Änderung: Test erst: zwei Blöcke desselben Servers mit verschiedener Namensreihenfolge (App am ersten Namen je Block); die App darf nach `uniqueVhosts` nur einmal und am ersten Namen des gewählten (TLS-)Blocks stehen. Der Test war rot (die App stand auf zwei Namen): `uniqueVhosts` lässt die App je Wurzelverzeichnis auf dem ersten Namen, der sie trägt.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe -run 'AnAppIsOnOneName|ANameIsKept|Vhost'
Doku: keine (interne Auswahl)

### T4 — R-1514: errWPDBServer erreicht den Aufrufer; Docstring _before_app_checks  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_wordpress_cron.go, apps/agent/internal/probe/app_wordpress_cron_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @5feff044e 2026-11-16T13:44:05+01:00
Review: approve (.ah-out/review/klein-nachlese-12/T4.verdict.json)
Beweis: reviewer kern-monitoring-35 T2 2026-11-15 · app_wordpress_cron.go:472
Änderung: Test erst rot: ein Server, der die Grenze reißt, ergibt aus `wpCronValue` eine Meldung, die „sends more than the view reads“ nennt (heute „connection fails“); der Wächter merkt sich seinen Fehler, `wpDBError` fragt ihn ab (`errors.Is(g.err, errWPDBServer)` an der Verbindung, nicht am Treiberfehler).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe -run 'WordPress|WP'
Doku: keine (Fehlertext)

### T5 — R-1514: Docstring von _before_app_checks  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_module_sync.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5e6efad87 2026-11-16T13:45:42+01:00
Review: approve (.ah-out/review/klein-nachlese-12/T5.verdict.json)
Beweis: reviewer kern-monitoring-35 branch 2026-11-15 · test_module_sync.py:775
Änderung: Docstring beschreibt, was die Funktion tut (ohne die Checks des Katalogs `APP_CHECKS`, version 1); kein Verhalten ändert sich.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py
Doku: keine (Docstring eines Tests)

### T6 — R-1511, R-1512: Doku berichtigen  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/features/kern-monitoring-28.md, changelog.d/klein-nachlese-12.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @081c16190 2026-11-16T13:49:59+01:00
Review: am Ende (nur Doku, Branch-Review)
Beweis: kern-monitoring-28 branch-Review 2026-11-15 · Semantik: docs/features/kern-monitoring-28.md „Last: pro Domain ein Handshake auf Loopback je Stunde“ (zu berichtigen)
Änderung: Der Agent fragt die Adresse, auf der der Webserver am Port des vHosts lauscht (meist Loopback), nicht fest `127.0.0.1` (agent/monitoring developer, admin monitoring, DE+EN). `web_domain` fährt zwei Checks mit je einem Handshake: zwei je Domain und Stunde (admin monitoring DE+EN, Spec-Zeile „Last“). Zuvor `resolve`/`ruledEndpoint` lesen, damit der Wortlaut stimmt.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende

### T7 — R-1511: Zieladresse auch im vHost-Absatz der Admin-Doku  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/features/kern-monitoring-28.md
Beweis: Abschlussprüfung klein-nachlese-12 2026-11-16 · docs/admin/monitoring.html:577 „Jeder Check fragt den Port des vHosts auf Loopback“
Änderung: Der Absatz der vHost-Checks (DE+EN) und die Spec-Zeilen 41 und 73 nennen die Adresse, auf der der Webserver am Port lauscht, nicht fest Loopback.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende

## Entscheidungen
- T2: Der Test von T2 liegt in execx_unix_test.go (Ledger nannte execx_test.go) und kam erst mit dem Commit von T3 in den Branch; T3 führt die Datei in Dateien:.
