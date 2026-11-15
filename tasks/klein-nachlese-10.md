<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-10 — Task-Ledger
Status: erledigt · Branch: feature/klein-nachlese-10 · Review: pro Task
Spec: docs/features/klein-nachlese-10.md (Roadmap R-1453, R-1458, R-1473, R-1485, R-1490, R-1492, R-1495, R-1497)
Heavy: linux-full — apps/agent (Agent-Checks dovecot_status und lmn_linbo)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Agent: Kommentar, Test, Body nur mit body_match lesen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_host.go, apps/agent/internal/probe/sensor_http.go, apps/agent/internal/probe/sensor_net_test.go, apps/agent/internal/probe/app_samba_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a6e860ab6 2026-11-15T00:56:00+01:00
Review: approve (.ah-out/review/klein-nachlese-10/T1.verdict.json)
Beweis: R-1473 (reviewer kern-monitoring-14 T5), R-1497 (reviewer kern-monitoring-11 T8 @72644422a), R-1458 (review kern-monitoring-30 @a4a220b9e) 2026-11-14
Änderung: Kommentarzeile in `sensor_host.go` auf etwa 100 Spalten umbrechen. `app_samba_test.go`: der Fall „smbstatus fehlt“ prüft `errors.Is(err, ErrUnsupported)`. `fetchExpecting` liest den Body bei `expect` ohne `body_match` nicht; `sensor_net_test.go`: die 200-ms-Frist bekommt den Kommentar nach `testing.md` (Grund der festen Frist). Test zum Body-Lesen, falls `sensor_http.go` ihn heute liest (Gegenprobe rot).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: keine (Agent-Interna ohne dokumentiertes Verhalten)

### T2 — Agent: dovecot_status meldet unbekannte Zeilen, lmn_linbo überspringt ein verschwundenes Image  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_mail.go, apps/agent/internal/probe/app_mail_test.go, apps/agent/internal/probe/app_lmn.go, apps/agent/internal/probe/app_lmn_test.go, changelog.d/klein-nachlese-10.md, apps/agent/internal/probe/sensor_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3d58aa414 2026-11-15T01:05:37+01:00
Review: approve (.ah-out/review/klein-nachlese-10/T2.verdict.json)
Beweis: R-1485 (reviewer kern-monitoring-11 T1 @78da35d24), R-1495 (reviewer kern-monitoring-11 @d92c8f450) 2026-11-14
Änderung: `dovecotErrors` gibt für eine nicht leere Zeile ohne bekannte Form (weniger als vier Felder oder unbekannter Typ) einen Fehler zurück statt zu überspringen; der Fehler nennt keinen Zeileninhalt. `lmnLinbo`: fehlt ein Image bei `Lstat` (`fs.ErrNotExist`), wird der Eintrag übersprungen, jeder andere Fehler bleibt. Beide mit Test (erst rot). Changelog-Fragment (German `### Fixed`).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: changelog.d/klein-nachlese-10.md
Abhängt von: T1

### T3 — Katalog: SSLDIR belegt, Docstrings auf 100 Zeichen und gleichen Umbruch  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/linuxmuster.py, apps/monitoring/app/catalog/modules/mattermost.py, apps/monitoring/app/catalog/modules/onlyoffice.py, apps/monitoring/tests/test_catalog_onlyoffice.py, apps/monitoring/tests/test_catalog_openldap.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ae23dcbe3 2026-11-15T01:07:36+01:00
Review: approve (.ah-out/review/klein-nachlese-10/T3.verdict.json)
Beweis: R-1490 (kern-monitoring-11 T6 Review), R-1458 (review kern-monitoring-30) 2026-11-14
Änderung: `linuxmuster.py` streicht „the directory's value in base7's environment module is not verified“ (belegt: `linuxmuster-common` `lib/environment.py` Zeile 14/24 `SSLDIR = '/etc/linuxmuster/ssl'`, `linuxmuster-base7` `functions/certs.py:252` `<item>.cert.pem`); die Docstrings der zwei Test-Dateien, `mattermost.py` (Zeile 17) und `onlyoffice.py` (Zeile 11, 24) brechen gleichmäßig auf ≤ 100 Zeichen um. Keine Wortänderung außer der Streichung.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_onlyoffice.py tests/test_catalog_openldap.py tests/test_catalog_directory.py
Doku: keine (Docstrings; der Katalogtext der Karte bleibt gleich)

### T4 — Desktop-E2E: findingItem wählt den Eintrag atomar  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-server-page.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @943e66b62 2026-11-15T01:09:36+01:00
Review: approve (.ah-out/review/klein-nachlese-10/T4.verdict.json)
Beweis: R-1492 (reviewer branch kern-desktop-e2e-1) 2026-11-14
Änderung: `findingItem` liefert das Element aus `browser.execute` (Element-Referenz) statt Index und zweiter Abfrage per `$$`; kein Treffer wirft weiter `no finding … in the inbox`. Lokal nur ESLint (das Live-Spec fährt die Desktop-Box); im Commit-Body als nicht laufbar vermerkt.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test-Hilfe)

### T5 — Doku: cicd.html DE+EN, Spec und Ledger von ci-11  [x]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, docs/features/ci-11.md, tasks/ci-11.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @35ed1ad11 2026-11-15T01:18:37+01:00
Review: approve (.ah-out/review/klein-nachlese-10/T5.verdict.json)
Beweis: R-1453 (review ci-11 @8bc8d4398) 2026-11-14
Änderung: In der Tabellenzeile `ci.yml` nennt der FRP-Pin-Check zusätzlich `scripts/tests/freebsd_box.sh` (Version und SHA-256 `freebsd_amd64`, gegen `release.yml`), und `pkg-repo` steht neben `agent-windows` (baut pkg aus den Quellen, baut und prüft das signierte pkg-Repo). `docs/features/ci-11.md` Ziel 5: „SHA-256 der Datei“ statt „(DER)“, Ziel 4: Ablauf wie in der Ledger-Entscheidung T3 (`OUT_DIR=pkg-out` vor `build-repo.sh`); `tasks/ci-11.md` Entscheidungen: der Satz „wie die Spec in Ziel 4 noch sagt“ entfällt.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html
Task-Review: am Ende

### T6 — Agent: lmn_linbo-Test erreicht das Überspringen in lmnLinbo  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/app_lmn.go, apps/agent/internal/probe/app_lmn_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @21ce3033c 2026-11-15T01:29:55+01:00
Review: approve (.ah-out/review/klein-nachlese-10/T6.verdict.json)
Beweis: Abschlussprüfung klein-nachlese-10 2026-11-15 (Gegenprobe: ohne das `continue` an der Aufrufstelle bleibt `TestLmnLinboLeavesOutAnImageThatIsGone` grün)
Änderung: Die Zählschleife von `lmnLinbo` wird zur Funktion `countLinboImages(root, dir, entries)`; der Test listet ein Verzeichnis, löscht ein Image und ruft sie mit der alten Liste auf. Verhalten unverändert.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/...
Doku: keine (Testlücke, Verhalten unverändert)
Abhängt von: T2

## Entscheidungen
- R-1458 geteilt: fünf eindeutige Nits in T1/T3; `timeout_s <= 2` mit `auto` und das OnlyOffice-Kartenfeld `body_match`
  ändern sichtbares Verhalten und werden eigene Roadmap-Zeilen `neu` (Kevins Bereich).
