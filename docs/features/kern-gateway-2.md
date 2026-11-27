# kern-gateway-2: Webhook-Trigger auf der zertifikatslosen Ebene, Upstream-Keepalive

Roadmap: R-1687 (BUG, Kevin 2026-11-27: angenommen, Webhook-Route auf :8444 ohne mTLS mit Token und Ratelimit),
R-1717 (REF, Kevin 2026-11-27: angenommen).

## Problem

**R-1687.** `POST /api/hooks/trigger` und `/api/hooks/trigger/{token}` sind als öffentlicher Ingest gedacht
(`apps/server/app/main.py:340`, ADR 0002, API-Referenz). Mit `MTLS_ENFORCE=true` (Standard) verlangt :443 ein
Client-Zertifikat (`apps/gateway/docker-entrypoint.sh:38-41`). :8444 kennt nur `/enroll` und `provision/activate`
(`apps/gateway/nginx.conf:166-210`). Ein externer Aufrufer ohne Zertifikat erreicht den Trigger im Standard also nicht.
Der Dialog zeigt ein curl auf `window.location.origin` ohne `--cert` (`apps/web/src/modals/WebhookTokenModal.svelte:29`).

**R-1717.** `proxy_set_header Connection ""` steht auf http-Ebene (`nginx.conf:60`). Jeder Block, der eigene
`proxy_set_header` setzt, verliert die Vererbung. Betroffen sind der :443-Server (`identity-headers.conf`, `nginx.conf:114`
und `:144`), der :8444-Server (`:187-188`) und `provision/activate` (`:199`). Diese Wege senden dem Upstream den Default
`Connection: close`, `keepalive 32` und `keepalive 16` (`:50`, `:55`) wirken dort nicht.

## Ziel

- :8444 leitet `POST /api/hooks/trigger` und `/api/hooks/trigger/<token>` an den Server weiter:
  - ohne Client-Zertifikat;
  - Identitäts-Header geleert, wie bei `activate`;
  - eigene `limit_req`-Zone `hooks`, damit Webhook-Last das Enrollment nicht drosselt;
  - Body-Grenze 1 MiB in diesen Locations (die Ebene sonst 16 KiB);
  - der Token bleibt die einzige Anmeldung, wie heute auf :443; der Server begrenzt zusätzlich 20 Aufrufe je Minute und Adresse.
- :443 bleibt unverändert, der Trigger ist dort weiter mit Zertifikat erreichbar.
- Der Dialog zeigt die URL auf dem Enrollment-Port. Die Antworten mit Token (Anlegen, Rotieren) tragen dazu `trigger_port`
  (`ENROLL_PORT`, `apps/server/app/core/config.py:287`); der Host bleibt der der Seite.
- Jeder `proxy_pass`-Weg zu `app` und `issuer` sendet `Connection ""`.

**Nicht-Ziele:** Den Trigger von :443 entfernen; die Ratelimits des Servers ändern; ein eigener Port für Webhooks.

## Komponenten und Dateien

| Bereich | Dateien |
|---|---|
| Gateway | `apps/gateway/nginx.conf`, `apps/gateway/identity-headers.conf` |
| Gateway-Tests | `apps/server/tests/test_gateway_container.py`, `scripts/tests/integration_stack_test.sh` |
| Server | `apps/server/app/modules/hooks/router.py`, `apps/server/app/modules/hooks/schemas.py`, `apps/server/tests/test_hooks.py`, OpenAPI-Snapshot |
| Web | `apps/web/src/modals/WebhookTokenModal.svelte`, ein Test dazu, `apps/web/src/lib/api/` (Typ) |
| Doku | API-Referenz DE+EN, Installation DE+EN (Port 8444), Betrieb DE+EN (zertifikatslose Ebene), `changelog.d/kern-gateway-2.md` |

## API und Datenmodell

- Additiv: `trigger_port: int` in `HookCreatedResponse` (nur mit Token) und `HookTokenOut`. Keine Migration.
- Gateway: neue Zone `limit_req_zone $binary_remote_addr zone=hooks:10m rate=5r/s`, `burst=20 nodelay`, Status 429 wie die
  übrigen Zonen.

## Trade-offs

- Port im Dialog: aus der Server-Antwort statt fest 8444, weil `ENROLL_PORT` den Host-Port setzt
  (`docker-compose.yml:291`). Alternative: fest 8444 im Web; falsch bei geändertem `ENROLL_PORT`. Das ist die offene Frage.
- Body-Grenze 1 MiB statt 10 MiB (:443): Webhook-Payloads sind JSON aus Fremdsystemen, 1 MiB reicht für die Beispiele
  unter `docs/examples/`, und die zertifikatslose Ebene bleibt klein.

## Risiken und Rollback

- Neue zertifikatslose Tür: Nur genau die zwei Trigger-Pfade, `location /` auf :8444 bleibt 404. Die Identitäts-Header
  werden geleert, und der Trigger hat keinen Scope-Guard (`main.py:340`). `security` prüft jede Gateway-Task.
- Rollback: Image zurück.

## Doku-Impact

API-Referenz DE+EN (Trigger auf :8444 ohne Zertifikat), Installation DE+EN (Port 8444 auch für Webhooks), Betrieb DE+EN
(Ratelimit der zertifikatslosen Ebene), CHANGELOG.

## Offene Fragen

- Keine. Kevin 2026-11-27: `trigger_port` aus den Token-Antworten.
