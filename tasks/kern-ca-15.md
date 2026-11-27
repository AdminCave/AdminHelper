<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-15 — ca-issuer: Erneuerung mit Besitznachweis, Entrypoint-Test — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-15 · Review: pro Task
Spec: docs/features/kern-ca-15.md (Roadmap R-1812, R-1813)
Heavy: linux-full — apps/ca-issuer und apps/agent (Stack- und Agent-Schritte im Sammellauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27 R-1812: Besitznachweis als Feld `proof` in POST /renew (Signatur über die CSR-DER-Bytes mit dem alten Schlüssel, geprüft gegen den Public Key des vorgelegten Zertifikats); ein Release Übergang: ohne `proof` angenommen mit WARN, ab dem übernächsten Release abgelehnt.
- Signierte Nachricht: `b"AdminHelper renew v1\x00"` + CSR-DER, ECDSA P-256/SHA-256, Signatur ASN.1 DER, Base64 (Standard-Alphabet mit Padding).

### T1 — R-1812: ca-issuer prüft `proof` in /renew  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/tests/test_enroll_renew.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @e9be4bf71 2026-11-27T14:45:58+01:00
Review: approve (.ah-out/review/kern-ca-15/T1.verdict.json)
Änderung: `RenewRequest.proof` optional (Base64, Länge begrenzt); `Issuer.renew` prüft ihn gegen den Public Key des vorgelegten Zertifikats, falsch/unlesbar → `IssuanceError` (403); fehlt er → WARN mit CN und Scope, Erneuerung wie bisher. Tests: gültiger proof erneuert; proof eines fremden Schlüssels, über eine andere CSR, ohne Präfix und unlesbar → 403; ohne proof erneuert und loggt WARN.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_enroll_renew.py tests/test_schemathesis.py
Doku: → T5

### T2 — R-1812: Agent signiert den Renew mit dem alten Schlüssel  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/renew.go, apps/agent/internal/enroll/renew_test.go
Änderung: `RenewRequest.Proof`; `Renew` liest den bisherigen Schlüssel, signiert Präfix + CSR-DER (`ecdsa.SignASN1` über SHA-256) und schickt `proof`. Test: der Testserver prüft den proof gegen das vorgelegte Client-Zertifikat (mTLS) mit derselben Nachricht.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/enroll/
Doku: → T5

### T3 — R-1812: Desktop signiert den Renew  [ ]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/enrollment.rs
Änderung: `RenewRequest` bekommt `proof`; `renew` signiert Präfix + CSR-DER mit dem behaltenen Schlüssel (rcgen `SigningKey::sign`). Test: der proof verifiziert gegen den Public Key des Schlüssels über dieselbe Nachricht.
Verify: bash scripts/dev/verify.sh desktop --strict -- enrollment
Doku: → T5

### T4 — R-1813: Test für --no-proxy-headers im ca-issuer-Entrypoint  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/tests/test_entrypoint.py
Änderung: neue Testdatei (SPDX-Header): liest die uvicorn-Zeile aus `apps/ca-issuer/docker-entrypoint.sh` wie `apps/server/tests/test_server_entrypoint.py` und verlangt `--no-proxy-headers` ohne `--forwarded-allow-ips`.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_entrypoint.py
Doku: keine (Test)

### T5 — Doku DE+EN und Changelog  [ ]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, changelog.d/kern-ca-15.md
Änderung: ca-issuer-Absatz: `/renew` mit Besitznachweis (`proof`), Übergang ohne ihn; Changelog neutral.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
