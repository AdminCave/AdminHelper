# Laufzeit: Redis-Netz und -Module, Proxy-Header des Servers (kern-laufzeit-3)

Roadmap: R-1139, R-1125 (Kevin 2026-11-09 Triage, vor 0.47.0).

## Problem / Motivation
- **R-1139:** `redis` (`docker-compose.yml:405`) hängt im Default-Netz, das alle Dienste außer `ca-issuer` und
  `frps` teilen; es braucht ihn nur `server` und `scheduler` (`REDIS_URL`, `:149`, `:216`). Der Entrypoint des
  gepinnten Images lädt zudem alle Module aus `/usr/local/lib/redis/modules/` (search, json, timeseries, bloom),
  die AdminHelper nicht nutzt. Härtung: Redis nur für seine Nutzer erreichbar, keine ungenutzten Module.
- **R-1125:** `apps/server/docker-entrypoint.sh:59` startet uvicorn ohne Proxy-Optionen; uvicorn schreibt damit
  Client-Adresse und Schema aus `X-Forwarded-*` für die Gegenstellen aus `FORWARDED_ALLOW_IPS` um (Standard
  `127.0.0.1` und `::1`, aus der Umgebung überschreibbar). Die Client-Adresse leitet der Server selbst über
  `TRUSTED_PROXIES` ab (`app/core/middleware.py:215`), die Gateway-Prüfung über den direkten Peer
  (`app/core/identity.py:133`): ein zweiter, impliziter Vertrauensweg ohne Nutzen.

## Ziel & Nicht-Ziele
Ziel: Redis in einem eigenen internen Netz nur mit `server` und `scheduler`, ohne die ladbaren Module; uvicorn
wertet keine Proxy-Header aus (`--no-proxy-headers`), es bleibt allein der Weg über `TRUSTED_PROXIES`.
Nicht-Ziele: kein Redis-Passwort und keine ACL (neues Secret in `.env`, `install.sh`/`update.sh`), keine Änderung am
Refresh-Cookie (R-1274, eigene Zeile), keine Änderung an `TRUSTED_PROXIES`.

## Betroffene Komponenten & Dateien
- `docker-compose.yml`: Netz `redis` (`internal: true`); `redis` nur dort, `server` und `scheduler` in `default` und
  `redis`; `redis` startet `redis-server` direkt (`entrypoint`, `user: redis`), ohne den Image-Entrypoint, der die
  Module lädt; Kommentar der Netze (`:641`).
- `docker-compose.test.yml`: der Loopback-Port von `redis` braucht ein nicht-internes Netz; die Test-Compose nimmt
  `internal` für `redis` zurück (nur Testbetrieb, Port weiter nur `127.0.0.1`).
- `scripts/tests/integration_stack_test.sh`: der Platzhalter für die Gateway-Adresse (`:223`) wird ein One-off von
  `victoria` (allein im Default-Netz); Schritt 11 (`:392`) behält Redis als Positiv-Kontrolle des Servers; neu: ein
  Dienst des Default-Netzes erreicht `redis:6379` nicht, Redis meldet keine ladbaren Module.
- `apps/server/tests/test_compose_hardening.py`: Netz `redis` intern, Mitglieder genau `redis`, `server`,
  `scheduler`; `redis` ohne den Image-Entrypoint.
- `apps/server/docker-entrypoint.sh`: `--no-proxy-headers`; `apps/server/app/core/identity.py` (Docstring
  `_peer_is_gateway`); Test `apps/server/tests/test_server_entrypoint.py` (neu, SPDX).
- Doku: `docs/developer/index.html`, `docs/en/developer/index.html` (Netze), `changelog.d/kern-laufzeit-3.md`.

## Datenmodell / API / Migrationen
Keine. Ein bestehender Stack bekommt das Netz beim nächsten `docker compose up -d` (update.sh), `redis`, `server`
und `scheduler` werden neu angelegt; Redis hält nichts Persistentes.

## Externe Integrationen
- Docker-Image `redis:8-alpine`: Entrypoint lädt die Module nur, wenn er `redis-server` startet; `vectorset` ist in
  `redis-server` eingebaut und bleibt (lokal geprüft: `MODULE LIST` ohne Image-Entrypoint nur `vectorset`).
- uvicorn Settings (https://uvicorn.dev/settings/): `--proxy-headers` Standard an, `--forwarded-allow-ips` aus
  `FORWARDED_ALLOW_IPS`, sonst `127.0.0.1` und `::1`; `--no-proxy-headers` schaltet die Auswertung ab.

## Trade-offs & Alternativen
- **Eigenes Netz statt `requirepass`/ACL:** gleiche Wirkung gegen die übrigen Dienste, ohne neues Secret und ohne
  Änderung an Install und Update. Empfehlung: Netz.
- **`--no-proxy-headers` statt `--forwarded-allow-ips 127.0.0.1`:** im Container spricht nichts über Loopback mit
  Proxy-Headern; ein ausdrücklicher Wert ließe den zweiten Weg bestehen. Folge: `request.url.scheme` bleibt `http`
  wie heute (die Gateway-Peers waren nie in `FORWARDED_ALLOW_IPS`).
- **Platzhalter `victoria`:** Image gepullt, nicht gebaut, allein im Default-Netz, hat `sleep`.

## Risiken & Rollback
Ein eigener Dienst des Betreibers (Override), der Redis über das Default-Netz nutzt, verliert die Verbindung; er
muss ins Netz `redis`. Wer `FORWARDED_ALLOW_IPS` gesetzt hat, verliert dessen Wirkung (undokumentiert).
Rollback: Revert, `docker compose up -d`.

## Doku-Impact
`docs/developer/index.html` DE+EN: Redis im eigenen Netz mit Server und Scheduler. CHANGELOG über
`changelog.d/kern-laufzeit-3.md`.

## Offene Fragen
Keine.
