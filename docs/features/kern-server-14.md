# kern-server-14 — Server: stille Fehlschläge, Verbindungen, Abfragezahl, Health

Roadmap: R-1694, R-1695, R-1697, R-1698, R-1699, R-1734, R-1737, R-1744, R-1715. Entscheidungen von Kevin am
2026-11-24: R-1694 als Glocken-Notiz an die Admins (keine Migration, kein API-Feld); R-1744/R-1715 als neue Route
`GET /api/health` ohne Auth und ohne DB-Abfrage, auf die der Compose-Healthcheck umstellt.

## Problem / Motivation

- **R-1694:** Scheitert ein geplanter Hook (`hooks/scheduler.py`, `_run_scheduled`) oder ein Event-Hook
  (`core/events.py`, `_run_event`), steht das nur im Log. Auch der Fall „Hook-Limit erreicht“
  (`hooks/script_runner.py`, Semaphor mit acht Plätzen) endet so. Die Liste zeigt weiter ein frisches „zuletzt
  gelaufen“.
- **R-1695:** Die Agent-Routen `proxy_agent_report` und `proxy_agent_plan` (`monitoring_proxy/router.py`) ziehen
  über `require_scope` (`core/identity.py`) eine `get_db`-Session. Ihre Verbindung bleibt über den Forward an das
  Monitoring (Timeout 30 s) belegt. Hängt das Monitoring, leert sich der Pool, und die Steuerebene steht. Dasselbe
  gilt im Admin-Proxy `proxy_to_monitoring`.
- **R-1697:** Scheitert nach dem Löschen eines Servers der eine Cleanup-Aufruf an das Monitoring
  (`servers/router.py`), bleiben dessen Checks, manuelle Zuweisungen, Regeln und Liveness für immer. Der Tag-Abgleich
  (`apps/monitoring/app/tag_sync.py`) entfernt nur Zuweisungen mit `source == "tag"`.
- **R-1698:** Der E-Mail-Digest (`notifications/digest.py`, `_send`) zählt bei jedem Fehlschlag `attempts` hoch,
  ohne `next_attempt_at` zu setzen. Der Job läuft alle 5 min, nach fünf Fehlschlägen (rund 20 min Relay-Ausfall) ist
  der Digest endgültig `failed`. Der normale Versand (`outbox.py`) wartet linear 5/10/15/20 min.
- **R-1699:** `sync_policy` (`frp/policy.py`) ruft je Server mit Tunnel `get_allow_users` (`frp/_helpers.py`) und
  fragt dabei jedes Mal dieselben Admins ab (N+1, alle 60 s je Worker und nach jeder Benutzer- oder Server-Änderung).
- **R-1737:** `gen_bulk_zip` (`frp/generate_router.py`) lädt `User.servers` per `selectinload`, ohne Test der
  Abfragezahl.
- **R-1734:** Nachlese kern-server-11: fehlende Routen-Tests für die 409-Antworten bei einem vergebenen
  Benutzernamen (Bootstrap und API), ein veralteter Kommentar in `notifications/router.py` und ein Prüfpunkt zur
  Datei der FRP-Policy nach einem CLI-Aufruf (Einzelheiten in `tasks/private/kern-server-11-nachlese.md`).
- **R-1744, R-1715:** Die Installations-Doku (DE und EN) empfiehlt `/api/health`, die Route gibt es aber nicht. Der
  Compose-Healthcheck des Servers ist ein TCP-Connect, der einen hängenden Prozess nicht erkennt. Monitoring
  (`/health`) und CA-Issuer (`/healthz`) haben HTTP-Health.

## Ziel & Nicht-Ziele

Ziel: Fehlschläge werden sichtbar oder heilen sich selbst, keine DB-Verbindung wartet auf das Monitoring, die
Policy-Berechnung fragt die Berechtigten einmal ab, und der Server hat eine echte Health-Route, die die Doku nennt
und Compose benutzt.

Nicht-Ziele:
- keine Spalten `last_status`/`last_error` an `hooks` und keine Anzeige in der Hook-Liste (Kevin 2026-11-24);
- keine DB-Prüfung in `/api/health`: ein DB-Ausfall soll keinen Neustart-Kreislauf des Containers auslösen;
- keine Umbenennung der Health-Routen von Monitoring und CA-Issuer;
- kein Umbau des Digest-Zeitplans selbst, nur der Backoff bei Fehlschlag.

## Betroffene Komponenten & Dateien

- Server: `app/modules/hooks/scheduler.py`, `app/core/events.py`, `app/modules/hooks/script_runner.py`,
  `app/modules/notifications/service.py` (`notify_users`), `app/modules/monitoring_proxy/router.py`,
  `app/core/identity.py`, `app/modules/notifications/digest.py`, `app/modules/frp/policy.py`,
  `app/modules/frp/_helpers.py`, `app/modules/frp/generate_router.py`, `app/main.py`,
  `app/modules/notifications/router.py`, dazu die Tests unter `apps/server/tests/`.
- Monitoring: `app/tag_sync.py`, `app/server_cleanup.py`, `tests/test_tag_sync.py`.
- Betrieb: `docker-compose.yml` (Healthcheck des Servers), `apps/server/tests/test_compose_healthchecks.py`.
- Doku: `docs/admin/installation.html`, `docs/en/admin/installation.html`, die Hook-Seite der Admin-Doku (DE und EN),
  `changelog.d/kern-server-14.md`.

## Datenmodell / API / Migrationen

- Keine Migration. Der Digest-Backoff nutzt die vorhandene Spalte `notification_outbox.next_attempt_at`.
- Neue Route `GET /api/health` → `200 {"status": "ok"}`, ohne Auth, ohne DB. `tests/openapi.snapshot.json` nimmt sie
  auf (API-Vertrag nach Kevins Ja vom 2026-11-24). Web und Desktop rufen sie nicht.
- Die Glocken-Notiz nutzt den bestehenden Weg `notify_users` (wie `frp/startup_checks.py`), mit einem
  Entprell-Schlüssel je Hook.

## Externe Integrationen

Keine. Docker-Compose-Healthcheck: dieselbe `test`-Form wie bisher, nur ein HTTP-GET statt eines TCP-Connects.

## Trade-offs & Alternativen

- **R-1695, kurze Session statt größerem Pool:** Ein größerer Pool verschiebt den Ausfall nur. Empfehlung: Die
  Agent-Routen prüfen den Scope auf einer eigenen kurzen Session, wie `authenticate_stream_user`. Der Admin-Proxy gibt
  seine Session vor dem Forward frei, die Audit-Zeile danach nimmt eine frische Verbindung.
- **R-1697, Abgleich im Monitoring statt Wiederholung im Server:** Eine Wiederholungsschlange im Server bräuchte
  Zustand. Der 15-Minuten-Tag-Abgleich holt das Inventar ohnehin. Er räumt jede `server_id` ab, die das Monitoring
  kennt und das Inventar nicht, aber nur bei einem erfolgreich geholten, nicht leeren Inventar.
- **R-1694, Entprellung:** eine Notiz je Hook und Fehlerphase. Ein erneuter Fehlschlag desselben Hooks innerhalb der
  Entprellzeit erzeugt keine weitere.

## Risiken & Rollback

- R-1697 löscht Monitoring-Daten. Schutz: kein Abgleich bei leerem oder gescheitertem Inventar. Der Test belegt beide
  Fälle.
- R-1695 berührt `core/identity.py` und `monitoring_proxy` (Risikopfad): `security` prüft die Task.
- `/api/health` ist ohne Auth erreichbar. Sie gibt nur `{"status":"ok"}` zurück, keine Version, keine Interna. Hinter
  dem Gateway gilt die mTLS-Regel des Gateways. Die Doku nennt deshalb den Healthcheck im Container
  (`127.0.0.1:8080`).
- Rollback: `git revert` je Task.

## Doku-Impact

`docs/admin/installation.html` und `docs/en/admin/installation.html`: der Abschnitt zu `/api/health` passend zur
Route. Die Hook-Seite (DE und EN) erwähnt die Glocken-Notiz bei Fehlschlag. Changelog-Fragment für R-1694, R-1697,
R-1698 und R-1744.

## Offene Fragen

Keine. Kevin hat R-1694 und R-1744/R-1715 am 2026-11-24 entschieden.
