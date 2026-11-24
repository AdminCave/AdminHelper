# kern-ca-13 — Task-Ledger
Status: geplant · Branch: feature/kern-ca-13 · Review: am Ende
Spec: docs/features/kern-ca-13.md (Roadmap R-1747)
Heavy: linux-full — apps/ca-issuer (Start-Prüfung LOG_LEVEL); die Stack-Probe sse_push_e2e läuft in integration-stack und im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1747: CA-Issuer nimmt nur die fünf Log-Level  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_logging.py, changelog.d/kern-ca-13.md
Beweis: security kern-config-1 T4 2026-11-24 · apps/ca-issuer/app/main.py:38-44 (`logging.getLevelName` lässt registrierte Namen wie TRACE durch) · Dedup-Key: ref:ca-issuer:app/main.py:_log_level-trace
Semantik: docs/admin/betrieb.html:133 „ein anderer Wert bricht den Start ab“
Änderung: `_log_level` prüft gegen eine feste Liste (DEBUG, INFO, WARNING, ERROR, CRITICAL). Der Test registriert `TRACE` per `logging.addLevelName` und erwartet `ValueError` (erst rot). Danach entfernt er den Namen wieder.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_logging.py
Doku: changelog.d/kern-ca-13.md

### T2 — R-1747: sse_push_e2e wartet nicht auf einen 5xx  [ ]
Komponente: scripts · Dateien: scripts/tests/sse_push_e2e.sh
Beweis: security kern-config-1 T2 2026-11-24 · scripts/tests/sse_push_e2e.sh:86,88 (`curl -so /dev/null` ohne Statusprüfung) · Dedup-Key: aus der Zeile R-1747
Änderung: Beide Warteschleifen lesen den Status per `curl -so /dev/null -w '%{http_code}'` und brechen nur bei 1xx bis 4xx ab (`case`, kein Bereich in `=~`). Der Lauf selbst bleibt in integration-stack (PR-CI).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)

## Entscheidungen
