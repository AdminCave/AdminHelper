<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ca-issuer: Client-Identität nur vom Gateway (kern-ca-14)

Roadmap: R-0840 · Ledger: `tasks/kern-ca-14.md`

## Problem / Motivation

Der Gateway terminiert mTLS und reicht das geprüfte Client-Zertifikat als `X-Client-Verify`/`X-Client-Cert` an
`server` und `ca-issuer` weiter. Der `server` wertet diese Header nur aus, wenn der direkte TCP-Peer eine aktuelle
Adresse des Compose-Dienstes `gateway` ist (`_peer_is_gateway` in `apps/server/app/core/identity.py`). Der
`ca-issuer` (`_presented_cert` in `apps/ca-issuer/app/main.py`, genutzt von `/renew` und `/trust`) verlässt sich
dagegen allein auf das Compose-Netz `pki`. In diesem Netz hängt neben dem Gateway auch `postgres`. Die Grenze
des ca-issuer soll dieselbe sein wie die des Servers.

## Ziel & Nicht-Ziele

Ziel:
- Der `ca-issuer` wertet `X-Client-Verify`/`X-Client-Cert` nur aus, wenn die Anfrage direkt vom Dienst `gateway`
  kommt. Von jeder anderen Gegenstelle gilt die Anfrage als ohne Zertifikat (401). Eine Warnzeile nennt den Peer,
  höchstens einmal je Minute.
- uvicorn im `ca-issuer` wertet keine `X-Forwarded-*`-Header aus (`--no-proxy-headers`), wie beim Server.
- Ein Stack-Test belegt die Grenze live: Header aus einem anderen Container des Netzes `pki` ergeben 401, über den
  Gateway erneuert das Gerät weiter.

Nicht-Ziele:
- Kein Umbau des Netzes `pki` und kein Wechsel der DB-Anbindung des ca-issuer.
- Keine gemeinsame Bibliothek für die Namensauflösung mit dem Server: das ca-issuer-Image trägt `ah_common` nicht
  (R-0699).
- `/enroll` bleibt unverändert: es prüft ein Einmal-Token, keine Header.

## Betroffene Komponenten & Dateien

- `apps/ca-issuer/app/main.py` (`_presented_cert`), neues Modul `apps/ca-issuer/app/gateway_peer.py` (SPDX), dazu
  `apps/ca-issuer/docker-entrypoint.sh` und der Kommentar an `_verify_ca_signed` in `apps/ca-issuer/app/issuer.py`.
- Tests: neues `apps/ca-issuer/tests/test_gateway_peer.py`. Die bestehenden Tests mit Headern (`test_enroll_renew.py`,
  `test_trust_generation.py`, `test_schemathesis.py`) laufen über eine Fixture, die den Test-Client als Gateway gelten
  lässt.
- `scripts/tests/integration_stack_test.sh`: ein neuer Schritt mit Headern direkt an `ca-issuer:8090` aus dem
  postgres-Container.
- Doku: `docs/developer/index.html`, `docs/admin/installation.html` und die EN-Seiten dazu.

## Datenmodell / API / Migrationen

Keine Migration, kein neuer Endpunkt. Verhalten: `/renew` und `/trust` antworten 401, wenn die Header nicht vom
Gateway kommen. Über den Gateway bleibt alles gleich.

## Externe Integrationen

Docker-Compose-DNS (Dienstname `gateway` löst auf die Adressen des Gateway-Containers auf); uvicorn-Option
`--no-proxy-headers` (https://www.uvicorn.org/settings/#http).

## Trade-offs & Alternativen

- **Peer-Prüfung im ca-issuer (Empfehlung):** dieselbe Grenze wie beim Server, unabhängig davon, wer künftig im Netz
  `pki` hängt.
- **postgres aus dem Netz `pki` nehmen:** dann bräuchte der ca-issuer einen anderen Weg zur DB (eigenes Netz nur
  mit postgres). Das ändert `docker-compose.yml` und den Update-Pfad, und die Grenze hinge wieder an der Topologie.
- **Geteiltes Geheimnis Gateway → ca-issuer:** ein neues Secret mit Rotation und Install-Pfad. Mehr Aufwand ohne
  Vorteil gegenüber der Peer-Prüfung.

Auflösung: der Name `gateway` wird mit kurzer Gültigkeit (wenige Sekunden) zwischengespeichert. Bei einem
unbekannten Peer wird einmal sofort neu aufgelöst, denn ein neu angelegter Gateway kommt mit neuer Adresse zurück.
Schlägt die Auflösung fehl, gilt kein Peer als Gateway (fail-closed).

## Risiken & Rollback

- Ein Aufrufer, der den ca-issuer ohne Gateway mit Headern anspricht, bekommt 401. Laut Code ruft nur der Gateway
  `/renew` und `/trust` (nginx `upstream ca-issuer:8090`). Der Stack-Test fährt die Erneuerung über den Gateway weiter.
- Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/developer/index.html` und `docs/admin/installation.html` (DE+EN): Den ca-issuer schützt nicht mehr allein das
Netz `pki`, er prüft wie der Server die Gegenstelle. CHANGELOG-Fragment `changelog.d/kern-ca-14.md`.

## Offene Fragen

Keine.
