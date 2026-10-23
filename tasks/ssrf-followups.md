<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Guard: direkter Weg neben einem Proxy, unlesbare URLs, Kommentar- und Test-Nachzug — Task-Ledger
Status: erledigt · Branch: feature/ssrf-followups · Review: pro Task
Spec: docs/features/ssrf-followups.md (Roadmap R-0606, R-0599; T1 und T2 gehören zum Paket, Kevin 2026-10-22)
Heavy: none — keine Route, kein Schema, keine Migration, kein Gateway-, PKI-, FRP-, Compose- oder Install-Pfad; geändert werden die Proxy-Weiche von `pinned_client` und der Fang in `check_target` in beiden Guard-Kopien, zwei Kommentare und Tests; die Aufrufer (HTTP-Check, Alert-Webhook, Hook-Helfer) bleiben, und keine schwere Suite setzt einen Proxy oder fährt diese Wege (`scripts/tests/`, Compose und Workflows nennen keine Proxy-Variable; wie bei ssrf-pin und ssrf-idna)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Neben einem Proxy aus der Umgebung geht, was httpx direkt verbinden würde (ein Ziel unter `NO_PROXY`), über
den Pin an eine geprüfte Adresse; welche Anfrage über den Proxy geht, bleibt gleich. (2) Eine URL mit einem einzelnen
Surrogat ist eine unlesbare URL (`Target(PRIVATE)`), kein Wurf. (3) Kommentare und Docstrings sagen, was gilt. (4) Die
Tests aus R-0599 und R-0606 sind da. Zeilenangaben: origin/main@53a7dbc5; der builder greppt sie vor dem Schreiben
neu.

Für alle Tasks:
- Reihenfolge: T1, dann T3 (beide `server`, dieselben Dateien). T2, T4 und T5 (`monitoring`) erst, wenn PR #265
  (`feature/monitoring-io`) auf `main` ist und `origin/main` in den Branch gemergt ist: #265 baut die Redirect-Schleife
  in `apps/monitoring/app/checkers/http.py` um und ändert `alerter.py`, `test_http_checker.py`, `test_alerter.py`.
  Diese Tasks nennen Code-Stellen nach Inhalt. T2 hängt an T1, T4 an T3, T5 nach T4 (gleiche Testdatei).
- Beide Guard-Kopien (`apps/server/app/core/ssrf.py`, `apps/monitoring/app/core/ssrf.py`) ändern sich im selben Commit
  und bleiben gleich: `apps/server/tests/test_ssrf_parity.py` vergleicht den AST ohne Docstrings und Kommentare,
  `_ALLOWED_DIVERGENCES` (`:30`) bleibt leer; Kommentare und Docstrings trotzdem gleich halten.
- Risikoliste (`scripts/dev/review-risk.txt:32-37`): beide `ssrf.py` und `alerter.py`. T1, T3 und T4 bekommen
  zusätzlich `security`.
- Platzhalter: Hosts unter `.example`, Proxy `http://192.0.2.10:3128` (RFC 5737) wie `_PROXY` in
  `apps/server/tests/test_ssrf_pin.py:37`; eine Adresse, die der Guard als öffentlich prüft, ist `93.184.216.34`
  (`_V4`, `:34`). Tests, die eine Proxy-Variable setzen, löschen vorher alle (die autouse-Fixtures
  `test_ssrf_pin.py:44-50` und `no_env_proxy`, `apps/monitoring/tests/_helpers.py:256-262`).
- Neue Code-Strings und Kommentare englisch.

### T1 — Proxy-Umgebung: was httpx direkt verbindet, geht über den Pin (gehört zum Paket)  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf_pin.py, docs/developer/hooks.html, docs/en/developer/hooks.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0c4ad7b7 2026-10-23T06:47:03+02:00
Review: approve (.ah-out/review/ssrf-followups/T1.verdict.json)
Änderung: In beiden Kopien `pinned_client` (`ssrf.py:277-305`, Monitoring `:275-303`). (1) Import `from urllib.request import getproxies` (`:26`, Monitoring `:23`) → `from httpx._utils import get_environment_proxies`; ein Kommentar sagt das Warum: die Tabelle, aus der httpx selbst seine Proxy-Mounts baut, `NO_PROXY` eingeschlossen; privat, die Tests dieser Task melden eine Änderung nach einem httpx-Upgrade. `urlparse` bleibt (`check_target`, `:166`). (2) Ablauf nach der Prüfung auf Adressen (`:289-290` bleibt): `parsed = httpx.URL(url)`; `proxies = get_environment_proxies()`; `mounts = {}`; nur wenn `proxies.get(f"{parsed.scheme}://") or proxies.get("all://")`, dann `mounts = {pattern: None if proxy is None else httpx.HTTPTransport(verify=verify, proxy=proxy) for pattern, proxy in proxies.items()}`; zurück kommt immer `httpx.Client(transport=_PinnedTransport(parsed.raw_host.lower(), target.addresses, verify=verify), mounts=mounts)`. Der Zweig mit `return httpx.Client(verify=verify)` (`:291-299`) entfällt. Sein Kommentar wird: über einen Proxy-Mount verbindet der Proxy wie bisher (durch einen CONNECT-Tunnel nimmt httpcore den TLS-Namen vom Ziel-Host, nicht von `sni_hostname`, eine gepinnte Adresse würde gegen das Zertifikat geprüft); ein `None`-Mount (`NO_PROXY`) und jede URL ohne passenden Proxy fallen auf den Transport des Clients, den Pin (`httpx/_client.py:760-769`); ohne Proxy für das Schema wird `NO_PROXY` nicht gelesen, wie bisher. Der Kommentar zu `raw_host` (`:300-303`) bleibt. (3) Docstring (`:280-288`): der Satz „Without a proxy `url` is parsed here … httpx.InvalidURL can come from this call already“ (`:285-287`, Monitoring `:283-285`) entfällt (R-0606: `check_target` hat die URL schon mit httpx gelesen); neu: mit einem Proxy aus der Umgebung für das Schema geht, was httpx über den Proxy schickt, wie bisher über ihn, ungepinnt, alles andere über den Pin. Tests in `test_ssrf_pin.py`, Abschnitt Proxy (`:399-436`), mit `_resolving_to` (`:62-71`), `_connections` (`:74-86`), `_below_the_pin` (`:89-98`): (a) parametrisiert, Verbindung genau `[(_V4, port)]`: `HTTP_PROXY` + `NO_PROXY=*` + `http://pinned.example/x`; `HTTP_PROXY` + `NO_PROXY=pinned.example`; `HTTP_PROXY` + `NO_PROXY=.example`; `HTTP_PROXY` + `NO_PROXY=PINNED.EXAMPLE`; `HTTPS_PROXY` + `no_proxy="other.example, *"` + `https://pinned.example/x`; `https_proxy` + `NO_PROXY=https://pinned.example` + `https://pinned.example/x`; `ALL_PROXY` + `NO_PROXY=pinned.example:8443` + `https://pinned.example:8443/x`. (b) Gegenstücke, Verbindung genau `[("192.0.2.10", 3128)]`: `NO_PROXY=other.example`; `NO_PROXY=pinned.example:8080` bei `http://pinned.example/x`; `NO_PROXY=https://pinned.example` bei `HTTP_PROXY` und `http://pinned.example/x`; `NO_PROXY=.pinned.example` bei `http://pinned.example/x` (nur Subdomains). (c) Differential: Proxy-Umgebung (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `HTTP_PROXY`+`HTTPS_PROXY`) × `NO_PROXY` (ohne, `*`, `pinned.example`, `.example`, `.pinned.example`, `example`, `pinned.example:8080`, `http://pinned.example`, `other.example`, `other.example, *`) × URL (`http://pinned.example/x`, `http://pinned.example:8080/x`, `https://pinned.example/x`, `https://sub.pinned.example/x`); Orakel ist ein gewöhnlicher `httpx.Client()` in derselben Umgebung mit derselben URL, Verbindungen aufgezeichnet: geht er an den Proxy, geht `pinned_client` an den Proxy; geht er an `(<host>, port)`, geht `pinned_client` an `(_V4, port)`. Der Test zählt beide Ausgänge und verlangt je mindestens einen Fall. (d) Unter dem Pin: `HTTPS_PROXY` + `NO_PROXY=pinned.example`, `https://pinned.example/x` → genau eine Anfrage mit `url.host == _V4`, `headers["host"] == "pinned.example"`, `extensions["sni_hostname"] == "pinned.example"`. (e) Weiche: ohne Proxy und `NO_PROXY=pinned.example:abc` sowie mit `HTTPS_PROXY=ftp://192.0.2.10:21` bei `http://pinned.example/x` baut der Client und verbindet an `(_V4, 80)`. Zuerst rot: (a), (c), (d) auf HEAD. Grün bleiben (b), (e), `test_a_proxy_for_the_scheme_keeps_the_proxy_path` (`:402-422`), `test_with_a_proxy_the_request_leaves_with_the_hostname` (`:425-436`), `test_a_rejected_target_gets_no_client` (`:357-370`), `test_closing_the_client_closes_the_inner_transport` (`:373-396`); die Kommentare `:46-47` („The proxy branch sets its own below“) und `:360-361` („Checked before the proxy branch“) sagen, was nach der Änderung gilt. Mutations-Stichprobe in einem eigenen Probe-Worktree, je allein, beide Kopien gleich: M1 Weiche weg (Mounts immer) → (e) rot; M2 `mounts=` weggelassen → (b) und `:402-422` rot; M3 nur Proxy-Muster gemountet (`None` gefiltert) → (a) und (c) rot. Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_pin.py tests/test_ssrf_parity.py tests/test_ssrf.py tests/test_hooks_http_ssrf.py
Doku: docs/developer/hooks.html:77, docs/developer/monitoring.html:175, docs/admin/monitoring.html:339 und EN je gleiche Zeile: statt des Teils, nach dem ein Ziel unter `NO_PROXY` direkt über den Namen verbunden wird, steht, dass ein Ziel, das wegen `NO_PROXY` nicht über den Proxy geht, wie ohne Proxy zu einer der geprüften Adressen verbindet · CHANGELOG.md (Changed, umlautfrei: SSRF-Schutz: ein Ziel, das wegen `NO_PROXY` nicht ueber den gesetzten Proxy geht, verbindet wie ohne Proxy zu einer der geprueften Adressen, im HTTP-Check, im Alert-Webhook und in `http_get`/`http_post` der Hooks; welche Anfragen ueber den Proxy gehen, bleibt gleich)
Beweis: origin/main@53a7dbc5 · Code-Lesung apps/server/app/core/ssrf.py:291-299 · Proben in der Spec (Problem 1, Trade-off 1 und 2)
Orakel: differential — ein gewöhnlicher `httpx.Client()` in derselben Umgebung entscheidet, ob über den Proxy oder direkt
HEAD: 53a7dbc5

### T2 — Monitoring: HTTP-Check und Webhook neben einem Proxy, Ziel unter NO_PROXY (gehört zum Paket)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_http_checker.py, apps/monitoring/tests/test_alerter.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6009d7e7 2026-10-23T19:18:01+02:00
Review: approve (.ah-out/review/ssrf-followups/T2.verdict.json)
Änderung: Je ein Test neben den bestehenden Proxy-Tests (`test_http_checker_with_a_proxy_for_the_scheme_the_proxy_connects`, `test_http_checker.py:289-300`; `TestWebhookSsrf.test_with_a_proxy_for_the_scheme_the_proxy_connects`, `test_alerter.py:306-320`), mit denselben Helfern (`_resolving`, `_connections_refused` bzw. `_resolving_to`, `_connections_refused`): (a) HTTP-Check: `HTTP_PROXY=http://192.0.2.10:3128`, `NO_PROXY=checks.example`, `{"url": "http://checks.example:8080/x"}`, Resolver → `_FIRST` → gefragt genau `["checks.example"]`, verbunden genau `[(_FIRST, 8080)]`, Ergebnis `("critical", "Connection failed: refused by the test")`. (b) Webhook: `HTTPS_PROXY=http://192.0.2.10:3128`, `NO_PROXY=*`, `https://hooks.example.com:8443/x` → gefragt genau `["hooks.example.com"]`, verbunden genau `[(_PUBLIC, 8443)]`, `(False, "Webhook connection failed")`. Rot auf 53a7dbc5 (verbunden an `("checks.example", 8080)` bzw. `("hooks.example.com", 8443)`), grün nach T1: Revert-Probe von T1 in einem eigenen Worktree, Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py tests/test_alerter.py tests/test_ssrf.py
Doku: keine (Doku und CHANGELOG trägt T1)
Abhängt von: T1; PR #265 auf `main` und in den Branch gemergt
Beweis: origin/main@53a7dbc5 · Code-Lesung apps/monitoring/app/core/ssrf.py:289-297
Orakel: contract — neben einem Proxy verbindet ein Ziel unter `NO_PROXY` zur geprüften Adresse, am Aufrufer gemessen
HEAD: 53a7dbc5

### T3 — Guard: URL mit einzelnem Surrogat wird abgelehnt statt geworfen; Kommentar-Beispiel; Docstring des Property-Tests (R-0606, R-0599)  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf_pin.py, apps/server/tests/test_ssrf_properties.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @128f4b6a 2026-10-23T06:53:07+02:00
Review: approve (.ah-out/review/ssrf-followups/T3.verdict.json)
Änderung: Beide Kopien: `except httpx.InvalidURL:` in `check_target` (`ssrf.py:176`, Monitoring `:174`) → `except (httpx.InvalidURL, UnicodeError):`; der Docstring (`:150-163`) nennt bei „A URL httpx cannot read“ auch ein einzelnes Surrogat. Kommentar `:168-169` (Monitoring `:166-167`): das Beispiel `"http://[::1"` wird `"http://["` (das liest httpx als Host `%5B`; bei `"http://[::1"` wirft httpx `InvalidURL: Invalid port: ':1'`). Test in `test_ssrf_pin.py` neben `test_a_host_httpx_cannot_send_is_rejected_without_resolving` (`:178-192`): parametrisiert über `"http://pinned.example/\ud800"`, `"http://pinned.example/?q=\udcff"`, `"http://pinned.example/#\ud800"`, `"http://us\ud800er@pinned.example/"` → `check_target(url) == Target(UrlVerdict.PRIVATE)`, Resolver nicht gefragt, `is_private_url(url) is True`. Zuerst rot: alle vier auf HEAD (`UnicodeEncodeError`). Docstring `test_the_guard_checks_the_host_that_httpx_will_actually_fetch` (`test_ssrf_properties.py:142-151`), Satz `:147-149` (R-0599): lesen Guard und httpx verschiedene Hosts, lehnt der Pin die Anfrage ab (er vergleicht den Host der Anfrage mit dem geprüften, `_PinnedTransport.handle_request`), und über einen Proxy holte der Proxy einen Host, den der Guard nicht geprüft hat; der Rest des Docstrings und der Test bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_pin.py tests/test_ssrf_properties.py tests/test_ssrf_parity.py tests/test_ssrf.py tests/test_hooks_http_ssrf.py
Doku: CHANGELOG.md (Fixed, umlautfrei: SSRF-Schutz: eine URL mit einem einzelnen Surrogat, etwa aus einem JSON-Payload, wird als unlesbar abgelehnt, statt eine Exception zu werfen; HTTP-Check, Alert-Webhook und `http_get`/`http_post` melden ihre gewoehnliche Ablehnung) · `docs/` keine (die Doku sagt schon, dass eine unlesbare URL abgelehnt wird)
Abhängt von: T1
Beweis: origin/main@53a7dbc5 · Probe (`ssrf._resolve` ersetzt): `check_target` mit Surrogat in Pfad, Query, Fragment oder Userinfo wirft `UnicodeEncodeError`, der Resolver wird nicht gefragt; Surrogat im Host oder Port → `PRIVATE`; dreimal identisch (gleiche md5)
Orakel: contract — eine URL, die httpx nicht lesen kann, ist `Target(PRIVATE)` ohne Auflösung
Dedup-Key: ref:ssrf:post-r0590-nits
HEAD: 53a7dbc5
Semantik: `docs/developer/hooks.html:77` — „Abgelehnt wird auch eine URL, die sich nicht lesen lässt oder keinen Host hat“; `apps/server/app/core/ssrf.py:154-156` — „A URL httpx cannot read (a host it cannot encode, a port that is no number) is rejected like an unreadable URL“

### T4 — Monitoring: unlesbare URL und Surrogat am HTTP-Check und am Webhook; Kommentare zum try (R-0606)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/app/alerter.py, apps/monitoring/tests/test_http_checker.py, apps/monitoring/tests/test_alerter.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @0de4f72d 2026-10-23T19:26:46+02:00
Review: approve (.ah-out/review/ssrf-followups/T4.verdict.json)
Änderung: Kommentare, kein Code: in `http.py` der Kommentar über `pinned_client(…)` (heute `:50-51`, nach #265 in der Redirect-Schleife) und in `alerter.py` über `pinned_client(url, target)` in `_send_webhook` (`:599-600`): statt „it parses the URL already, so it sits in the try“ steht, dass `check_target` die URL schon mit httpx gelesen hat und `pinned_client` im `try` steht, weil der Bau des Clients an einer unbrauchbaren Proxy-Angabe aus der Umgebung scheitern kann (Spec, Problem 4). Tests mit dem echten Guard (Resolver ersetzt und aufgezeichnet, Anfragen unter dem Pin aufgezeichnet): (a) `HttpChecker().run` mit `https://☃.example/`, `http://checks.example:abc/` und `"http://checks.example/\ud800"` → `("unknown", "URL points to a private/reserved address, rejected by the SSRF guard", None)`, Resolver nicht gefragt, keine Anfrage. (b) `alerter._send_webhook` mit denselben drei Formen unter `hooks.example.com` → `(False, "Webhook target is private/reserved (not allowed)")`, Resolver nicht gefragt, keine Anfrage. Rot auf 53a7dbc5: die Surrogat-Fälle in (a) und (b) (`UnicodeEncodeError` aus `run` bzw. `_send_webhook`); grün nach T3 (Revert-Probe von T3 in einem eigenen Worktree, Ergebnis in den Commit-Body).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py tests/test_alerter.py
Doku: keine (CHANGELOG trägt T3)
Abhängt von: T3; PR #265 auf `main` und in den Branch gemergt
Beweis: origin/main@53a7dbc5 · Code-Lesung apps/monitoring/app/checkers/http.py:34 und apps/monitoring/app/alerter.py:576 (`check_target` vor dem `try`) mit der Probe aus T3; Folgen `apps/monitoring/app/check_engine.py:314-320` und `alerter.py:203-210`
Orakel: contract — eine unlesbare URL ergibt am Aufrufer die gewöhnliche Ablehnung ohne Anfrage
Dedup-Key: ref:ssrf:post-r0590-nits
HEAD: 53a7dbc5

### T5 — Monitoring-Tests: verify am Redirect-Hop, Fehlertext aus httpx (R-0599)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_http_checker.py, apps/monitoring/tests/test_alerter_dispatch.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @d0de71af 2026-10-23T19:33:00+02:00
Review: approve (.ah-out/review/ssrf-followups/T5.verdict.json)
Änderung: (a) Neuer Test neben `test_http_checker_verify_ssl_off_only_for_real_false` (`test_http_checker.py:114-135`), gleiche Naht (`HTTPTransport.__init__` zeichnet `verify` auf, `handle_request` antwortet): erste Antwort `302` mit `location: http://moved.example/`, zweite `200`; Resolver für beide Hosts öffentlich (`_resolving`). Mit `verify_ssl: False` → `seen == [False, False]`, Status `ok`, Meldung mit `[TLS verification disabled]`; mit `verify_ssl: True` → `[True, True]`. (b) `test_a_url_httpx_cannot_read_stores_a_fixed_reason` (`test_alerter_dispatch.py:124-136`): die erwartete Zeile nimmt den Text von httpx (`with pytest.raises(httpx.InvalidURL) as info: httpx.URL("https://hooks.example.com:abc/x")`, dann `[f"Webhook failed: c -> hooks.example.com: {info.value}"]`); der Rest des Tests bleibt. Mutations-Stichprobe im Probe-Worktree: M1 der Hop verbindet mit `verify=True` (heute `http.py:80`; nach #265 der eine Aufruf in der Schleife, nur für Hops) → (a) rot. Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py tests/test_alerter_dispatch.py
Doku: keine (nur Tests)
Abhängt von: T4 (gleiche Testdatei); PR #265 auf `main` und in den Branch gemergt
Beweis: origin/main@53a7dbc5 · Code-Lesung: kein Test zeichnet `verify` bei einem Redirect auf (`test_http_checker.py:114-135` ohne Redirect); `test_alerter_dispatch.py:136` vergleicht `Invalid port: 'abc'` wörtlich
Orakel: mutation-sample — M1 wie in `Änderung:`; eine Stichprobe, kein Beweis der Vollständigkeit
Dedup-Key: ref:monitoring:ssrf-tests-nits
HEAD: 53a7dbc5

### T6 — Guard-Tests: verify an den Proxy-Mounts; Docstring des Property-Tests sagt, was der Pin vergleicht (Branch-Prüfung)  [x]
Komponente: server · Dateien: apps/server/tests/test_ssrf_pin.py, apps/server/tests/test_ssrf_properties.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b333b63f 2026-10-23T20:09:55+02:00
Review: approve (.ah-out/review/ssrf-followups/T6.verdict.json)
Änderung: (a) Seit T1 baut `pinned_client` die Proxy-Transports selbst (`httpx.HTTPTransport(verify=verify, proxy=proxy)`, `apps/server/app/core/ssrf.py`, gleich in der Monitoring-Kopie); vorher reichte `httpx.Client(verify=verify)` den Wert an seine Proxy-Transports weiter. Kein Test kommt auf dem Proxy-Weg bis zu `verify` (Fund des tester). Neuer Test in `test_ssrf_pin.py`, Abschnitt Proxy: `HTTPS_PROXY=http://192.0.2.10:3128` (`_PROXY`), `https://pinned.example/x`, parametrisiert über `verify` = `False`, `True` und ein `ssl.SSLContext`; `httpx.HTTPTransport.__init__` zeichnet seine Argumente auf (Original danach aufrufen); geprüft: der Transport mit `proxy=` bekam genau diesen `verify` (bei `SSLContext` dasselbe Objekt), der innere Transport des Pins ebenso, und es entsteht genau ein Proxy-Transport für das Muster `https://`. Proxy-Variablen vorher löschen wie die Nachbartests. Mutations-Stichprobe in einer Kopie (beide Guard-Kopien gleich, je allein): M1 `HTTPTransport(proxy=proxy)` → die Fälle `False` und `SSLContext` rot; M2 `HTTPTransport(verify=False, proxy=proxy)` → die Fälle `True` und `SSLContext` rot. Ergebnis in den Commit-Body. (b) Docstring von `test_the_guard_checks_the_host_that_httpx_will_actually_fetch` (`test_ssrf_properties.py`, der in T3 geänderte Satz): der Pin vergleicht den Host der Anfrage mit dem Host, den httpx aus derselben URL in `pinned_client` liest (`_PinnedTransport(parsed.raw_host…)`), nicht mit dem Host, den der Guard geprüft hat; der Satz sagt, was nach `check_target` und `pinned_client` wirklich gilt, wenn Guard und httpx verschiedene Hosts läsen (vorher am Code prüfen und mit einer Probe belegen; Fund des Branch-Reviewers: `pinned_client("http://pinned.example/x", Target(ALLOWED, "other.example", (_V4,)))` verbindet). Der Rest des Docstrings und der Test bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_pin.py tests/test_ssrf_properties.py tests/test_ssrf_parity.py
Doku: keine (nur Tests)
Abhängt von: T1, T3
Beweis: feature/ssrf-followups@a14a11d3 · Code-Lesung: kein Test zeichnet `verify` an einem Proxy-Transport auf (Proxy-Tests in `test_ssrf_pin.py`, `test_http_checker.py`, `test_alerter.py`, `test_hooks_http_ssrf.py` brechen an `socket.create_connection` ab oder ersetzen `handle_request`); Probe des Branch-Reviewers zum Docstring
Orakel: mutation-sample — M1 und M2 wie in `Änderung:`; eine Stichprobe, kein Beweis der Vollständigkeit
Dedup-Key: ref:server:ssrf-tests-proxy-verify
HEAD: a14a11d3
