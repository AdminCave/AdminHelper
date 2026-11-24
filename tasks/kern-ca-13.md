# kern-ca-13 — Task-Ledger
Status: bereit · Branch: feature/kern-ca-13 · Review: am Ende
Spec: docs/features/kern-ca-13.md (Roadmap R-1747)
Heavy: linux-full — apps/ca-issuer (Start-Prüfung LOG_LEVEL); die Stack-Probe sse_push_e2e läuft in integration-stack und im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1747: CA-Issuer nimmt nur die fünf Log-Level  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_logging.py, changelog.d/kern-ca-13.md
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @9872110ac 2026-11-24T19:47:58+01:00
Review: am Ende (Branch-Review)
Beweis: security kern-config-1 T4 2026-11-24 · apps/ca-issuer/app/main.py:38-44 (`logging.getLevelName` lässt registrierte Namen wie TRACE durch) · Dedup-Key: ref:ca-issuer:app/main.py:_log_level-trace
Semantik: docs/admin/betrieb.html:133 „ein anderer Wert bricht den Start ab“
Änderung: `_log_level` prüft gegen eine feste Liste (DEBUG, INFO, WARNING, ERROR, CRITICAL). Der Test registriert `TRACE` per `logging.addLevelName` und erwartet `ValueError` (erst rot). Danach entfernt er den Namen wieder.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_logging.py
Doku: changelog.d/kern-ca-13.md

### T2 — R-1747: sse_push_e2e wartet nicht auf einen 5xx  [x]
Komponente: scripts · Dateien: scripts/tests/sse_push_e2e.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @54af6a1fe 2026-11-24T20:13:04+01:00
Review: am Ende (Branch-Review)
Beweis: security kern-config-1 T2 2026-11-24 · scripts/tests/sse_push_e2e.sh:86,88 (`curl -so /dev/null` ohne Statusprüfung) · Dedup-Key: aus der Zeile R-1747
Änderung: Beide Warteschleifen lesen den Status per `curl -so /dev/null -w '%{http_code}'` und brechen nur bei 1xx bis 4xx ab (`case`, kein Bereich in `=~`). Der Lauf selbst bleibt in integration-stack (PR-CI).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)

### T3 — R-1747: sse_push_e2e scheitert laut, wenn eine Instanz nicht hochkommt  [x]
Komponente: scripts · Dateien: scripts/tests/sse_push_e2e.sh, docs/admin/betrieb.html, docs/en/admin/operations.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7181bd365 2026-11-24T20:45:58+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer branch kern-ca-13 2026-11-24 · scripts/tests/sse_push_e2e.sh:92 (`wait_up` endet nach 40 Versuchen mit dem Exit von `sleep`, also 0)
Änderung: `wait_up` meldet nach Ablauf der Frist `FAIL` mit dem Port und gibt 1 zurück; der Aufruf bricht den Lauf ab wie die Postgres-Wartung darüber. Die Frist steigt auf 30 s (60 × 0,5 s, `testing.md` „Fristen“). Dazu nennt die Betriebsdoku DE+EN `CRITICAL` unter den Log-Leveln (Nit aus derselben Prüfung).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html

## Entscheidungen
