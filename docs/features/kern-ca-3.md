<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-3 — Vertrauen je Scope genau an den geführten Zwischenzertifikaten (R-1009)

## Problem / Motivation
`rotate-intermediates --compromised <scope>` (`apps/ca-issuer/app/rotation.py`) nimmt das abgelöste
Zwischenzertifikat aus `<scope>-retired.pem` und damit aus den Trust-Bundles. Die Bundles tragen aber die Root als
Anker (`apps/ca-issuer/app/storage.py:452`, `bundle = inter.chain + …`), und Gateway wie frps bauen die Kette mit
dem, was der Client mitschickt. Die Betriebsdoku sagt das offen (`docs/admin/betrieb.html`, Abschnitt
`ca-rotation`: „ein Client, der sein Zwischenzertifikat mitschickt, kommt mit einem Zertifikat des alten weiter
durch den TLS-Handshake“) und verlangt deshalb den Widerruf aller Geräte des Scopes. Ziel ist, dass die Sperre an
frps und am Server ohne diesen Umweg wirkt.

## Ziel & Nicht-Ziele
Ziel:
- frps vertraut Client-Zertifikaten nur, wenn sie von einem geführten Zwischenzertifikat ausgestellt sind (aktuell
  oder abgelöst, nicht gesperrt), nicht mehr über die Root.
- Der Server nimmt ein vom Gateway gemeldetes Client-Zertifikat nur an, wenn ein geführtes Zwischenzertifikat seines
  Scopes es direkt ausgestellt hat; sonst die 403 `ERR_CERT_REVOKED` wie bei einem widerrufenen Gerät, in beiden
  `MTLS_ENFORCE`-Modi.

Nicht-Ziele:
- Root-Erneuerung (R-1021, eigener Zug) und die Prüfung des Servers durch Agent und Desktop, die an der Root hängt:
  beides schließt erst eine neue Root.
- Kein OCSP/CRL, keine Änderung an nginx (OpenSSL braucht die selbstsignierte Root als Anker; die Prüfung je
  Zwischenzertifikat macht deshalb der Server).
- Keine Änderung an `/renew` (prüft schon gegen aktuell + abgelöst, `apps/ca-issuer/app/issuer.py`).

## Betroffene Komponenten & Dateien
- `apps/ca-issuer/app/storage.py` (`_provision_server_material:420`, `ensure_frps_cert:529`): Bundle für frps ohne Root.
- `apps/ca-issuer/app/main.py` (`provision_boot_material:32`), neues Modul `apps/ca-issuer/app/trust.py`,
  `apps/ca-issuer/app/config.py`: je Scope eine öffentliche Datei `<scope>.pem` (aktuelles + abgelöste
  Zwischenzertifikate) in ein neues Volume `ca-trust`, bei jedem Start atomar geschrieben.
- `docker-compose.yml`: Volume `ca-trust`, im `ca-issuer` schreibbar, im `server` nur lesbar; Env für den Pfad.
- `apps/server/app/core/identity.py` (`get_client_identity:145`, `_refused:298`), `apps/server/app/core/config.py`:
  Aussteller-Prüfung; Tests `apps/server/tests/test_mtls_scope.py`, `test_identity_source.py`,
  `test_identity_revocation.py`, `test_certificate_check.py` brauchen eine Test-Trust-Datei (Fixture).
- `scripts/tests/integration_stack_test.sh`: Gegenprobe am echten Stack.

## Datenmodell / API / Migrationen
Keine Migration, keine neue Route. Neu ist ein interner Dateivertrag ca-issuer → server: Verzeichnis mit
`tunnel.pem`, `access.pem`, `internal.pem` (PEM-Bundle, nur Zertifikate). Sichtbar ändert sich nur, dass ein
Zertifikat eines gesperrten Zwischenzertifikats die bestehende 403 `ERR_CERT_REVOKED` bekommt; Clients kennen den Code.

## Externe Integrationen
frps nutzt Go `crypto/tls` (`transport.tls.trustedCaFile` → `ClientCAs`); Go wertet jedes Zertifikat im Pool als
Anker, selbstsigniert oder nicht (https://pkg.go.dev/crypto/x509#VerifyOptions). Vor dem Bau nachlesen und im Stack
belegen.

## Trade-offs & Alternativen
- **Volume mit öffentlichem Material (gewählt)** gegen **Tabelle in der Server-DB** (wie `infra_certificates`): die DB
  bräuchte eine Migration und eine neue Spalte für das PEM; das Volume trägt nur öffentliche Zertifikate, der Server
  liest es mit mtime-Cache. Empfehlung Volume.
- Prüfung in nginx statt im Server: nginx bietet keinen Anker ohne Root (kein `partial_chain`), verworfen.
- Fehlt die Trust-Datei eines Scopes oder ist sie unlesbar, lehnt der Server Zertifikate dieses Scopes ab und loggt
  einen Fehler (fail-closed wie R-0900). Der `ca-issuer` startet nach dem Server; bis er geschrieben hat, gibt es
  beim ersten Start noch keine Client-Zertifikate, bei einem Update nur Sekunden.

## Risiken & Rollback
- Fehler in der Aussteller-Prüfung sperrt alle Geräte aus (403). Gegenmittel: Tests mit aktuellem und abgelöstem
  Zwischenzertifikat, Stack-Probe mit echtem Enrollment. Rollback: Revert des Server-Commits.
- frps ohne Root im Bundle: ein Client, dessen Aussteller weder aktuell noch abgelöst ist, scheitert. Das ist die
  Absicht; abgelöste stehen weiter im Bundle.
- Nach einer Rotation ohne Neustart des `ca-issuer` gelten weiter die alten Dateien; die Doku verlangt den Neustart
  schon heute.

## Doku-Impact
`docs/admin/betrieb.html` / `docs/en/admin/operations.html` (Abschnitt `ca-rotation`: was nach `--compromised`
wirkt, was erst eine neue Root schließt), Architektur-Seite zu mTLS-Vertrauen (DE+EN, per grep bestimmt),
`changelog.d/kern-ca-3.md` unter `### Security`, neutral formuliert.

## Offene Fragen
- R-1021 (Root-Erneuerung) fährt nicht mit: sie ändert die Vertrauensanker von Agent und Desktop und den
  Erneuerungsvertrag; Frage an Kevin, ob als Architektur-Vorhaben (`start-session.sh arch R-1021`).
