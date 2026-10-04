<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Kleinkram: bulk-zip nur mit nutzbaren Tunneln, Redis-Hub wartet auf sein Abo — Task-Ledger
Status: geplant · Branch: feature/server-kleinkram · Commit-Granularität: pro Task · Review: am Ende (feature-review, Sonnet) · Modell: Opus
Spec: Roadmap R-0148, R-0149
Heavy: none — T1 ändert nur, welche Dateien der Admin-ZIP enthält (kein Datenpfad eines nutzbaren Tunnels), T2 nur den Start der Redis-Subscription im Server-Prozess; pytest deckt bulk-zip ab, die Redis-Tests laufen in der PR-CI gegen ihren Redis-Service.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-04 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-10-03/04. Zeilenangaben main@cf4a9ab2.

Entscheidungen:
- C (R-0149): Fix an der Wurzel. `stream_hub.start()` kehrt erst zurück, wenn Redis das Abo bestätigt hat; der Test
  bleibt, wie er ist (Kevin).
- D (R-0148): Der ZIP lässt Server ohne nutzbaren Tunnel weg; im Extremfall enthält er nur `frps.toml`. Das ist dieselbe
  Regel wie der 404 der Einzelrouten, eine Hinweisdatei gibt es nicht (Kevin).

### T1 — bulk-zip enthält nur Konfigurationen mit nutzbaren Tunneln  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_permissions.py, CHANGELOG.md
Änderung: `gen_bulk_zip` filtert die Tunnel **einmal** oben, nach dem Laden von `all_tunnels`
(`generate_router.py:181` ff.), mit `without_secretless_stcp`; danach arbeiten alle Zweige auf dieser Liste.
- Die Schleife je Server (`:193–194`) schreibt `clients/<server>/frpc.toml` nur, wenn der Server danach noch einen
  Tunnel hat.
- `stcp_tunnels` (`:196`) entsteht aus der gefilterten Liste. Der Zweig ohne zugeordnete Nutzer (`:210`) schreibt
  `visitor.toml` nur, wenn es nutzbare stcp-Tunnel gibt.
- Der Filter je Nutzer (`:201`) entfällt, weil die Liste schon gefiltert ist.
- Damit warnt `without_secretless_stcp` (`config_generator.py:44`) im ZIP-Pfad einmal je Tunnel statt je Server, Nutzer
  und Generator-Aufruf. `generate_frpc_toml` (`config_generator.py:180`) und `generate_visitor_toml` (`:239`) filtern
  weiter selbst; die Einzelrouten bleiben unverändert.
- CHANGELOG: Eintrag unter „Fixed“; dazu die Reihenfolge der beiden FRP-Einträge (R-0129 `:197` vor R-0128 `:203`)
  nach der Roadmap-Nummer richten.

Tests (`tests/test_frp_permissions.py`, Muster `test_bulk_zip_contains_per_server_configs` `:198` und
`test_bulk_zip_writes_no_visitor_without_one` `:260`):
- Ein Server, dessen einziger Tunnel ein stcp ohne Secret ist ⇒ keine `clients/<server>/frpc.toml` im ZIP.
- Ohne zugeordnete Nutzer und nur mit stcp-Tunneln ohne Secret ⇒ keine `visitor.toml`.
- Ein Server mit einem nutzbaren und einem secretlosen Tunnel ⇒ `frpc.toml` mit genau dem nutzbaren.
- Je secretlosem Tunnel genau **eine** Warnung im Log (`caplog`).
- Vor dem Fix rot: die ersten zwei und die Warnungszählung.

Beweis: main@cf4a9ab2, Code-Lesung `apps/server/app/modules/frp/generate_router.py:181–210`. Die Schleife je Server
übergibt die ungefilterten Tunnel an `generate_frpc_toml`, das secretlose stcp-Tunnel weglässt, aber trotzdem eine
`frpc.toml` mit `auth.token` und ohne `[[proxies]]` liefert. Der Zweig `:210` übergibt `stcp_tunnels` ungefiltert an
`generate_visitor_toml`. Gefunden im Gesamt-Review von frp-secret-followups (feature/frp-secret-followups@fa08018a).
Dedup-Key: ref:server:generate_router.py:bulk-zip-secretless
HEAD: cf4a9ab2
Semantik: `docs/developer/api-reference.html:137`: „<code>404</code>, wenn der Server keinen aktiven, nutzbaren Tunnel
hat; ein STCP-Tunnel ohne Secret z&auml;hlt nicht.“ und `:138`: „ohne Tunnel gibt es kein <code>auth.token</code>.“ Der
ZIP folgt derselben Regel. `:140` beschreibt ihn als „ZIP mit <code>frps.toml</code> + <code>clients/*.toml</code> +
<code>visitors/*.toml</code>“, ohne zu sagen, welche Server ihn bekommen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_permissions.py tests/test_frp_tunnels.py
Doku: CHANGELOG (Fixed). `docs/developer/api-reference.html:140` + `docs/en/developer/api-reference.html:140`: ein
Halbsatz „nur Server bzw. Nutzer mit nutzbarem Tunnel“.

### T2 — Redis-Hub kehrt aus `start()` erst nach der Abo-Bestätigung zurück  [ ]
Komponente: server · Dateien: apps/server/app/modules/notifications/stream_hub.py, apps/server/tests/test_stream_reconnect.py, CHANGELOG.md
Änderung: `start()` (`stream_hub.py:98`) wartet nach `await pubsub.subscribe(CHANNEL)` (`:108`) auf die
Abo-Bestätigung von Redis, bevor es den Reader startet (`:109`) und „subscribed“ loggt (`:110`):
`get_message(ignore_subscribe_messages=False, timeout=…)` in einer Schleife bis `type == "subscribe"`, mit einer Frist
von 5 s insgesamt.
- Läuft die Frist ab, loggt `start()` eine Warnung und startet den Reader trotzdem; der Polling-Rückfall der Clients
  bleibt.
- Der Reconnect-Pfad im Reader (`:133`) bleibt unverändert: Dort liest der Reader die Bestätigung ohnehin als Nachricht
  und verwirft sie (`ignore_subscribe_messages=True`).

Tests (`tests/test_stream_reconnect.py`, Muster `_FakePubSub` `:26`):
- Fake-PubSub, dessen `get_message` erst nach `subscribe` die Bestätigung liefert ⇒ `start()` hat sie gelesen, bevor
  der Reader-Task existiert.
- Ohne Bestätigung innerhalb der Frist ⇒ Warnung, Reader läuft trotzdem.
- Vor dem Fix rot: der erste. `start()` liest heute keine Nachricht, die Bestätigung bleibt beim Reader.
- Die Redis-Integrationstests (`tests/test_stream_redis.py`) bleiben unverändert; in der PR-CI laufen sie gegen den
  Redis-Service (`ci.yml`, Job server).

Beweis: main@cf4a9ab2.
- redis-py 8.1.0, `redis/asyncio/client.py:1266–1276`: `PubSub.execute_command` schickt SUBSCRIBE nur ab und liest die
  Antwort nicht („don't parse the response in this function“). `start()` kehrt also zurück, bevor Redis das Abo kennt.
  Ein sofortiges `publish` über die zweite, synchrone Verbindung kann vorher ankommen und geht verloren; Pub/Sub puffert
  nicht.
- Messung der Aufsicht 2026-10-03: Wegwerf-Container `redis:7-alpine`, kein Server, kein DB-Zugriff. Die Abfolge
  `subscribe` → `publish` → `get_message` lief je 500-mal. Ohne Warten auf die Bestätigung gingen **4 von 500**
  Nachrichten verloren, mit Warten **0 von 500**.
- Das Symptom in CI: PR #69, `gh run view 37017312318 --log-failed`: `FAILED
  tests/test_stream_redis.py::test_redis_fanout_only_to_targeted_user - TimeoutError`, 1 von etwa 40 Läufen.
Dedup-Key: bug:server:test_stream_redis.py:fanout-timeout
HEAD: cf4a9ab2
Semantik: `docs/developer/server.html:189`: „publiziert der Server ein leichtes „Refresh"-Signal
(<code>stream_hub.publish()</code>) auf den Redis-Kanal <code>notif:events</code>; jeder Web-Worker hält eine
Redis-Subscription und stellt das Signal seinen lokal verbundenen Streams der betroffenen User zu.“ Ein Worker, der
„subscribed“ meldet, muss das Signal auch bekommen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_stream_reconnect.py tests/test_stream.py tests/test_stream_redis.py
Doku: CHANGELOG (Fixed: ein Worker verpasste kurz nach dem Start ein Refresh-Signal). Sonst keine (intern).
