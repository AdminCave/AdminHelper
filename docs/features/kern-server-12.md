# kern-server-12 — Ein Monitoring-Client im Server, Internal-Key-Gate nach core

Roadmap: R-0691 (REF, Code-Audit 2026-10-21, SRV-13).

## Problem / Motivation

Der Server spricht das Monitoring auf vier eigenen Wegen an, jeder setzt URL, Header und Timeout selbst zusammen:

| Weg | Datei | URL | Timeout |
|---|---|---|---|
| Tag-Sync anstoßen | `modules/servers/router.py:86-96` | `f"{MONITOR_SERVICE_URL}/templates/tag-sync"`, **ohne** `rstrip('/')` | 30 s |
| Cleanup nach Server-Löschen | `modules/servers/router.py:313-326` | `f"{MONITOR_SERVICE_URL}/servers/{id}/cleanup"`, **ohne** `rstrip('/')` | 5 s |
| Agent-Key beim Provisioning | `modules/provisioning/helpers.py:52-55` | mit `rstrip('/')` | Parameter |
| Provisioning-Fortschritt | `modules/provisioning/progress.py:93-99` | mit `rstrip('/')` | 3 s, connect 1 s |

Dazu kommt der Proxy (`modules/monitoring_proxy/router.py:54`, async, mit `rstrip('/')`).

Steht `MONITOR_SERVICE_URL` mit Slash am Ende, entsteht beim Tag-Sync und beim Cleanup `//`. Die Monitoring-Routen
ohne Präfix passen darauf nicht und antworten mit 404. Folgen: Der Cleanup nach dem Löschen eines Servers scheitert,
seine Checks verwaisen, und der Tag-Sync wird nicht angestoßen. Beides landet nur als WARNING im Log.

Außerdem importiert `servers/router.py:28` das Gate `require_internal_key` aus `notifications/router.py`, also einen
Router aus einem anderen Router.

## Ziel & Nicht-Ziele

Ziel:
- `app/core/monitoring_client.py` (neu): `base_url()` liest `config.MONITOR_SERVICE_URL` zur Aufrufzeit ohne Slash
  am Ende, und `request(method, path, *, timeout)` setzt URL und `X-Internal-Key` gleich zusammen. Die vier
  synchronen Wege rufen `request`, der Proxy nimmt `base_url()`.
- Jeder Weg behält seinen Timeout und seine Fehlerbehandlung.
- `require_internal_key` zieht samt Security-Scheme nach `app/core/auth.py`, neben die übrigen Auth-Abhängigkeiten.
  Der OpenAPI-Snapshot bleibt gleich (Scheme-Name `InternalKey`).

Nicht-Ziele: kein gemeinsamer Timeout, keine Retries, kein geteilter Connection-Pool für die synchronen Wege, keine
Änderung am Proxy-Forwarding, keine neue Route.

## Betroffene Komponenten & Dateien

Server: `app/core/monitoring_client.py` (neu), `app/core/auth.py`, `modules/servers/router.py`,
`modules/provisioning/helpers.py`, `modules/provisioning/progress.py`, `modules/monitoring_proxy/router.py`,
`modules/notifications/router.py`.

Tests: `test_monitoring_client.py` (neu), `test_tag_sync_notify.py` und die Tests, die
`servers_router.httpx` patchen (`test_frp_policy.py`, `test_identity_revocation.py`, `test_provisioning.py`,
`test_servers_authz.py`), sowie `test_route_auth_gate.py` (Kommentar zum Ort des Gates).

## Datenmodell / API / Migrationen

Keine Migration, keine API-Änderung, der OpenAPI-Snapshot bleibt gleich. Sichtbar ändert sich nur, dass ein
`MONITOR_SERVICE_URL` mit Slash am Ende Tag-Sync und Cleanup nicht mehr bricht.

## Externe Integrationen

Keine neue: die Monitoring-Routen (`/templates/tag-sync`, `/servers/{id}/cleanup`, `/agent-keys/{id}`,
`/agent/{id}/state`) bleiben, wie sie sind.

## Trade-offs & Alternativen

- **Ein `request`-Helfer statt je einer Funktion pro Endpunkt:** Die Antwortbehandlung ist je Weg verschieden (Log
  bei `>= 300`, JSON-Feld, Fortschritt). Ein dünner Helfer vereinheitlicht URL und Header, ohne vier fast leere
  Wrapper zu schaffen. Empfehlung: `request`.
- **Timeouts je Weg statt einem gemeinsamen:** Fire-and-forget im Worker (30 s), Cleanup im Request (5 s) und
  Fortschritts-Polling (3 s) haben verschiedene Gründe. Ein gemeinsamer Wert wäre für mindestens einen falsch.
- **Gate in `core/auth.py` statt in einer neuen Datei:** `core/auth.py` steht in `scripts/dev/review-risk.txt`.
  Eine neue Datei unter `core/` würde das Gate aus der Sicherheitsprüfung fallen lassen.

## Risiken & Rollback

Der Agent-Key beim Provisioning und das Internal-Key-Gate sind Risikopfade (`security` je Task). Die Tests decken
jeden Weg samt Slash am Ende. Rollback: Revert des Merge-Commits, keine Daten berührt.

## Doku-Impact

`changelog.d/kern-server-12.md` (Fixed: Slash am Ende von `MONITOR_SERVICE_URL`). Sonst keine, weil die Doku nur
den Default ohne Slash nennt.

## Offene Fragen

Keine aus Kevins Bereich: Die Roadmap-Zeile nennt Fehler und Vorschlag, und das Verhalten ändert sich nur am
fehlerhaften Rand.
