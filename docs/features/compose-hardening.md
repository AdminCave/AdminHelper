<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Compose-Härtung: Client-Adresse hinter dem Gateway, Grenzen der Container, CA-Passphrase als Secret, Netz frpedge

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/compose-hardening.md`. Härtung, Kevin 2026-10-22.

## Problem / Motivation

1. **Der Server sieht hinter dem Gateway nur das Gateway.** Das Gateway setzt `X-Forwarded-For` auf `$remote_addr`
   (`apps/gateway/identity-headers.conf:9`, auf :8444 `apps/gateway/nginx.conf:163`). Der Server wertet den Header
   nur aus, wenn die direkte Gegenstelle in `TRUSTED_PROXIES` liegt (`apps/server/app/core/middleware.py:64-90`);
   Compose setzt `TRUSTED_PROXIES` leer (`docker-compose.yml:102`) und `TRUST_PROXY_HEADERS` auf `false` (`:99`).
   uvicorn startet ohne `--forwarded-allow-ips` (`apps/server/docker-entrypoint.sh:54-58`) und vertraut
   Forwarded-Headern damit nur von `127.0.0.1` und `::1` (uvicorn-Doku, unten). Also ist `request.client.host` für
   jede Anfrage über das Gateway dessen Adresse im Compose-Netz. Folgen im Betrieb:
   - Die Ratenlimits je Adresse gelten für alle Clients gemeinsam: Login 5 je 60 s
     (`apps/server/app/modules/users/auth_router.py:50`, `:124`), Webhook-Trigger 20 je 60 s
     (`apps/server/app/modules/hooks/router.py:43-55`), Agent-Reports 120 je 60 s
     (`apps/server/app/modules/monitoring_proxy/router.py:31-32`, `:78-81`) — ab etwa 120 Agents mit einem Report je
     Minute antwortet der Proxy für alle mit 429.
   - `ALLOWED_IPS` (`middleware.py:93-109`) prüft die Adresse des Gateways. Die Doku zeigt es mit Client-Netzen
     (`docs/admin/benutzer.html:132-134`, EN `docs/en/admin/users.html:126-128`); so gesetzt, weist der Server heute
     jede Anfrage über das Gateway ab.
   - Das Audit-Log trägt als Adresse immer das Gateway (`apps/server/app/core/auth.py:230`, `:303`, `:313`,
     `auth_router.py:136`, `:155`, `:271`).
   - `docs/admin/installation.html:160` (EN `docs/en/admin/installation.html:112`) rät, für einen vorgeschalteten
     Reverse-Proxy dessen Adresse in `TRUSTED_PROXIES` einzutragen; das wirkt nicht, weil der Server nur das Gateway
     als Gegenstelle hat.

2. **Container ohne Grenzen.** Nur frps läuft mit `no-new-privileges` (`docker-compose.yml:331-333`); kein Dienst hat
   `pids_limit` oder `mem_limit`. Das Gateway läuft mit der Default-Capability-Liste von Docker (`:178-210`, kein
   `cap_drop`), obwohl sein nginx-Master nur wenige braucht. Hook-Skripte laufen im server- bzw. scheduler-Container
   mit einem Timeout von 30 s (`apps/server/app/modules/hooks/script_runner.py:60`), höchstens acht zugleich je
   Prozess (`:69-70`), aber ohne Grenze für Prozesse und Speicher. Die certless Ebenen :8444 und :8445 haben keine
   Grenze gleichzeitiger Verbindungen je Adresse (Ratenlimits nur auf :8444 und `/ca/renew`,
   `apps/gateway/nginx.conf:65-70`, `:150`, `:159`), und alle drei Ebenen teilen sich `worker_connections 1024` je
   Worker (`:12-14`); die Timeouts für Header und Body stehen auf dem nginx-Default von 60 s.

3. **CA-Root-Passphrase dauerhaft in der Container-Umgebung.** Der ca-issuer braucht die Passphrase nur, wenn er die
   Hierarchie beim ersten Start erzeugt (`apps/ca-issuer/app/storage.py:85-131`, Prüfung `:116-119`). Compose reicht
   sie als Umgebungsvariable durch (`docker-compose.yml:233`); damit steht sie im `Config.Env` des Containers. Der Code
   liest bevorzugt `CA_ROOT_PASSPHRASE_FILE` (`apps/ca-issuer/app/config.py:43-54`), und die Doku empfiehlt es
   (`docs/admin/installation.html:142`, EN `:53`), aber Compose verdrahtet es nicht. Leert der Betreiber den Wert
   nach dem ersten Start, erzeugt `scripts/init-secrets.sh` (`:103-111`) beim nächsten Update eine neue Passphrase
   (`scripts/update.sh:563` ruft es in `migrate_env` auf), die nicht zum vorhandenen Root-Key passt.

4. **Netz `frpedge` mit ausgehendem Verkehr.** frps sitzt allein im Netz `frpedge` (`docker-compose.yml:356`,
   `:453-456`), einem Bridge-Netz mit IP-Masquerading (Docker-Default). frps nimmt nur Verbindungen an; Einträge, die
   frps ausgehend nutzen würden (Server-Plugins), lässt der Supervisor nicht zu: auf oberster Ebene nur die Schlüssel
   aus `TOP_KEYS` (`apps/frps/frps-supervisor.sh:119-122`), als Tabelle nur `[transport.tls]`, jede andere Zeile gilt als Fehler (`:212-221`).

5. **Doku der Netze.** `docs/developer/index.html:106` (EN `docs/en/developer/index.html:84`) und der Kommentar
   `apps/ca-issuer/app/config.py:93-101` sagen, nur das Gateway erreiche den ca-issuer; ebenso der Kommentar
   `docker-compose.yml:214-216`. Im Netz `pki` hängt auch Postgres (`:35`); der Kommentar `:266-268` sagt es richtig.

## Ziel & Nicht-Ziele

Ziel:
- Hinter dem mitgelieferten Gateway wertet der Server die Client-Adresse aus, die das Gateway übermittelt: die
  Ratenlimits je Adresse, `ALLOWED_IPS` und die Adresse im Audit-Log beziehen sich auf den Client. Forwarded-Header
  von anderen Gegenstellen bleiben unbeachtet (T11–T13, offene Fragen 1 und 2).
- Jeder Dienst läuft mit `no-new-privileges` und einer Prozessgrenze (`pids_limit`); Speichergrenzen nach offener
  Frage 3 (T10).
- Das Gateway behält von den Capabilities nur, was sein nginx-Master braucht; Port 443 im Container ohne
  `NET_BIND_SERVICE` wie bei frps.
- Die certless Ebenen :8444 und :8445 begrenzen gleichzeitige Anfragen je Adresse und je Ebene und schließen
  untätige Verbindungen früher; :443 bleibt, wie es ist.
- Die CA-Root-Passphrase erreicht den ca-issuer als Datei (Compose-Secret), nicht als Umgebungsvariable; nach dem
  ersten Start darf der Wert in `.env` leer sein, ohne dass ein Update eine neue Passphrase erzeugt.
- frps hat aus `frpedge` keinen ausgehenden Verkehr über den Host hinaus (kein Masquerading); veröffentlichte Ports
  bleiben erreichbar.
- Die Doku beschreibt die Netze, wie Compose sie anlegt.

Nicht-Ziele (YAGNI):
- Getrennte Datenbankrollen je Dienst: eigenes Vorhaben, weil es bestehende Installationen migriert (Rollen,
  Eigentümer, Passwörter, Backup/Restore) und `scripts/install.sh`/`scripts/update.sh` berührt.
- Kein `cap_drop` für server, scheduler, ca-issuer und monitoring (deren Entrypoints wechseln per `gosu` den Nutzer;
  gehört zu den Images), kein `read_only`-Root-Dateisystem, keine `ulimits`.
- Keine Auswertung von Forwarded-Headern eines vorgeschalteten Proxys im Gateway (`real_ip`); die Doku sagt, was der
  Server dann sieht.
- uvicorn bleibt beim Default für Forwarded-Header; die Auswertung bleibt an einer Stelle, `resolve_client_ip`.
- Keine Änderung an `scripts/install.sh`, `scripts/update.sh`, `scripts/backup.sh` (offene Frage 2 nennt die
  Variante mit `update.sh`).
- `worker_connections` bleibt 1024; die Grenzen je Ebene halten die certless Ebenen darunter.
- Kein IPv6 für `frpedge` (heute nicht aktiviert).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `docker-compose.yml`, `apps/server/tests/test_compose_hardening.py` (neu), `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T2 | server | `docker-compose.yml`, `apps/server/tests/test_gateway_container.py` (neu), `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T3 | server | `apps/gateway/nginx.conf`, `apps/server/tests/test_gateway_container.py`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T4 | server | `docker-compose.yml`, `apps/server/tests/test_compose_hardening.py`, `docs/developer/index.html`, `docs/en/developer/index.html`, `CHANGELOG.md` |
| T5 | ca-issuer | `apps/ca-issuer/app/config.py` (samt Kommentar `:93-101`), `apps/ca-issuer/tests/test_config.py` |
| T6 | server | `docker-compose.yml`, `.env.example`, `apps/server/tests/test_compose_hardening.py`, `apps/server/tests/test_env_parity.py`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `CHANGELOG.md` |
| T7 | scripts | `scripts/init-secrets.sh`, `scripts/tests/init-secrets_test.sh`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T8 | scripts | `scripts/tests/integration_stack_test.sh` |
| T9 | scripts | `scripts/tests/multibox.sh`, `scripts/tests/box_serverbox.sh` |
| T10 | server | `docker-compose.yml`, `apps/server/tests/test_compose_hardening.py`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |
| T11 | server | `apps/server/app/core/middleware.py`, `apps/server/tests/test_ip_filter.py`, `docs/developer/server.html`, `docs/en/developer/server.html` |
| T12 | server | `docker-compose.yml`, `.env.example`, `apps/server/tests/test_compose_hardening.py`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `docs/admin/benutzer.html`, `docs/en/admin/users.html`, `CHANGELOG.md` |
| T13 | scripts | `scripts/tests/integration_stack_test.sh` |

Risikopfade (`scripts/dev/review-risk.txt`): `docker-compose*.yml` (T1, T2, T4, T6, T10, T12), `apps/gateway/*` (T3),
`apps/ca-issuer/*` (T5): diese Tasks bekommen zusätzlich `security`. `apps/server/app/core/middleware.py` (T11)
steht nicht auf der Liste; die Session holt `security` dort trotzdem (Vertrauensentscheidung über Forwarded-Header).

In `docker-compose.yml` ändern sich: je Dienst neue Schlüssel nach der Zeile `restart: unless-stopped` (T1, T10), beim
gateway `cap_drop`/`cap_add`/`sysctls` (T2), bei monitoring `sysctls` (T1), beim ca-issuer die Zeile `:233` samt
Kommentar `:231-232` und ein `secrets:`-Eintrag (T6), ein neuer Top-Level-Block `secrets:` (T6), beim server die Zeilen
`:97-102` (T12), unter `networks:` der Eintrag `frpedge` (`:453-456`, T4) und die Kommentare `:214-216` und `:445-448`
(T4). Die `environment:`-Blöcke bleiben sonst unberührt.

## Datenmodell / API / Migrationen

Keine Alembic-Migration, keine Route, kein Schema; OpenAPI bleibt unverändert. Kein Vertrags-Drift zu Web, Desktop
oder Agent. `.env`-Schlüssel bleiben dieselben: `CA_ROOT_PASSPHRASE` bleibt der Ort der Passphrase (T6 ändert nur, wie
Compose sie übergibt), `TRUSTED_PROXIES` bleibt der Knopf für zusätzliche Proxys (T12 stellt das Gateway davor).
`TRUSTED_PROXIES` versteht nach T11 neben Adressen und Netzen auch Hostnamen (additiv). Bestehende Installationen
übernehmen die Änderungen mit dem nächsten `update.sh` (neue `docker-compose.yml` aus dem Release-Bundle); das Netz
`frpedge` legt Compose dabei neu an (T4, Probe unten). Wer `ALLOWED_IPS` gesetzt hat, ist von T12 betroffen (offene
Frage 2).

## Externe Integrationen

- Docker Compose, Services-Referenz (https://docs.docker.com/reference/compose-file/services/, gelesen 2026-10-22):
  `security_opt` „For boolean options such as `no-new-privileges`, the value may be omitted entirely“; `pids_limit`
  „tunes a container's PIDs limit. Set to -1 for unlimited PIDs.“; `cap_drop`/`cap_add`; `sysctls` „You can only use
  sysctls that are namespaced in the kernel.“; `mem_limit` „must be consistent with the `limits.memory` attribute in
  the Deploy Specification“.
- Docker Compose, Secrets (https://docs.docker.com/reference/compose-file/secrets/): `environment` — „The secret is
  created with the value of an environment variable on the host. This is only supported by Docker Compose.“ Laut
  compose-spec `09-secrets.md` seit Compose v2.6.0. Probe (Docker 29.8.1, Compose v5.5.1): der Wert kommt auch aus der
  `.env` des Projekts, liegt im Container als `/run/secrets/<name>` (0444, root), `Config.Env` enthält nur
  `CA_ROOT_PASSPHRASE_FILE`; ist die Variable leer, gibt es die Datei nicht; fehlt sie ganz, bricht `docker compose up`
  ab („environment variable "CA_ROOT_PASSPHRASE" required by secret … is not set“).
- Docker Bridge-Treiber (https://docs.docker.com/engine/network/drivers/bridge/): `com.docker.network.bridge.enable_ip_masquerade`,
  Default `true`, „Enable IP masquerading.“; Port-Publishing
  (https://docs.docker.com/engine/network/port-publishing/): Masquerading „can be disabled for a user-defined bridge
  network“. Probe (Docker 29.8.1, Compose v5.5.1, ein Alpine-Container): mit `false` scheitern Verbindungen ins Internet
  und zum LAN-Router, ein veröffentlichter Port bleibt vom Host aus erreichbar, Dienste des Hosts selbst bleiben
  erreichbar; Compose legt das Netz beim nächsten `up` mit der geänderten Option neu an. Erreichbarkeit des
  veröffentlichten Ports von einem zweiten Host: nicht verifiziert (belegt der `scenario`-Lauf, T9).
- Docker-Defaults im Container (Probe Docker 29.8.1): `net.ipv4.ping_group_range` = `0 2147483647`,
  `net.ipv4.ip_unprivileged_port_start` = `0`.
- uvicorn Settings (https://uvicorn.dev/settings/): `--proxy-headers` „Defaults to enabled, but is restricted to only
  trusting connecting IPs in the `forwarded-allow-ips` configuration.“; `--forwarded-allow-ips` „Comma separated list
  of IP Addresses, IP Networks, or literals (e.g. UNIX Socket path) … Defaults to `$FORWARDED_ALLOW_IPS` if set.
  Otherwise, `127.0.0.1` and `::1` are trusted.“ Hostnamen nennt die Doku nicht.
- nginx `ngx_http_limit_conn_module` (https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html): „A connection
  is counted only if it has a request being processed by the server and the whole request header has already been
  read.“; `limit_conn_status` Default 503; „If the zone storage is exhausted, the server will return the error to all
  further requests.“ `ngx_http_core_module`: `client_header_timeout`/`client_body_timeout`/`send_timeout` Default 60s,
  `keepalive_timeout` 75s.
- Compose-Interpolation `${VAR:+…}` mit verschachteltem `${VAR}`: Probe (Compose v5.5.1) — ungesetzt und leer ergeben
  `gateway`, gesetzt `gateway,<wert>`.

## Trade-offs & Alternativen

1. **Wie der Server dem Gateway vertraut (T11, T12; offene Frage 1).** (C) `TRUSTED_PROXIES` versteht Hostnamen; Compose
   setzt `gateway` davor, der Server löst den Namen über das Docker-DNS auf und hält die Adressen mit kurzer
   Lebensdauer im Speicher — **Empfehlung**: keine Netzänderung, keine feste Adresse, kein Konflikt mit Netzen des
   Hosts, Bestand übernimmt es ohne Zutun; Vertrauen genau für die Container des Dienstes `gateway`. Kosten: ein
   Resolver mit Cache im Server, ein Zeitfenster bis zur nächsten Auflösung nach einem Neustart des Gateways (dann
   gilt wie heute die Gateway-Adresse). (A) Eigenes Netz zwischen Gateway und Server mit festem Subnetz und fester
   Gateway-Adresse, `TRUSTED_PROXIES` (oder uvicorns `--forwarded-allow-ips`) auf diese Adresse: deklarativ, aber ein
   fest gewähltes Subnetz kann mit Netzen auf dem Host kollidieren (dann scheitert `docker compose up`), braucht
   Knöpfe für Subnetz und Adresse, und das Gateway muss das Default-Netz verlassen, damit `server` eindeutig auflöst.
   (B) Das ganze Compose-Netz vertrauen: auch monitoring, scheduler, redis, postgres und victoria dürften dann
   `X-Forwarded-For` setzen.
2. **Eine Stelle für Forwarded-Header.** uvicorn bleibt beim Default (vertraut 127.0.0.1/::1); `resolve_client_ip`
   bleibt die einzige Auswertung. Zwei Ebenen (uvicorn und App) müssten gleich konfiguriert werden, und uvicorn kennt
   keine Hostnamen.
3. **Passphrase als Compose-Secret aus der Umgebung (T6)** statt aus einer Datei auf dem Host: Eine `file:`-Quelle
   bräuchte eine zusätzliche Datei mit passenden Rechten für die UID von `app` und ein Skript, das sie anlegt; die
   `environment:`-Quelle liest denselben `.env`-Schlüssel wie heute. Folge: fehlt die Zeile `CA_ROOT_PASSPHRASE` in
   `.env` ganz, bricht `docker compose up` ab; leer ist erlaubt. `.env.example` trägt die Zeile aktiv, `update.sh`
   ergänzt fehlende aktive Zeilen (`migrate_env`), `install.sh` kopiert `.env.example`. Die Doku sagt: Wert leeren,
   Zeile behalten.
4. **Wann `init-secrets.sh` die Passphrase erzeugt (T7).** Nur im selben Lauf, in dem es auch `POSTGRES_PASSWORD`
   erzeugt (frische Installation: beide Volumes entstehen neu) — **Empfehlung**: ohne Docker-Abfrage, gilt für
   `install.sh`, `update.sh` und den Aufruf von Hand gleich. Alternative: das Volume `ca-pki` über Docker abfragen —
   braucht den Projektnamen und einen laufenden Docker-Daemon im Skript. Folge der Empfehlung: wer `POSTGRES_PASSWORD`
   vor dem ersten Lauf von Hand setzt, bekommt keine Passphrase erzeugt; der ca-issuer bricht dann beim ersten Start
   mit „CA_ROOT_PASSPHRASE muss gesetzt sein …“ ab (`storage.py:116-119`), das Skript nennt den Fall in einer Zeile.
5. **Werte der Prozessgrenzen (T1).** Großzügig nach der Struktur der Dienste, nicht gemessen: server 4096 (je
   uvicorn-Worker ein Thread-Pool von 40, bis acht Hook-Prozesse, `WEB_CONCURRENCY` nach der Faustregel
   2×Kerne+1, `.env.example:144-149`), scheduler und monitoring 1024 (Thread-Pools, Hooks bzw. `ping`-Prozesse,
   `apps/monitoring/app/scheduler.py:39`), victoria 1024, ca-issuer, gateway (ein Worker je Kern), frps und postgres
   (Default `max_connections` 100) je 512, redis 256. Höher setzt sie, wer will, per `docker-compose.override.yml`
   (Compose lädt sie selbst, `update.sh` tauscht nur die Dateien des Bundles, `scripts/update.sh:513-535`).
6. **Capabilities des Gateways (T2).** Start mit `cap_drop: [ALL]` und `CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE`;
   `KILL` nur, wenn der Test ohne es einen unsauberen Stopp zeigt. `DAC_OVERRIDE` statt `DAC_READ_SEARCH`, weil
   `gateway.key` 0600 unter der UID des ca-issuer liegt (`apps/ca-issuer/app/storage.py:67-77`, `:224`) und
   `DAC_READ_SEARCH` zusätzlich `open_by_handle_at` erlaubt (nicht in Dockers Default-Liste). Jede Capability der Liste
   hat im Test eine Gegenprobe ohne sie.
7. **Grenzen der certless Ebenen (T3).** `limit_conn` je Adresse (:8444 16, :8445 64) und je Ebene (:8444 128, :8445
   256), `limit_conn_status 429`, `client_header_timeout`/`client_body_timeout` 10 s, `keepalive_timeout` 15 s auf
   beiden Ebenen. 64 je Adresse auf :8445, weil viele Agent-Hosts hinter einer NAT-Adresse zugleich Pakete holen können.
   Die Grenzen je Ebene halten :8444 (zwei Verbindungen je Anfrage) und :8445 zusammen unter der Hälfte von
   `worker_connections` eines einzelnen Workers. Untätige Verbindungen zählt `limit_conn` nicht; die kürzeren Timeouts
   begrenzen sie.
8. **Ausgehender Verkehr von frps (T4).** Masquerading aus — **Empfehlung**: eine Option am Netz, Docker-Mittel, kein
   Eingriff in die Firewall des Hosts. Alternativen: Regeln in `DOCKER-USER` über `install.sh` (Host-Firewall,
   iptables/nftables-Varianten); `gateway_mode_ipv4=isolated` setzt ein `internal`-Netz voraus, auf dem Docker keine
   Ports veröffentlicht.

## Risiken & Rollback

- T12 ändert, was `ALLOWED_IPS` prüft. Eine Installation, die `ALLOWED_IPS` nur mit dem Docker-Netz des Gateways
  betreibt, weist nach dem Update externe Clients mit 403 ab (offene Frage 2).
- T1/T10: zu knappe Grenzen zeigen sich als Fehler beim Prozessstart (`fork`) bzw. als OOM-Kill eines Dienstes. Die
  Werte sind großzügig; `docker-compose.override.yml` hebt sie an.
- T2: fehlt dem Gateway eine Capability, startet nginx nicht; der Container-Test (T2) und der Stack-Lauf zeigen es vor
  dem Merge.
- T4: Compose legt `frpedge` beim Update neu an (Probe Compose v5.5.1). Ob ältere Compose-Versionen das Netz bei
  geänderter Option ebenso neu anlegen, ist nicht verifiziert; der Stack-Check (T8) liest die Option am laufenden Netz.
- T6: fehlt die Zeile `CA_ROOT_PASSPHRASE` in `.env` ganz, startet der Stack nicht (Meldung von Compose nennt die
  Variable). `.env.restored` aus einem Backup trägt die Zeile nicht (`scripts/backup.sh:100`); die Restore-Doku sagt
  schon, sie zu ergänzen.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung. `update.sh` rollt eine gescheiterte Aktualisierung
  samt `docker-compose.yml` zurück (`scripts/update.sh:588-618`).

## Doku-Impact

T1: neuer Abschnitt „Grenzen der Container“ in `docs/admin/betrieb.html` nach „Multi-Worker-Betrieb“ (`:155`), EN
`docs/en/admin/operations.html` nach „Multi-Worker Notes“ (`:108`); T2, T3 und T10 ergänzen ihn. T4: Netze in
`docs/developer/index.html:106` und EN `:84`. T6: Zeile `CA_ROOT_PASSPHRASE` in `docs/admin/installation.html:142`, EN
`:53`. T7: Callout und Restore-Absatz in `docs/admin/betrieb.html:95`, `:103`, EN `docs/en/admin/operations.html:62`,
`:70`. T11: `docs/developer/server.html:45`, EN `:45`. T12: `docs/admin/installation.html:146-148`, `:160`, EN
`:57-59`, `:112`, `docs/admin/benutzer.html:132`, EN `docs/en/admin/users.html:126`. CHANGELOG (Changed) für T1–T4,
T6, T7, T10, T12.

## Offene Fragen

1. **Wie vertraut der Server dem Gateway (T11, T12, T13)?** Empfehlung (C): `TRUSTED_PROXIES` versteht Hostnamen,
   Compose setzt `gateway` davor. Alternative (A): eigenes Netz mit festem Subnetz und fester Adresse des Gateways.
   Begründung und Kosten: Trade-off 1. Bei (A) entfällt T11, und T12 wird neu geschnitten.
2. **Bestand mit `ALLOWED_IPS` (T12).** Empfehlung: Hinweis im CHANGELOG und in der Doku, dass `ALLOWED_IPS` danach die
   Client-Netze enthalten muss; keine Skriptänderung. Alternative: `update.sh` warnt, wenn `ALLOWED_IPS` gesetzt ist —
   ändert `scripts/update.sh` (Merge durch Kevin) und überschneidet sich mit einem parallelen Vorhaben an den
   Betriebsskripten.
3. **Speichergrenzen (T10).** Empfehlung: `mem_limit` für alle Dienste mit großzügigen festen Werten, höher per
   `docker-compose.override.yml`. Alternativen: nur für die Dienste mit fester Last (gateway, frps, ca-issuer, redis)
   und für die übrigen nur dokumentiert; oder `.env`-Knöpfe je Dienst. Die Werte setzt die Session nach einer Messung
   im Stack-Lauf (`docker stats`) vor dem Bau ein.
4. **`scenario` vor dem Merge** (T4, T9, T2/T3 unter `--enforce`, T12/T13 mit echten Clients von einem zweiten Host):
   `--agents 1 --tunnel --enforce` — ask-first.
