<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-3 — Task-Ledger
Status: bereit · Branch: feature/kern-ca-3 · Review: pro Task
Spec: docs/features/kern-ca-3.md (Roadmap R-1009)
Heavy: linux-full — `apps/ca-issuer`, Server-mTLS und `docker-compose.yml` (Sammellauf; dazu vor dem Merge der Stack-Job per Dispatch mit der frps- und Gateway-Probe aus T4)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — frps-Bundle ohne Root (R-1009)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/storage.py, apps/ca-issuer/tests/test_frps_cert.py, apps/ca-issuer/tests/test_gateway_cert.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @33e0108d 2026-10-31T07:28:30+01:00
Review: approve (.ah-out/review/kern-ca-3/T1.verdict.json)
Änderung: `_provision_server_material` bekommt einen Schalter, ob die Root ins Trust-Bundle geht; `ensure_frps_cert` schreibt `ca.crt` nur mit den Zwischenzertifikaten (aktuell + abgelöst, tunnel und access), das Gateway behält die Root (nginx braucht sie). Tests: `ca.crt` enthält kein selbstsigniertes Zertifikat; mit `cryptography.x509.verification` (Store = Bundle) besteht ein Leaf des aktuellen und eines abgelösten Zwischenzertifikats, eines unter einem nicht geführten Zwischenzertifikat derselben Root (mitgeschickt) nicht; Gateway-Bundle unverändert.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_frps_cert.py tests/test_gateway_cert.py
Doku: → T5

### T2 — ca-issuer veröffentlicht die geführten Zwischenzertifikate je Scope (R-1009)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/trust.py, apps/ca-issuer/app/main.py, apps/ca-issuer/app/config.py, apps/ca-issuer/tests/test_trust.py, docker-compose.yml, apps/ca-issuer/docker-entrypoint.sh
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @6bc826c5 2026-10-31T07:32:08+01:00
Review: approve (.ah-out/review/kern-ca-3/T2.verdict.json)
Änderung: Neues Modul `trust.py` (SPDX-Header) schreibt bei jedem Start nach `provision_boot_material` je Scope `<scope>.pem` (aktuelles + abgelöste Zwischenzertifikate, nur Zertifikate) atomar in `CA_TRUST_DIR`; ohne gesetztes Verzeichnis nichts. Compose: Volume `ca-trust`, im `ca-issuer` schreibbar, im `server` nur lesbar, Env `CA_TRUST_DIR` in beiden. Test: Dateien nach dem Lauf, nach einer Rotation mit `--compromised` ohne das gesperrte, kein Schlüssel im Verzeichnis.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_trust.py tests/test_rotation.py
Doku: → T5

### T3 — Server prüft den Aussteller des Client-Zertifikats (R-1009)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/core/config.py, apps/server/tests/conftest.py, apps/server/tests/test_identity_issuer.py, apps/server/tests/test_mtls_scope.py, apps/server/tests/test_identity_source.py, apps/server/tests/test_identity_revocation.py, apps/server/tests/test_certificate_check.py, docker-compose.yml, apps/server/tests/trust_ca.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @798bb8e5 2026-10-31T07:55:28+01:00
Review: approve (.ah-out/review/kern-ca-3/T3.verdict.json)
Änderung: `get_client_identity` hält fest, ob ein Zwischenzertifikat aus `CA_TRUST_DIR/<scope>.pem` das Zertifikat direkt ausgestellt hat (Signaturprüfung, mtime-Cache je Datei); `_refused` lehnt sonst ab (403 `ERR_CERT_REVOKED`, beide Modi). Fehlt oder ist die Datei unlesbar: ablehnen und Fehler loggen (fail-closed). Die bestehenden Tests bekommen eine Fixture mit der Trust-Datei ihrer Test-CA (mehr als acht Dateien: jede Testdatei mit eigenem Zertifikatsbau braucht sie). Neue Testdatei mit SPDX-Header: aktuell und abgelöst angenommen, fremdes Zwischenzertifikat derselben Root abgelehnt, fehlende Datei abgelehnt, geänderte Datei neu gelesen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_issuer.py tests/test_mtls_scope.py tests/test_identity_source.py tests/test_identity_revocation.py tests/test_certificate_check.py tests/test_openapi_snapshot.py
Doku: → T5
Abhängt von: T2

### T4 — Stack-Probe: gesperrter Aussteller an frps und Server abgelehnt (R-1009)  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f64d42ef 2026-10-31T08:32:07+01:00
Review: approve (.ah-out/review/kern-ca-3/T4.verdict.json)
Änderung: Im echten Stack ein Zwischenzertifikat unter der echten Root ausstellen, das nicht geführt ist (im `ca-issuer`-Container mit der Passphrase des Testlaufs), damit ein Leaf signieren und mitschicken: frps lehnt den Handshake ab, über das Gateway bekommt der Server-Aufruf 403 `ERR_CERT_REVOKED`; ein echt enrolltes Zertifikat besteht beides weiter. Dazu `tls_probe` an das Bundle ohne Root aus T1 anpassen (OpenSSL braucht `VERIFY_X509_PARTIAL_CHAIN` oder die Root in der Probe-CA-Datei). Beweis im Stack-Job per `gh workflow run ci.yml --ref feature/kern-ca-3`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T5
Abhängt von: T1, T3

### T5 — Doku DE+EN und Changelog (R-1009)  [x]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-ca-3.md, docs/developer/index.html, docs/en/developer/index.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @23470360 2026-10-31T08:40:23+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitt `ca-rotation`: nach `--compromised` und Neustart nehmen frps und Server kein Zertifikat des gesperrten Zwischenzertifikats mehr an; was weiter erst eine neue Root schließt (die Prüfung des Servers durch die Clients). Architektur-Seite zu mTLS-Vertrauen per grep bestimmen und mitziehen (`ledger.sh set-files`). Changelog neutral unter `### Security`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-ca-3.md
Task-Review: am Ende

### T6 — ca-issuer schreibt die Trust-Dateien vor dem übrigen Material (R-1009)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_trust.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @310dbcc2 2026-10-31T07:34:50+01:00
Review: approve (.ah-out/review/kern-ca-3/T6.verdict.json)
Änderung: `provision_boot_material` schreibt `CA_TRUST_DIR` als ersten Schritt: scheitert danach die Gateway- oder frps-Bereitstellung, liegt keine Liste mit einem gesperrten Zwischenzertifikat mehr im Volume (security-Nit zu T2). Test: ein Fehler in der Gateway-Bereitstellung lässt die neuen Trust-Dateien stehen.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_trust.py tests/test_rotation.py
Doku: keine (Reihenfolge beim Start)
Abhängt von: T2

## Entscheidungen
- 2026-10-31: R-1021 (Root-Erneuerung) fährt nicht mit — ändert Vertrauensanker von Agent und Desktop und den Erneuerungsvertrag (Kevins Bereich, Architektur); verschoben nach tasks/kern-ca-5.md, Frage am Gate.
- 2026-10-31: Trust-Daten für den Server über ein Volume mit öffentlichem Material statt einer DB-Tabelle (keine Migration); fehlende Datei ist fail-closed wie R-0900.
- 2026-10-31: T2 hängt `ca-trust` nur lesbar in den Server, setzt `CA_TRUST_DIR` dort aber erst in T3: `test_env_parity` verlangt, dass der Server jeden gesetzten Schlüssel liest.
- 2026-10-31: T6 aus dem security-Nit zu T2 (Trust-Dateien zuerst schreiben), als eigene ca-issuer-Task vor T3 gebaut.
