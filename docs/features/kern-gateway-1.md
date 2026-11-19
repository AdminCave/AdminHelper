# Gateway: interne Dienst-Routen nur im Compose-Netz

Roadmap R-1604 (Härtung). Einzelheiten zum Anlass stehen nur unter `tasks/private/`.

## Problem / Motivation
Der Server hat unter `/api/internal/*` Routen für den Austausch zwischen den Diensten (Monitoring → Server:
Inventar, Events, Zustell-Einstellungen), geschützt mit `X-Internal-Key`. Der Gateway reicht auf dem Access-Plane
`:443` mit `location / { proxy_pass http://app; }` jeden Pfad an den Server durch, also auch diese. Kein
Verbraucher braucht den Weg: das Monitoring spricht den Server direkt im Compose-Netz an
(`SERVER_HUB_URL=http://server:8080`, `docker-compose.yml`).

## Ziel & Nicht-Ziele
- Ziel: Der Gateway beantwortet `/api/internal` und alles darunter auf `:443` selbst mit 404, ohne den Server zu
  fragen. Die Dienste erreichen die Routen weiter direkt.
- Nicht-Ziele: keine Änderung an den Routen, am Schlüssel oder an `:8444`/`:8445` (dort antwortet ohnehin jeder
  fremde Pfad 404).

## Betroffene Komponenten & Dateien
- `apps/gateway/nginx.conf` — Server-Block `listen 443`: neue `location ^~ /api/internal { return 404; }`.
- `apps/server/tests/test_gateway_container.py` — Konfigurationsprüfung und Container-Probe.
- `docs/developer/server.html`, `docs/en/developer/server.html` — Tabellenzeile `/api/internal`.
- `changelog.d/kern-gateway-1.md`.

## Datenmodell / API / Migrationen
Keine. Kein Vertrag ändert sich für Clients: die Routen waren nie für Clients gedacht (OpenAPI unverändert).

## Externe Integrationen
nginx: `location`-Auswahl auf der normalisierten URI (Prozentkodierung dekodiert, `.`/`..` aufgelöst, doppelte
Schrägstriche zusammengefasst bei `merge_slashes on`, Standard); `^~` beendet die Suche ohne Regex-Locations
(https://nginx.org/en/docs/http/ngx_http_core_module.html#location, #merge_slashes).

## Trade-offs & Alternativen
- **Prefix ohne Schrägstrich** (`/api/internal`): trifft auch `/api/internalX`; solche Routen gibt es nicht und
  sollen nicht entstehen. Mit Schrägstrich bliebe `/api/internal` selbst durchgereicht. Empfehlung: ohne.
- **404 statt 403:** verrät nicht, dass es den Pfad gibt, und gleicht `:8444`/`:8445`.
- **Allow-Liste statt Sperrpfad** (nur bekannte Präfixe durchreichen): größer, bricht jede neue Route; nicht jetzt.

## Risiken & Rollback
Ein Verbraucher, der die Routen doch über den Gateway ruft, bekäme 404. Monitoring, Agent, Desktop und Web nutzen
den Weg nicht (Monitoring direkt, die übrigen kennen den Schlüssel nicht). Die Desktop-GUI-E2E
(`notification-push.live.js`, `injectEvent`) speiste ihre Events bisher über den Gateway ein; sie geht jetzt über
`docker compose exec` in den Server-Container (T2). Rollback: die Location entfernen.

## Doku-Impact
`docs/developer/server.html` (DE+EN), Zeile `/api/internal` der Routentabelle: nur im Compose-Netz erreichbar.
CHANGELOG-Fragment.

## Offene Fragen
Keine.
