<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# mTLS: Server und Gateway lesen `MTLS_ENFORCE` gleich, Identitäts-Header nur vom Gateway

Stand des Codes: `origin/main@53a7dbc5`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/mtls-consistency.md`. Härtung (Kevin 2026-10-22).

## Problem / Motivation

1. **`MTLS_ENFORCE` wird an zwei Stellen verschieden gelesen.** Die Doku verspricht, dass **eine** Variable Gateway
   und Server steuert (`docs/admin/betrieb.html:262`, EN `docs/en/admin/operations.html:220`). Das Gateway liest sie in
   `apps/gateway/docker-entrypoint.sh:37-53`: `1|true|yes|on` → `ssl_verify_client on`, `0|false|no|off` → `optional`,
   jeder andere Wert → `on` mit einer Warnung „fail-closed“ (Kommentar `:47-49`). Der Server liest sie in
   `apps/server/app/core/config.py:144` als `… .lower() in ("1", "true", "yes")`. Probe an `origin/main@53a7dbc5`
   (der `case`-Block per `awk` wie in `scripts/tests/gateway_mtls_test.sh`, mit `sh` ausgeführt; der Ausdruck des
   Servers mit Python 3.13):

   | Wert | Gateway | Server |
   |---|---|---|
   | `true`, `TRUE`, `1`, `yes`, ungesetzt | erzwungen | erzwungen |
   | `false`, `0`, `no`, `off` | permissiv | permissiv |
   | `on`, `On` | erzwungen | **permissiv** |
   | leer (nur außerhalb von Compose; Compose setzt `${MTLS_ENFORCE:-true}`, `docker-compose.yml:74`) | erzwungen | **permissiv** |
   | `ture`, `enforced`, ` true` | erzwungen, mit Warnung | **permissiv**, ohne Warnung |

   Mit `MTLS_ENFORCE=on` verlangt das Gateway am Handshake ein Zertifikat, der Server prüft den Scope je Route aber
   nur im Log (`apps/server/app/core/identity.py:254-277`). Der Kommentar zum Default (`config.py:136-143`) will genau
   das vermeiden: ein Server, der still permissiv läuft, obwohl der Betreiber Erzwingen meint.

2. **Der Server nimmt die Identitäts-Header von jeder Gegenstelle an.** Das Gateway terminiert mTLS und reicht das
   geprüfte Zertifikat als `X-Client-Verify` und `X-Client-Cert` weiter (`apps/gateway/identity-headers.conf:6-10`);
   eingehende Header dieses Namens überschreibt es (`scripts/tests/integration_stack_test.sh:129-145`).
   `get_client_identity` (`apps/server/app/core/identity.py:78-105`) liest die Header, ohne zu prüfen, woher die
   Anfrage kommt. Begründet wird das mit „kein Host-Port“ (`identity.py:5-11`, `docker-compose.yml:39-42`,
   `docs/developer/index.html:106`, EN `docs/en/developer/index.html:84`). Im Compose-Netz `default` erreichen aber
   neben dem Gateway auch scheduler, monitoring, victoria, redis und postgres den Server unter `server:8080`
   (`server` hat kein `networks:`, `docker-compose.yml:37-131`; die Netze `:449-456`). ADR 0001 §3.2
   (`docs/adr/0001-unified-pki-and-secure-deployment.md:128-129`) beschreibt das Soll: der Server „liest die
   verifizierte Identität aus dem vom Gateway gesetzten Header“. Gewünscht ist, dass der Server das selbst festhält:
   Identitäts-Header zählen nur, wenn die direkte Gegenstelle das Gateway ist.

   Die Prüfung der Zertifikatskette macht dabei weiterhin das Gateway (Abschnitt „Externe Integrationen“): Kommen die
   Header nur vom Gateway, trägt jede Anfrage mit `X-Client-Verify: SUCCESS` ein Zertifikat, das nginx gegen
   `client-ca.pem` geprüft hat (`apps/gateway/nginx.conf:89-91`).

## Ziel & Nicht-Ziele

Ziel:
- **(T1)** Der Server liest `MTLS_ENFORCE` mit derselben Tabelle wie das Gateway: `1|true|yes|on` erzwungen,
  `0|false|no|off` permissiv, leer oder ungesetzt erzwungen, jeder andere Wert erzwungen mit einer WARNING im Log
  (Groß-/Kleinschreibung egal, kein Abschneiden von Leerzeichen, wie im Gateway). Ein Test hält die Tabelle des
  Servers und den `case`-Block des Gateways gleich. *Wartet auf Kevin (Offene Fragen 1).*
- **(T2)** `get_client_identity` wertet `X-Client-Verify`/`X-Client-Cert` nur aus, wenn `request.client.host` eine
  Adresse des Compose-Dienstes `gateway` ist; sonst gilt die Anfrage als ohne Zertifikat (wie heute ohne Header).
  Die Adressen löst der Namens-Resolver aus `apps/server/app/core/middleware.py` auf (compose-hardening T11: Daemon-
  Thread, 30 s Cache, 5 s nach Fehlschlag). Kommt eine Anfrage mit `X-Client-Verify` von einer Adresse, die nicht im
  Cache steht, frischt der Server den Namen sofort auf (höchstens eine solche Auffrischung je Sekunde, Wartezeit
  höchstens 1 s) und prüft erneut — damit greift die Identität auch gleich nach einem Neuanlegen des Gateways (neue
  Adresse beim Update) und vor der ersten Auflösung beim Start. Eine ignorierte Identität loggt eine WARNING mit der
  Gegenstelle, höchstens einmal je Adresse und Minute.
- **(T3)** Der Stack-Test belegt im laufenden Stack: Header direkt an `server:8080` (ohne Gateway) geben keine
  Identität, derselbe Weg über das Gateway schon, auch gleich nach einem Neuanlegen des Gateways.

Nicht-Ziele:
- **Kettenprüfung im Server** (ein CA-Bundle für den Server, neues Volume, Kopplung an die CA-Rotation). Mit T2 kommen
  die Header nur vom Gateway, und nginx weist ein Zertifikat ab, dessen Kette nicht stimmt (Abschnitt „Externe
  Integrationen“). Ein Bundle im Server brächte nur etwas, wenn das Gateway selbst nicht mehr vertrauenswürdig ist;
  diesen Fall nimmt ADR 0001 §3.2 Bedingung (3) bewusst hin (`docs/adr/0001-unified-pki-and-secure-deployment.md:138-140`).
- **Netz-Topologie** (eigenes Netz für Gateway und Server), **gemeinsames Secret** zwischen Gateway und Server,
  **TLS zwischen Gateway und Server**: siehe „Trade-offs & Alternativen“.
- **Gateway:** keine Zeile. Den veralteten Kommentar `apps/gateway/nginx.conf:73-76` („optional = permissive rollout
  (default)“) korrigiert feature/docs-drift T6.
- **`TRUSTED_PROXIES`/`X-Forwarded-For`:** regelt feature/compose-hardening (T11, T12). T2 nutzt deren Resolver, aber
  eine eigene, feste Namensliste (`gateway`): `TRUSTED_PROXIES` kann per `.env` weitere Einträge bekommen, die für die
  Client-Adresse taugen, für die Identität aber nicht.
- **ca-issuer:** nicht Teil dieses Vorhabens.
- Keine neue Umgebungsvariable, keine Compose-Änderung, kein neues Secret.

## Betroffene Komponenten & Dateien

- **server** — `apps/server/app/core/config.py` (T1), `apps/server/app/core/identity.py` (T2),
  `apps/server/app/core/middleware.py` (T2, sofortige Auffrischung im Resolver aus compose-hardening T11),
  `apps/server/tests/conftest.py` (T2), neu `apps/server/tests/test_mtls_enforce_parse.py` (T1), neu
  `apps/server/tests/test_identity_source.py` (T2).
- **scripts** — `scripts/tests/integration_stack_test.sh` (T3).
- **Doku** — `.env.example`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html` (T1);
  `docs/developer/index.html`, `docs/en/developer/index.html` (T2); `CHANGELOG.md` (T1, T2).

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Schema, keine Änderung am OpenAPI-Snapshot. Sichtbares Verhalten:
- T1: Wer `MTLS_ENFORCE=on` (oder einen unbekannten Wert) gesetzt hat, bekommt im Server das Verhalten, das das
  Gateway schon hat: Zertifikate mit falschem Scope auf einer Route mit Scope-Prüfung ergeben 403 statt nur einer
  Log-Zeile (`identity.py:254-258`). Clients mit dem richtigen Scope merken nichts.
- T2: Anfragen, die nicht über das Gateway kommen, haben keine Zertifikats-Identität. Im Compose-Betrieb schickt kein
  Dienst außer dem Gateway diese Header: der Hub-Push des Monitorings nutzt `X-Internal-Key`
  (`apps/monitoring/app/alerter.py:425-427`, `apps/monitoring/app/tag_sync.py:50-51`), der scheduler ruft den Server
  nicht per HTTP. Der Dev-Server ohne Gateway (`DEVELOPMENT.md:762`) bekommt keine solchen Header.

## Externe Integrationen

- nginx `ngx_http_ssl_module` (https://nginx.org/en/docs/http/ngx_http_ssl_module.html, gelesen 2026-10-22):
  `ssl_verify_client on | off | optional | optional_no_ca` — „The `optional` parameter … requests the client
  certificate and verifies it if the certificate is present.“; nur `optional_no_ca` „does not require it to be signed
  by a trusted CA certificate“. `$ssl_client_verify`: „`SUCCESS`, `FAILED:reason`, and `NONE` if a certificate was not
  present“. `$ssl_client_escaped_cert`: „the client certificate in the PEM format (urlencoded)“. Fehlercode 495: „an
  error has occurred during the client certificate verification“.
- nginx-Quelltext `src/http/ngx_http_request.c`, `ngx_http_process_request` (gelesen 2026-10-22): bei gesetztem
  `ssl_verify_client` und einem Prüfergebnis ungleich `X509_V_OK` endet die Anfrage mit `NGX_HTTPS_CERT_ERROR`, außer
  bei `optional_no_ca`. Das Gateway setzt nur `on` oder `optional` (`docker-entrypoint.sh:37-53`), also erreicht kein
  Zertifikat mit falscher Kette den Server.
- Namensauflösung des Dienstnamens `gateway` über das DNS von Docker im Compose-Netz: wie compose-hardening T11.
- Starlette 1.3.1 (Server-Venv): `TestClient(app, client=(host, port))` setzt die Gegenstelle; damit testet T2 ohne
  Netz.

## Trade-offs & Alternativen

1. **Gegenstelle prüfen (T2, Empfehlung).** Kein neues Secret, kein Netz, keine Compose-Änderung; ein Update tauscht
   nur das Server-Image. Kosten: Abhängigkeit von der Namensauflösung; das Fenster nach einem Neuanlegen des Gateways
   schließt die sofortige Auffrischung. Außerhalb von Compose (kein Name `gateway`) gibt es keine Identität
   (fail-closed).
2. **Kettenprüfung im Server.** Der ca-issuer müsste ein öffentliches CA-Bundle in ein neues Volume schreiben, der
   Server die Signatur des Leafs gegen das Intermediate seines Scopes prüfen. Hält nur selbst erzeugte Zertifikate
   ab, nicht das Weiterreichen echter (öffentlicher) Zertifikate; drei Komponenten, neues Volume, Kopplung an die
   CA-Rotation. Mit 1. ist die Kette schon vom Gateway geprüft. Nicht gewählt.
3. **Gemeinsames Secret Gateway↔Server** (ein Header, den nur das Gateway kennt). Neues Pflicht-Secret in `.env`
   (`scripts/init-secrets.sh`, `.env.example`, Entrypoint des Gateways) oder ein Laufzeit-Token über ein Volume.
   Schützt so gut wie 1., hat aber mehr bewegliche Teile und berührt die Secret-Verwaltung. Nicht gewählt.
4. **Eigenes Netz nur für Gateway und Server.** postgres und redis muss der Server weiter erreichen, das Monitoring
   braucht `server:8080` für den Hub (`docker-compose.yml:382`). Abgegrenzt wären nur Dienste ohne eigenen Bedarf;
   der Hub-Weg müsste über das Gateway mit Zertifikat laufen, und ein Update legt Netze neu an. Nicht gewählt.
5. **TLS/mTLS zwischen Gateway und Server.** Eigenes Zertifikat für den Server, uvicorn mit TLS. Zu groß für den
   Nutzen. Nicht gewählt.
6. **T1: Start verweigern bei unbekanntem Wert** statt fail-closed. Änderte auch das Gateway; ein Tippfehler legte den
   Stack lahm. Nicht gewählt.

## Risiken & Rollback

- T2 hängt am Resolver aus compose-hardening T11; der Branch nimmt `origin/main` mit T11 auf, bevor T2 gebaut wird.
- T2 ändert, was die Server-Suite über Identitäten sieht: `apps/server/tests/conftest.py` bekommt eine autouse-Fixture,
  die in der Suite jede Gegenstelle als Gateway gelten lässt (die Tests bauen Requests ohne `client`,
  `apps/server/tests/test_mtls_scope.py:74-79`, `apps/server/tests/test_identity_revocation.py:122-125`, oder mit der
  Gegenstelle `testclient`); nur `test_identity_source.py` schaltet die echte Prüfung ein. Kein bestehender Test
  ändert seine Zusicherung.
- Neuanlegen des Gateways (Update): bis zur sofortigen Auffrischung höchstens 1 s Wartezeit für die erste Anfrage mit
  Zertifikat; T3 prüft das im Stack.
- Rollback: Image der Vorversion; keine Daten, kein Schema, keine Konfiguration zurückzudrehen. T1 zurück: wer `on`
  meinte, bekommt wieder das permissive Server-Verhalten.

## Doku-Impact

T1: `.env.example:109-118` und `docs/admin/betrieb.html:262` + EN `docs/en/admin/operations.html:220` nennen die
Werte (`true/1/yes/on`, `false/0/no/off`, alles andere erzwungen mit Warnung). T2: `docs/developer/index.html:106` +
EN `docs/en/developer/index.html:84`: der Server wertet die Identitäts-Header nur aus, wenn die Anfrage vom Gateway
kommt. CHANGELOG je Task (`### Changed`, umlautfrei).

## Überschneidungen & Merge-Reihenfolge

- **feature/compose-hardening** (aktiv): T11 (`apps/server/app/core/middleware.py`, Resolver) ist Voraussetzung für T2;
  T4 (`docs/developer/index.html:106`), T12 (`.env.example:120-124`), T8/T13 (`scripts/tests/integration_stack_test.sh`,
  neue Schritte vor der Summary). **Zuerst compose-hardening mergen.**
- **feature/docs-drift** (aktiv): T7 (`apps/server/app/core/identity.py:18-20`, `apps/server/tests/test_mtls_scope.py`,
  Test des Defaults), T6 (`apps/gateway/nginx.conf`); T2 ändert den Modul-Docstring `identity.py:5-11` daneben.
  Vor diesem Vorhaben mergen.
- **feature/server-fixes** (geplant): T4 (`identity.py`, `require_scope` → `check_scope`), T1 (`conftest.py`).
  **feature/fehlervertrag** (geplant): T2 (`identity.py`, Code in den 403). Andere Funktionen; wer zuerst merged,
  gewinnt, der andere nimmt `origin/main` auf.
- **feature/auth-sessions** (aktiv, T4), **feature/server-hardening**, **feature/smtp-hardening** (bereit):
  `apps/server/app/core/config.py`, andere Zeilen.
- **feature/update-rollback** (geplant): T3 (`scripts/tests/integration_stack_test.sh`). **feature/ca-rotation**
  (geplant): `integration_stack_test.sh`, `docs/admin/betrieb.html`. **feature/install-restore** (geplant):
  `docs/admin/betrieb.html`, andere Abschnitte. Keine gemeinsame Datei mit `docker-compose.yml` oder `apps/gateway/`.

## Offene Fragen

1. **T1 — Bedeutung von `on`, leer und unbekannten Werten im Server.** Optionen: (a) wie das Gateway: erzwungen,
   unbekannt mit WARNING (Empfehlung); (b) nur `on` ergänzen, Unbekanntes bleibt permissiv; (c) unverändert lassen
   und nur dokumentieren. Empfehlung (a): Gateway (`docker-entrypoint.sh:47-49`) und Default-Kommentar des Servers
   (`config.py:136-143`) wollen bei Zweifel Erzwingen, und die Doku sagt „eine Variable“. Trade-off: wer heute
   `MTLS_ENFORCE=on` gesetzt hat, sieht 403 für Zertifikate mit falschem Scope, wo bisher nur geloggt wurde.
