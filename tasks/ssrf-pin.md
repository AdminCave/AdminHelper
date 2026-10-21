<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Schutz: zur geprüften Adresse verbinden — Task-Ledger
Status: aktiv · Branch: feature/ssrf-pin · Review: pro Task
Spec: docs/features/ssrf-pin.md
Heavy: none — kein HTTP-Endpunkt, kein Schema, keine Migration, kein Gateway-, PKI-, FRP-, Compose- oder Install-Pfad; geändert werden nur die ausgehenden Anfragen von HTTP-Check, Alert-Webhook (Monitoring) und Hook-Helfern `http_get`/`http_post` (Server), und keine schwere Suite fährt diese Wege (`scripts/tests/` kennt weder HTTP-Check noch Webhook noch `http_get`); belegt wird am Verbindungsaufbau (`socket.create_connection`) und mit einem echten TLS-Handshake gegen einen lokalen Server
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: Der Guard löst je Ziel einmal auf, prüft alle Adressen und gibt sie zurück; die Anfrage verbindet zu einer
geprüften Adresse, Host-Header und TLS-Name (SNI, Zertifikatsprüfung) bleiben der Hostname. Mit einem Proxy aus der
Umgebung für das Schema der URL bleibt der Weg wie heute. Zeilenangaben: origin/main@82e4a7b8.

Für alle Tasks:
- Beide Guard-Kopien bleiben identisch: `apps/server/tests/test_ssrf_parity.py:67`, `_ALLOWED_DIVERGENCES` (`:30`)
  bleibt leer.
- Kein Test baut eine echte Verbindung nach außen auf. Eine Naht unter dem Pin ist `httpx.HTTPTransport.handle_request`
  (wie `apps/monitoring/tests/test_alerter.py:305-310`) oder `socket.create_connection` (aufzeichnen, dann `OSError`).
- Adressen, die der Guard wirklich prüft, müssen öffentlich sein: die Literale, die die Suiten schon nutzen
  (`93.184.216.34`, `93.184.216.35`, `2606:2800:220:1:248:1893:25c8:1946`). RFC-5737- und `2001:db8::`-Adressen gelten
  dem Guard als privat (`ipaddress`: `is_private`); sie taugen nur, wo die Prüfung gestubbt ist.
- Proxy-Variablen leeren, wo ein Test den direkten Weg meint (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`,
  je groß und klein, `monkeypatch.delenv(..., raising=False)`).
- Stubs bestehender Tests, die nach dem Umbau ins Leere gingen (`httpx.post`, `httpx.request`, `httpx.stream`,
  `classify_url` am Aufrufer), ziehen in derselben Task auf `check_target` bzw. eine Naht unter dem Pin um; die
  Testnamen bleiben. Ein Zähler auf eine nicht mehr gerufene Funktion ist kein Beleg.

### T1 — Guard: einmal auflösen, geprüfte Adressen zurückgeben, Client zur geprüften Adresse  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf_pin.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @41ccfed7 2026-10-21T09:57:53+02:00
Review: approve (.ah-out/review/ssrf-pin/T1.verdict.json)
Änderung: In beiden Kopien identisch (Form: Spec „Betroffene Komponenten & Dateien“). (1) `Target` (frozen dataclass: `verdict`, `host`, `addresses`) und `check_target(url) -> Target`: der heutige Rumpf von `classify_url` (monitoring `:128-166`, server `:130-168`) mit genau einem `_resolve`; bei `ALLOWED` alle Adressen ohne Dubletten in Resolver-Reihenfolge, eine IPv4-gemappte als ihre IPv4-Adresse; sonst keine Adressen. `classify_url` wird `return check_target(url).verdict` (Verhalten gleich). (2) `pinned_client(url, target, *, verify=True) -> httpx.Client`: `ValueError` ohne Adressen; meldet `urllib.request.getproxies()` einen Proxy für das Schema der URL oder `all`, `httpx.Client(verify=verify)` wie bisher; sonst ein Client mit `_PinnedTransport`: nur Anfragen an `target.host` (sonst `httpx.ConnectError` ohne Verbindung), je Adresse `url.copy_with(host=<adresse>)`, Header unverändert (Host samt Port aus der ursprünglichen URL), Extension `sni_hostname` = `url.raw_host` (ASCII), inneres `httpx.HTTPTransport(verify=verify)`, nächste Adresse nur bei `httpx.ConnectError`/`httpx.ConnectTimeout`, sonst der letzte Fehler; `close()` schließt den inneren Transport. (3) Docstring von `is_private_url` (monitoring `:174-176`, server `:176-178`): statt „does not pin“ der Verweis auf `check_target` + `pinned_client`. `test_ssrf_pin.py` (neu, SPDX `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`): genau ein `_resolve` je `check_target`; alle Adressen, ohne Dubletten, gemappte als IPv4; eine private unter öffentlichen → `PRIVATE` ohne Adressen; `UNRESOLVED` ohne Adressen; Verbindung (`socket.create_connection` aufgezeichnet) geht an `(<geprüfte Adresse>, <port>)`, auch für IPv6; erste Adresse abgewiesen → zweite; bei `httpx.ReadTimeout` kein Wechsel; Host-Header mit Nicht-Standard-Port und `sni_hostname` bei einem IDN-Host (`raw_host`); fremder Host abgelehnt ohne Verbindung; `pinned_client` mit `PRIVATE`/`UNRESOLVED` → `ValueError`; `HTTPS_PROXY` gesetzt → eine `https://`-URL geht ungepinnt (Hostname in der URL des Transports), nur `HTTP_PROXY` gesetzt → eine `https://`-URL wird gepinnt; echter TLS-Handshake: lokaler HTTPS-Server auf `127.0.0.1`, Zertifikat auf einen Namen aus einer Test-CA (`cryptography`), `Target` mit Adresse `127.0.0.1` direkt gebaut (der Guard selbst lehnte Loopback ab), Antwort 200, der Server sieht SNI und `Host` = Name, `resp.url` trägt den Namen; Gegenprobe mit einem Zertifikat auf einen anderen Namen → `httpx.ConnectError`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_pin.py tests/test_ssrf_parity.py tests/test_ssrf.py tests/test_ssrf_properties.py
Doku: keine (intern; die sichtbare Wirkung beschreiben T2–T4 je Aufrufer)

### T2 — Alert-Webhook verbindet zur geprüften Adresse  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/tests/test_alerter.py, apps/monitoring/tests/test_alerter_dispatch.py, apps/monitoring/tests/test_alert_bundle.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, CHANGELOG.md, apps/monitoring/tests/_helpers.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @fdaf237e 2026-10-21T10:13:00+02:00
Review: approve (.ah-out/review/ssrf-pin/T2.verdict.json)
Änderung: `_send_webhook` (`alerter.py:562-606`): `check_target(url)` statt `classify_url` (`:576`), Ablehnungen, Log-Zeilen und Gründe unverändert (`:577-591`); der POST (`:599`) läuft über `with pinned_client(url, target) as client: client.post(url, json=payload, timeout=10, follow_redirects=False)`. `_post_hub_event` (`:418-439`) bleibt. Zuerst der rote Test in `test_alerter.py`: `_resolve` des Guards liefert eine öffentliche Adresse, `socket.create_connection` zeichnet auf und lehnt ab; erwartet wird `(<geprüfte Adresse>, <port>)`. Umzug der Stubs: `TestWebhookSsrf` (`test_alerter.py:192-254`, alle drei), `TestWebhookLogLines` (`:286-334`, beide), `test_refused_dispatch_writes_english_error` (`test_alerter_dispatch.py:70-77`, Fall `webhook-private-target`) und `test_failed_webhook_stores_a_fixed_reason` (`:107-117`, Fehler unter dem Pin geworfen), Fixture `channels` (`test_alert_bundle.py:67-92`: Webhook-Bodies unter dem Pin aufzeichnen, Hub weiter über `httpx.post`). Doku: Kanal `webhook` (`docs/admin/monitoring.html:339`, EN `:339`), nach dem SSRF-Satz: die Anfrage geht an eine der dabei geprüften Adressen, Host-Header und TLS-Name bleiben der Hostname; mit einem Proxy aus der Umgebung für das Schema verbindet der Proxy wie bisher. `CHANGELOG.md` `[Unreleased]` → `### Changed` (umlautfrei): neuer Eintrag „SSRF-Schutz verbindet zur geprueften Adresse (Server und Monitoring)“ — der Alert-Webhook loest das Ziel einmal auf, prueft alle Adressen und verbindet zu einer davon (der Reihe nach, bis eine annimmt), Host-Header und TLS-Name bleiben der Hostname, mit `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` fuer das Schema wie bisher ueber den Proxy; Doku-Hinweis.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alerter_dispatch.py tests/test_alert_bundle.py tests/test_ssrf.py
Doku: docs/admin/monitoring.html + docs/en/admin/monitoring.html, CHANGELOG
Abhängt von: T1
Beweis: origin/main@82e4a7b8 · Probe: `_resolve` → `93.184.216.34`, `socket.create_connection` aufgezeichnet; `_send_webhook({"url": "https://<hostname>:8443/x"}, …)` verbindet zu `("<hostname>", 8443)`, nicht zu `("93.184.216.34", 8443)`; dreimal identisch
Orakel: contract — die Adresse am Verbindungsaufbau ist eine aus `check_target(url).addresses`
HEAD: 82e4a7b8

### T3 — HTTP-Check: erste Anfrage und jeder Redirect-Hop zur geprüften Adresse  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/tests/test_http_checker.py, apps/monitoring/tests/test_checker_messages.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @751af994 2026-10-21T10:24:22+02:00
Review: approve (.ah-out/review/ssrf-pin/T3.verdict.json)
Änderung: `HttpChecker.run` (`checkers/http.py:21-124`): die erste URL (`:34`, Anfrage `:50-56`) und jeder Hop (`:68`, Anfrage `:82-88`) über `check_target` und `pinned_client(url, target, verify=verify_ssl)`; Methode, Timeout, `follow_redirects=False`, Meldungen und Metriken unverändert; die Hop-URL wird wie heute aus `resp.url.join(location)` (`:67`) gebildet, `resp.url` trägt mit dem Client weiter den Hostnamen. Zuerst der rote Test in `test_http_checker.py`: `_resolve` liefert je Name eine eigene öffentliche Adresse, `socket.create_connection` bzw. eine Naht unter dem Pin zeichnet auf; erwartet werden für die erste Anfrage und für einen Hop auf einen zweiten Namen je die geprüfte Adresse, Host-Header = jeweiliger Name. Umzug der Stubs auf `httpx.HTTPTransport.handle_request` bzw. `check_target`: in `test_http_checker.py` alle Stellen auf `http_mod.httpx.request` (`:27`, `:49`, `:64`, `:88`, `:101`, `:113`, `:125`, `:137`, `:147`, `:158`, `:168`, `:197`) und `http_mod.classify_url` (`:100`); `test_http_checker_verify_ssl_off_only_for_real_false` (`:77-93`) prüft das `verify`, das am Transport ankommt; in `test_checker_messages.py` die Helfer `_http` (`:449-451`) und `_private` (`:480-482`). Doku: Zeile `http.py` der Checker-Tabelle (`docs/developer/monitoring.html:175`, EN `:175`): „folgt Redirects“ genauer — folgt Redirects selbst (höchstens 5), prüft jeden Hop und verbindet zu einer geprüften Adresse; Host-Header und TLS-Name bleiben der Hostname; mit Proxy für das Schema wie bisher. `CHANGELOG.md`: den Eintrag aus T2 um den HTTP-Check samt Redirect-Hops ergänzen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py tests/test_checker_messages.py
Doku: docs/developer/monitoring.html + docs/en/developer/monitoring.html, CHANGELOG
Abhängt von: T1, T2 (CHANGELOG-Eintrag)
Beweis: origin/main@82e4a7b8 · Probe: `_resolve` → `93.184.216.34`, `socket.create_connection` aufgezeichnet; `HttpChecker().run({"url": "http://<hostname>:8080/x"})` verbindet zu `("<hostname>", 8080)`, Ergebnis `('critical', 'Connection failed: …')`; dreimal identisch
Orakel: contract — die Adresse am Verbindungsaufbau ist eine aus `check_target(<url des Hops>).addresses`
HEAD: 82e4a7b8

### T4 — Hook-Helfer `http_get`/`http_post` verbinden zur geprüften Adresse  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_worker.py, apps/server/tests/test_hooks_http_ssrf.py, docs/developer/hooks.html, docs/en/developer/hooks.html, CHANGELOG.md
Änderung: `_safe_http_get` und `_safe_http_post` (`script_worker.py:58-96`): `check_target(url)` statt `classify_url` (`:61`, `:79`), Fehlertexte unverändert; die Anfrage über `with pinned_client(url, target) as client, client.stream(..., follow_redirects=False) as resp:` statt `httpx.stream` (`:69-71`, `:87-94`); `_read_capped_body` unverändert. Zuerst der rote Test in `test_hooks_http_ssrf.py`, für beide Helfer: `_resolve` liefert eine öffentliche Adresse, `socket.create_connection` zeichnet auf; erwartet `(<geprüfte Adresse>, <port>)`. Dazu: mit `HTTP_PROXY` gesetzt (der Runner reicht es durch, `script_runner.py:116-125`) geht `http_get` auf eine `http://`-URL wie bisher an den Proxy, ungepinnt, und die Prüfung läuft vorher. Umzug der Stubs: `test_safe_http_get_disables_redirects_and_caps_body` (`:34-61`, `follow_redirects` und Kappung unter dem Pin) und `test_unresolvable_target_is_named_as_such` (`:64-73`). Doku: Punkt `http_get`/`http_post` (`docs/developer/hooks.html:77`, EN `:77`): die Anfrage geht an eine geprüfte Adresse, Host-Header und TLS-Name bleiben der Hostname; ist ein Proxy für das Schema gesetzt, verbindet der Proxy wie bisher. Vor dem Bau `origin/main` hineinmergen und `:77` neu greppen: ein paralleles Doku-Vorhaben schreibt denselben Satz neu. `CHANGELOG.md`: den Eintrag aus T2 um die Hook-Helfer ergänzen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_http_ssrf.py tests/test_ssrf_parity.py
Doku: docs/developer/hooks.html + docs/en/developer/hooks.html, CHANGELOG
Abhängt von: T1, T2 (CHANGELOG-Eintrag)
Beweis: origin/main@82e4a7b8 · Probe: `_resolve` → `93.184.216.34`, `socket.create_connection` aufgezeichnet; `_safe_http_get("http://<hostname>:8080/x")` verbindet zu `("<hostname>", 8080)` und wirft `httpx.ConnectError`; dreimal identisch
Orakel: contract — die Adresse am Verbindungsaufbau ist eine aus `check_target(url).addresses`
HEAD: 82e4a7b8
