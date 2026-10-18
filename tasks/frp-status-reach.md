<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP-Statusansicht erreicht frps über den Supervisor — Task-Ledger
Status: aktiv · Branch: feature/frp-status-reach · Review: am Ende
Spec: Roadmap R-0408
Heavy: linux-full — frps-Image (`apps/frps`), Admin-Route `GET /api/frp/status` und der Stack-Test `integration-stack`. Der Job läuft nicht auf PRs, deshalb vor dem Merge `gh workflow run ci.yml --ref feature/frp-status-reach`. Kein `scenario`: kein Tunnel-Datenpfad, kein Cross-Host
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-18: R-0408 nach R-0411 (#205) prüfen und, falls offen, als `/feature-plan --kurz` planen. Geprüft gegen origin/main@5855a9b5: noch offen. R-0411 hat frps in ein eigenes Netz gelegt und den Statuskanal `frps-state` eingeführt (Supervisor schreibt, Server liest, `docker-compose.yml:52`/`:312`), aber `status_router.py` fragt weiter `http://frps:<dashboard_port>` und danach `http://127.0.0.1:<dashboard_port>` (`:57-63`). Der Server (`docker-compose.yml:37`) hat keinen `networks:`-Schlüssel und hängt damit nur im Netz `default`; frps hängt nur in `frpedge` (`:354`). Die Zeile nennt `docker-compose.yml:200` als Netze des Servers; das war auf `81586e98` die Zeile des Gateways. Am Befund ändert das nichts. Lösungsweg nach der Zeile: den Server nicht in `frpedge` holen, denn frps erreichte ihn dann am Gateway vorbei. Stattdessen geht der Status über den Kanal aus R-0401/R-0411: Der Supervisor fragt das Dashboard im eigenen Container über Loopback ab und legt die Antworten in `frps-state` ab, der Server liest sie dort. T3 ändert `scripts/tests/integration_stack_test.sh`, dieselbe Datei wie R-0411 T31, und wird deshalb erst nach dem Merge von R-0411 gebaut.

### T1 — Supervisor legt die Proxy-Listen des Dashboards in frps-state ab  [x]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9d6a3206 2026-10-18T07:51:32+02:00
Review: am Ende (Branch-Review)
Änderung: Der Supervisor fragt das Dashboard bei jedem Poll (`poll`, `frps-supervisor.sh:663`) ab, nach `report`, solange frps läuft (`FRPS_PID` gesetzt) und `current/frps.toml` ein `webServer.port` trägt. Er holt `http://127.0.0.1:<port>/api/proxy/<typ>` für `stcp`, `https`, `tcp` und `udp` (die Typen von `status_router.py:19`), mit `webServer.user`/`webServer.password` aus `current/frps.toml`. Jede Abfrage ist zeitbegrenzt (curl `--max-time`). Die Zugangsdaten gehen über stdin (`curl -K -`), nicht über die Kommandozeile. Jede Antwort kommt unverändert, ungeparst und höchstens 1 MiB groß in eine eigene Datei `$FRPS_STATE_DIR/proxy-<typ>.json`, über Temp-Datei und `mv` wie `write_status` (`:632`), mit 0644. Typ und Zeit legt damit der Supervisor fest (Dateiname, mtime), nicht die Antwort von frps. Scheitert eine Abfrage, ist die Antwort zu groß, läuft frps nicht oder fehlt `webServer.port`, entfällt die Datei des Typs. Tests in `test_frps_supervisor.py`, zuerst rot, mit dem Stub-frps und einem lokalen HTTP-Server als Dashboard: (a) läuft frps mit `webServer.port`, liegen nach einem Poll vier Dateien mit genau den Antworten, 0644; (b) ohne `webServer.port` und nach dem Stopp von frps liegt keine Datei; (c) eine Antwort über 1 MiB und ein Dashboard, das nicht antwortet, hinterlassen keine Datei, und der Poll-Takt bleibt (TERM beendet weiter innerhalb von `FRPS_STOP_SECONDS`); (d) kein Prozess trägt das Passwort in seiner Kommandozeile.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py
Doku: keine (intern; die sichtbare Wirkung beschreibt T2)
Beweis: origin/main@5855a9b5 · `docker compose -f docker-compose.yml --env-file /dev/null config --no-interpolate --format json`, ausgewertet je Dienst nach `networks` → dreimal identisch `server: ['default']`, `frps: ['frpedge']`, `gateway: ['default', 'pki']`, `scheduler: ['default']`. Docker-Doku (docs.docker.com/compose/how-tos/networking/): „The `proxy` service is isolated from the `db` service, because they do not share a network in common.“ `status_router.py:57-63`: ohne `FRPS_DASHBOARD_URL` nur `http://frps:<port>` und `http://127.0.0.1:<port>`, also ein Name, der im Netz `default` nicht auflöst, und der Server-Container selbst
Orakel: contract — die Doku verspricht, dass der Server das Dashboard in Compose erreicht (Semantik), die Netze lassen es nicht zu
Dedup-Key: bug:server:frp/status_router.py:frps-unreachable
HEAD: 5855a9b5
Semantik: docs/admin/frp-tunnel.html:118 — „Die Tunnel-Statusansicht fragt das frps-Dashboard ab. Standardmäßig erreicht der Server es über den Compose-Servicenamen (<code>http://frps:PORT</code>, mit <code>127.0.0.1</code>-Fallback).“ (EN `docs/en/admin/frp-tunnel.html:118`)

### T2 — `/api/frp/status` liest ohne `FRPS_DASHBOARD_URL` die Dateien des Supervisors  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/status_router.py, apps/server/app/modules/frp/proxy_status.py, apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_frp_status.py, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, CHANGELOG.md, apps/server/app/core/config.py, apps/server/tests/test_config_generator.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c96149b3 2026-10-18T08:12:40+02:00
Review: am Ende (Branch-Review)
Änderung: Neue Datei `frp/proxy_status.py` (SPDX-Header) mit einem Leser für `proxy-<typ>.json` in `FRPS_STATE_DIR`, nach dem Vorbild von `supervisor_status.py`. Er vertraut der Datei nicht: nur eine reguläre Datei ohne Symlink (`O_NOFOLLOW`), höchstens 1 MiB, UTF-8-JSON ohne doppelte Schlüssel, ein Objekt mit der Liste `proxies`. Eine mtime älter als 60 s (wie `STALE_AFTER`, `supervisor_status.py:44`) gilt als veraltet. Der Leser wirft nie. Ohne `FRPS_DASHBOARD_URL` nimmt `frps_status` (`status_router.py:41`) die Proxies aus diesen Dateien statt über HTTP. Die Kandidaten `http://frps:<port>` und `http://127.0.0.1:<port>` (`:59-63`) entfallen. Die Zuordnung zu den Tunneln und die Antwortform (`FrpStatus`) bleiben gleich. Fehlen alle Dateien oder sind sie veraltet oder ungültig, antwortet die Route wie heute bei einem unerreichbaren Dashboard: `proxies` leer, `total` 0, `error` mit englischem Text, etwa „frps dashboard: no current data from the frps supervisor“. Mit `FRPS_DASHBOARD_URL` bleibt der HTTP-Weg wie heute. Der Kommentar `config_generator.py:180-184` nennt den neuen Weg: `webServer.addr` bleibt `0.0.0.0` für `FRPS_DASHBOARD_URL`, der Supervisor fragt über Loopback. Tests in `test_frp_status.py`, zuerst rot: `test_status_without_dashboard_url_reads_the_supervisor_files` (ohne `FRPS_DASHBOARD_URL`, `FRPS_STATE_DIR` auf `tmp_path`, `proxy-stcp.json` mit einem Proxy `srv1.<tunnel>`; erwartet `total` 1, kein `error`, Tunnel zugeordnet, Secret maskiert). Auf HEAD ist der Test rot, weil die Route `http://frps:…` fragt und das `error`-Payload liefert. Dazu: veraltete, zu große, ungültige Datei und Symlink → `error`-Payload, nie 500; mit `FRPS_DASHBOARD_URL` bleiben die bestehenden HTTP-Tests (`:38`ff.) grün. Doku DE+EN (`frp-tunnel.html:118`): Woher die Statusansicht die Daten nimmt (Supervisor, alle 5 s). Für eine andere Topologie bleibt `FRPS_DASHBOARD_URL`. Es wirkt nur in der Umgebung des `server`-Dienstes (etwa `docker-compose.override.yml`); ein Eintrag in der `.env` erreicht den Server nicht, denn Compose reicht die Variable nicht durch. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_status.py
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html (`:118`) · CHANGELOG.md (Fixed)
Abhängt von: T1
Beweis: wie T1; dazu `grep -n FRPS_DASHBOARD_URL docker-compose.yml` → kein Treffer. Der Dienst `server` hat weder `env_file` noch einen `environment`-Eintrag dafür, der in der Doku genannte `.env`-Weg wirkt also nicht
Dedup-Key: bug:server:frp/status_router.py:frps-unreachable
HEAD: 5855a9b5
Semantik: docs/admin/frp-tunnel.html:118 — „Standardmäßig erreicht der Server es über den Compose-Servicenamen (<code>http://frps:PORT</code>, mit <code>127.0.0.1</code>-Fallback). Läuft frps in einer anderen Topologie (eigener Host), die Basis-URL über <code>FRPS_DASHBOARD_URL</code> in der <code>.env</code> setzen, statt den Code zu ändern.“ (EN `docs/en/admin/frp-tunnel.html:118`)

### T3 — Stack-Test: die Statusansicht liefert Daten von frps  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fdb4034a 2026-10-18T09:43:44+02:00
Review: am Ende (Branch-Review)
Änderung: In `frps_takeover` (`integration_stack_test.sh:439`) bekommt die FRP-Konfiguration (`:486`) einen `dashboard_port` mit Benutzer und Passwort. Danach wartet der Test bis zu 20 s, bis `GET /api/frp/status` kein `error` mehr trägt und `total` eine Zahl ist (`until_ok`, wie die Schritte daneben); sonst `bad` mit dem `error`-Text. Ohne T1/T2 wäre der Schritt rot mit „frps-Dashboard: nicht erreichbar (ConnectError)“, das ist der Befund im echten Stack. Die übrigen Schritte von `frps_takeover` bleiben unverändert. Erst nach dem Merge von R-0411 bauen (T31 ändert dieselbe Datei).
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (intern)
Abhängt von: T2
Dedup-Key: bug:server:frp/status_router.py:frps-unreachable
HEAD: 5855a9b5
Semantik: docs/admin/frp-tunnel.html:118 — „Die Tunnel-Statusansicht fragt das frps-Dashboard ab.“ (EN `docs/en/admin/frp-tunnel.html:118`)

### T4 — Tests: argv von curl wirklich prüfen, Frische-Grenze ohne Wettlauf  [ ]
Komponente: server · Dateien: apps/server/tests/test_frps_supervisor.py, apps/server/tests/test_frp_status.py
Änderung: Funde des tester im Branch-Review (2026-10-18). (a) `test_no_process_carries_the_password_of_the_dashboard_on_its_command_line` sucht das rohe Passwort in `/proc/*/cmdline` erst, wenn die Anfrage am Dashboard ankommt; curl hat dann `-u u:pw` schon überschrieben, und `-H "Authorization: Basic <b64>"` trüge nur das base64. Ein Rückbau von `curl --config -` auf `-u`/`-H` bliebe grün. Neu: ein `curl`-Shim im `bin_dir` der Box schreibt `"$@"` nach `$STUB_DIR` und startet das echte curl (`shutil.which`) per `exec`; der Test verlangt mindestens 4 protokollierte Aufrufe und dass kein argv das Passwort oder `base64(user:password)` enthält. Gegenprobe im Scratch: mit `-u` statt `--config -` wird der Test rot. (b) Der Fall „59 s old“ in `test_frp_status.py` altert die Datei vor `_login()`; bis `STALE_AFTER` bleibt 1 s für bcrypt und die Anfrage. Die Datei wird erst nach dem Login gealtert (oder auf 55 s), die Grenze bleibt geprüft. (c) Ein Test für den Zweig `frps-Dashboard: HTTP <status>` (z. B. 401) in `_from_dashboard`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py tests/test_frp_status.py
Doku: keine
