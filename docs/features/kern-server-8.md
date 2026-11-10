# Server: wiederholter Skalar-Query-Parameter ergibt 422 (kern-server-8)

Roadmap: R-1132 (vor dem Release 0.47.0, R-1110). API-Änderung von Kevin angenommen (Triage 2026-11-09): ein
wiederholter Skalar-Query-Parameter wird mit 422 abgelehnt.

## Problem / Motivation

FastAPI liest bei `?offset=1&offset=2` den letzten Wert und antwortet 200, obwohl das veröffentlichte Schema
`offset` als einen einzelnen Wert beschreibt. Im Monitoring hat R-1131 das behoben
(`apps/monitoring/app/core/query_params.py`, App-weite Abhängigkeit `reject_repeated_scalar_query`). Der Server
hat dieselbe Klasse, etwa `GET /api/connections` (`limit`, `offset`,
`apps/server/app/modules/connections/router.py:203-204`).

Der CA-Issuer ist nicht betroffen: keine seiner Routen (`/healthz`, `/enroll`, `/renew`, `/trust`,
`apps/ca-issuer/app/main.py`) hat einen Query-Parameter. Er bleibt unverändert.

## Ziel & Nicht-Ziele

- Ziel: Jeder im Schema als Einzelwert deklarierte Query-Parameter einer Server-Route ergibt bei mehrfacher Angabe
  422 mit `loc ["query", <name>]`, in der Form der übrigen Validierungsfehler. Array-Parameter und nicht deklarierte
  Parameter bleiben wie bisher.
- Nicht-Ziel: eine gemeinsame Bibliothek für Server und Monitoring (zwei getrennte Dienste mit eigenem Paket; die
  Kopie ist klein).

## Betroffene Komponenten & Dateien

- `apps/server/app/core/query_params.py` (neu, SPDX): wie im Monitoring, liest die Tabelle aus `app.openapi()`.
- `apps/server/app/main.py`: `FastAPI(..., dependencies=[Depends(reject_repeated_scalar_query)])`.
- `apps/server/tests/test_repeated_query.py` (neu, SPDX).

## Datenmodell / API / Migrationen

Keine Migration. Das Schema bleibt gleich (die Abhängigkeit nimmt nur `Request`), `test_openapi_snapshot` bleibt
grün. Sichtbar: eine Anfrage mit doppeltem Skalar-Parameter ist 422 statt 200. Web und Desktop senden keinen
Parameter doppelt.

## Trade-offs & Alternativen

- Middleware statt Abhängigkeit: kennt die Route nicht vor dem Routing; verworfen wie in R-1131.
- Pro Route `list[...]` prüfen: viele Stellen, leicht zu vergessen; verworfen.

## Risiken & Rollback

Ein Client, der heute einen Parameter doppelt sendet, bekommt 422. Rollback: die Zeile in `main.py` entfernen.

## Doku-Impact

Keine Seite unter `docs/` beschreibt das Verhalten bei doppelten Parametern; ein CHANGELOG-Eintrag
(`changelog.d/kern-server-8.md`, Fixed).

## Offene Fragen

Keine.
