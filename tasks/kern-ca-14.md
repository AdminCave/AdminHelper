# ca-issuer: Client-Identitaet nur vom Gateway — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-14 · Review: pro Task
Spec: docs/features/kern-ca-14.md (Roadmap R-0840)
Heavy: linux-full — apps/ca-issuer und integration_stack_test.sh (Erneuerung ueber den echten Gateway); Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-25 (Notiz R-0840): faellig. Die Bedingung aus der Notiz (Netz pki nach db-roles) ist erfuellt; pki
  traegt weiter postgres.

### T1 — ca-issuer: Header nur vom Gateway-Peer  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/app/gateway_peer.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/docker-entrypoint.sh, apps/ca-issuer/tests/test_gateway_peer.py, apps/ca-issuer/tests/conftest.py
Änderung: `_presented_cert` wertet die Header nur, wenn der TCP-Peer eine aktuelle Adresse des Namens `gateway` ist (neues Modul mit kurzem Cache, sofortiger Neuauflösung bei unbekanntem Peer, fail-closed, Warnzeile je Peer und Minute); sonst 401. Entrypoint mit `--no-proxy-headers`. Kommentar an `_verify_ca_signed` nachziehen. Tests: Peer Gateway → 200, anderer Peer → 401 auf `/renew` und `/trust`, Auflösungsfehler → 401, neue Gateway-Adresse wird nach Neuauflösung angenommen; bestehende Tests per Fixture mit dem Test-Client als Gateway. SPDX im neuen Modul und Test.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_gateway_peer.py tests/test_enroll_renew.py tests/test_trust_generation.py
Doku: → T3

### T2 — Stack-Test: Header aus einem anderen pki-Container  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Änderung: Nach Schritt 8 schickt der postgres-Container (busybox `wget`) `X-Client-Verify: SUCCESS` und das echte, escapte Leaf des Geraets direkt an `ca-issuer:8090/trust`; erwartet 401. Gegenprobe im selben Schritt: dieselbe Anfrage ueber den Gateway liefert 200.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)
Abhängt von: T1

### T3 — Doku: ca-issuer prueft die Gegenstelle, CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-ca-14.md
Änderung: Architektur und Installation DE+EN: der ca-issuer wertet die `X-Client-*`-Header wie der Server nur vom Dienst `gateway` aus, uvicorn ohne Proxy-Header. CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/index.html, docs/en/developer/index.html, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-ca-14.md
Task-Review: am Ende
