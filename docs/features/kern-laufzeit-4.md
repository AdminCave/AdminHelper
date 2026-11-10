# Laufzeit: Refresh-Cookie hinter dem Gateway (kern-laufzeit-4)

Roadmap: R-1274 (Kevin 2026-11-10 Triage).

## Problem / Motivation
`_set_refresh_cookie` (`apps/server/app/modules/users/auth_router.py:111`) setzt `Secure` nach dem Schema der
Anfrage (`request.url.scheme`, `:120`). Der Server spricht hinter dem Gateway nur HTTP, und uvicorn läuft seit
kern-laufzeit-3 mit `--no-proxy-headers` (`apps/server/docker-entrypoint.sh`): das Schema ist dort immer `http`, das
Cookie kommt ohne `Secure`. Die Entwickler-Doku (`docs/developer/server.html:79`, `api-reference.html:39`) beschreibt
es als `HttpOnly; Secure; SameSite=Strict`.

## Ziel & Nicht-Ziele
Ziel: Das Cookie trägt `Secure`, wenn die Anfrage selbst HTTPS ist oder vom Gateway kommt (`_from_gateway`, der
direkte Peer, `apps/server/app/core/identity.py:122`) und das Gateway `X-Forwarded-Proto: https` setzt
(`apps/gateway/identity-headers.conf:10`, überschreibt einen mitgeschickten Header). Ohne Gateway (Dev auf
`http://localhost`, Testclient) bleibt es beim Schema der Anfrage.
Nicht-Ziele: kein Wechsel zurück zu uvicorns Proxy-Headern, keine Änderung an `TRUSTED_PROXIES`, an HSTS oder an
anderen Cookies (es gibt keine weiteren).

## Betroffene Komponenten & Dateien
- `apps/server/app/modules/users/auth_router.py`: `_set_refresh_cookie`; den Header liest es nur, wenn er da ist, und
  fragt erst dann `_from_gateway` (die Prüfung warnt für fremde Peers).
- `apps/server/tests/test_auth.py` (`TestRefreshCookie`, `:271`): Secure mit Gateway-Peer und Header `https`; ohne
  Header nicht; mit Header, aber fremdem Peer nicht (Marker `identity_source` hebt die Stand-in-Fixture auf,
  `apps/server/tests/conftest.py:209`).

## Datenmodell / API / Migrationen
Keine. Das Attribut `Secure` ändert keinen Vertrag; Browser über HTTPS senden das Cookie wie bisher.

## Externe Integrationen
Keine neue; der Header kommt vom eigenen Gateway.

## Trade-offs & Alternativen
- uvicorn `--forwarded-allow-ips=<gateway>`: zweiter Vertrauensweg, den kern-laufzeit-3 gerade entfernt hat.
- `Secure` immer: bricht die Anmeldung über `http://localhost` in der Entwicklung. Empfehlung: Gateway-Peer + Header.

## Risiken & Rollback
Ein Browser, der über das Gateway per HTTP käme, bekäme ein Cookie, das er nicht zurückschickt: das Gateway setzt
`https` nur auf TLS-Listenern (`$scheme`); auf Port 80 leitet es um. Rollback: Revert des Commits.

## Doku-Impact
Die Doku beschreibt schon `Secure`; nur `changelog.d/kern-laufzeit-4.md`.

## Offene Fragen
Keine.
