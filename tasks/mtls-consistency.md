<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# mTLS: `MTLS_ENFORCE` in Server und Gateway gleich, Identitäts-Header nur vom Gateway — Task-Ledger
Status: erledigt · Branch: feature/mtls-consistency · Review: pro Task
Spec: docs/features/mtls-consistency.md (Härtung, Kevin 2026-10-22)
Heavy: linux-full + scenario --agents 1 --enforce — der Diff ändert, wann der Server eine Zertifikats-Identität annimmt (`apps/server/app/core/identity.py`, T2) und wie er `MTLS_ENFORCE` liest (`apps/server/app/core/config.py`, T1); jede Anfrage mit Client-Zertifikat hängt daran. `linux-full` im Sammellauf über `main`: `integration-stack` (Stack mit `MTLS_ENFORCE=true`, Zertifikats-Wege über das Gateway in den Schritten 4–8b, der neue Schritt aus T3 mit dem Neuanlegen des Gateways), `sse-push` (SSE mit Zertifikat), `upgrade-path`; auf PRs läuft der Stack-Job nicht, daher vor dem Merge `gh workflow run ci.yml --ref feature/mtls-consistency`. `scenario` vor dem Merge (ask-first): nur er fährt einen echten Agent von einem zweiten Host mit Zertifikat über das Gateway unter `MTLS_ENFORCE=true` (Provisionierung, Metriken, Konfiguration) gegen die Prüfung der Gegenstelle. Kein `windows`: kein Agent- und kein Desktop-Code; deren CI-Jobs laufen im PR ohnehin. Kein Compose-, Gateway- oder PKI-Diff.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Der Server liest `MTLS_ENFORCE` mit derselben Tabelle wie das Gateway; ein Test hält beide gleich (T1, wartet
auf Kevin). (2) Der Server wertet `X-Client-Verify`/`X-Client-Cert` nur aus, wenn die direkte Gegenstelle der
Compose-Dienst `gateway` ist, auch gleich nach einem Neuanlegen des Gateways (T2); der laufende Stack belegt es (T3).
Zeilenangaben: origin/main@53a7dbc5; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 und T2 sind unabhängig (beide in `apps/server/app/core/`, keine gemeinsame Datei);
  T1 wartet auf Kevin, T2 nicht. T2 braucht den Namens-Resolver aus feature/compose-hardening T11 in
  `apps/server/app/core/middleware.py`: vor dem Bau von T2 `origin/main` (mit T11) in den Branch mergen; ist T11 noch
  nicht auf `main`, bleibt T2 offen. T3 nach T2.
- Nachbar-Vorhaben in denselben Dateien (Spec, „Überschneidungen“): feature/docs-drift T7 (`identity.py:18-20`,
  `tests/test_mtls_scope.py`), feature/server-fixes T4 (`require_scope` → `check_scope`) und T1 (`tests/conftest.py`),
  feature/fehlervertrag T2 (403 mit `code`), feature/compose-hardening T8/T13 und feature/update-rollback T3
  (`scripts/tests/integration_stack_test.sh`). T2 ändert in `identity.py` nur `get_client_identity`, den
  Modul-Docstring `:5-11` und eine neue Konstante; vor jedem Task-Bau `origin/main` aufnehmen.
- Risikopfade (`scripts/dev/review-risk.txt`): `apps/server/app/core/identity.py` (T2) → zusätzlich `security`;
  ebenso T1 (Vertrauensgrenze `MTLS_ENFORCE`).
- Neue Code-Strings (Kommentare, Log-Zeilen) englisch; bestehende deutsche Texte bleiben. CHANGELOG unter
  `## [Unreleased]` → `### Changed`, umlautfrei. Test-Adressen nur RFC 5737 (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`).
- Keine neue Umgebungsvariable, keine Änderung an `docker-compose.yml`, `apps/gateway/` oder Skripten unter
  `scripts/` außer `scripts/tests/integration_stack_test.sh`.

### T1 — Server: `MTLS_ENFORCE` wie das Gateway lesen  [x]
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d1ad8eb2 2026-10-23T16:08:43+02:00
Review: approve (.ah-out/review/mtls-consistency/T1.verdict.json)
Entscheidung: Kevin 2026-10-23: (a) wie das Gateway: `on`, leer und unbekannte Werte erzwingen, ein unbekannter Wert mit WARNING (fail-closed). Restrisiko der Variante V1 hingenommen, V2 wird nicht gebaut.
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/tests/test_mtls_enforce_parse.py, .env.example, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Änderung (Empfehlung): Neue Funktion `parse_mtls_enforce(raw: str | None) -> bool` in `apps/server/app/core/config.py` mit der Tabelle des Gateways (`apps/gateway/docker-entrypoint.sh:37-53`): `None` oder leer → `True`; sonst `raw.lower()` ohne Abschneiden von Leerzeichen; `1|true|yes|on` → `True`; `0|false|no|off` → `False`; jeder andere Wert → `True` und eine WARNING (englisch, nennt den Wert per `repr` und „fail-closed“). `:144` wird `MTLS_ENFORCE = parse_mtls_enforce(os.environ.get("MTLS_ENFORCE"))`; die Log-Zeilen `:145-150` bleiben; der Kommentar `:136-143` bekommt einen Satz: dieselbe Tabelle wie der Entrypoint des Gateways, der Test hält sie gleich. Neue Testdatei `apps/server/tests/test_mtls_enforce_parse.py` (SPDX-Header): (a) Tabelle: `true`, `TRUE`, `1`, `yes`, `on`, `On` → `True`; `false`, `0`, `no`, `off`, `OFF` → `False`; `None`, `""` → `True`; `ture`, `enforced`, `" true"` → `True` mit genau einer WARNING (`caplog`); die bekannten Werte ohne WARNING. (b) Parität: der Test liest den Block von `^case .*MTLS_ENFORCE` bis `^esac` aus `apps/gateway/docker-entrypoint.sh` (wie `scripts/tests/gateway_mtls_test.sh`), führt ihn je Wert aus (a) mit `sh` und `SNIPPET_DIR` = `tmp_path` aus (ungesetzt: Env ohne `MTLS_ENFORCE`), liest `data-plane-mtls.conf` (`ssl_verify_client on;` → `True`, `optional;` → `False`) und vergleicht mit `parse_mtls_enforce`; ein fehlender `case`-Block lässt den Test fallen, nicht überspringen. Zuerst rot: `on`, `On`, `""`, `ture`, `enforced`, `" true"` in (a) und (b). Die Suite bleibt permissiv (`apps/server/tests/conftest.py:21` setzt `false`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_mtls_enforce_parse.py tests/test_mtls_scope.py
Doku: `.env.example:109-118` (Werte: `true/1/yes/on` erzwungen, `false/0/no/off` permissiv, jeder andere Wert erzwungen mit Warnung, in Gateway und Server gleich) · `docs/admin/betrieb.html:262` + `docs/en/admin/operations.html:220` (ein Satz mit denselben Werten) · CHANGELOG (Changed, umlautfrei: Der Server liest MTLS_ENFORCE wie das Gateway; `on` und unbekannte Werte erzwingen die Scope-Pruefung je Route, ein unbekannter Wert loggt eine Warnung)
Beweis: Code-Lesung apps/server/app/core/config.py:144 gegen apps/gateway/docker-entrypoint.sh:37-53; Probe an 53a7dbc5 (case-Block mit `sh`, Ausdruck des Servers mit Python 3.13): `on`, `On`, leer, `ture`, `enforced`, `" true"` → Gateway erzwungen, Server permissiv
Orakel: differential — Tabelle des Servers gegen den `case`-Block des Gateways
HEAD: 53a7dbc5

### T2 — Server: Identitäts-Header nur vom Gateway  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/core/middleware.py, apps/server/tests/conftest.py, apps/server/tests/test_identity_source.py, docs/developer/index.html, docs/en/developer/index.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @364facfc 2026-10-23T17:02:18+02:00
Review: approve (.ah-out/review/mtls-consistency/T2.verdict.json)
Änderung: `get_client_identity` (`apps/server/app/core/identity.py:78-105`) prüft nach dem Vergleich mit `SUCCESS` (`:84`) die Gegenstelle: fehlt `request.client` oder ist `request.client.host` keine aktuelle Adresse des Namens `gateway`, gibt sie `_UNVERIFIED` zurück und loggt eine WARNING (englisch, nennt die Gegenstelle; höchstens einmal je Adresse und Minute). Die Namensliste ist eine feste Konstante in `identity.py` (`("gateway",)`), nicht `TRUSTED_PROXIES`; die Adressen liefert der Namens-Resolver aus `apps/server/app/core/middleware.py` (compose-hardening T11). Im Resolver neu, soweit T11 es nicht schon bietet: eine sofortige Auffrischung bei Fehltreffer — ist die Gegenstelle nicht im Cache, löst der Resolver den Namen neu auf, höchstens einmal je Sekunde über alle Anfragen, und `get_client_identity` wartet höchstens 1 s auf das Ergebnis (sync-Dependency im Threadpool, die Event-Loop blockiert nicht). Anfragen ohne `X-Client-Verify: SUCCESS` lösen keine Auflösung aus. Modul-Docstring `identity.py:5-11`: den Headern wird vertraut, weil der Server sie nur von der Gegenstelle `gateway` annimmt (nicht mehr „solely through the gateway“ wegen des fehlenden Host-Ports). `apps/server/tests/conftest.py`: autouse-Fixture, die in der Suite jede Gegenstelle als Gateway gelten lässt (Requests ohne `client` in `tests/test_mtls_scope.py:74-79` und `tests/test_identity_revocation.py:122-125`, TestClient-Gegenstelle `testclient`); keine bestehende Zusicherung ändert sich. `apps/server/tests/test_identity_source.py` (neu, SPDX-Header) hebt die Fixture auf und ersetzt die Namensauflösung (keine echte DNS-Abfrage): (a) Gegenstelle `192.0.2.10`, `gateway` → `192.0.2.10`, gültige Header → verifiziert; (b) Gegenstelle `192.0.2.11` → nicht verifiziert, eine WARNING, eine zweite Anfrage derselben Adresse in der Minute ohne weitere WARNING; (c) `gateway` löst inzwischen auf `192.0.2.20` auf, der Cache hält `192.0.2.10`: Anfrage von `192.0.2.20` → verifiziert, genau eine zusätzliche Auflösung; (d) zwei Anfragen von `192.0.2.11` in derselben Sekunde → höchstens eine zusätzliche Auflösung; (e) die Auflösung scheitert oder dauert länger als 1 s → nicht verifiziert, keine Exception; (f) Anfrage ohne Header von `192.0.2.11` → keine Auflösung; (g) über die App mit `TestClient(app, client=(…, 50000))`, `config.MTLS_ENFORCE=True`, JWT des Admins und einem Zertifikat mit CN = Benutzername und Scope `access` (Muster `_gateway_headers`, `tests/test_mtls_scope.py:66-71`; `require_cert_user`, `apps/server/app/core/auth.py:229`): `GET /api/servers` von `192.0.2.11` → 403, von `192.0.2.10` → 200. Zuerst rot: (b), (d), (g) mit `192.0.2.11`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_source.py tests/test_mtls_scope.py tests/test_certificate_check.py tests/test_cert_user_binding.py tests/test_identity_revocation.py tests/test_device_api.py tests/test_identity_header_contract.py tests/test_ip_filter.py
Doku: `docs/developer/index.html:106` + `docs/en/developer/index.html:84`: der Server wertet die `X-Client-*`-Header nur aus, wenn die Anfrage direkt vom Dienst `gateway` kommt; die Begründung „kein Host-Port, daher unfälschbar“ / „so the header is unforgeable“ wird entsprechend ergänzt · CHANGELOG (Changed, umlautfrei: Der Server wertet die Zertifikats-Header nur noch aus, wenn die Anfrage direkt vom Gateway kommt)
Abhängt von: feature/compose-hardening T11 auf `main` (Namens-Resolver in `apps/server/app/core/middleware.py`)
Beweis: Code-Lesung apps/server/app/core/identity.py:78-105, docker-compose.yml:37-131 (`server` ohne `networks:`), :449-456
HEAD: 53a7dbc5

### T3 — Stack-Prüfung: Identitäts-Header nur über das Gateway  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @25ce52e5 2026-10-23T17:28:13+02:00
Review: approve (.ah-out/review/mtls-consistency/T3.verdict.json)
Änderung: Neuer Schritt `7b` nach Schritt 7 (`scripts/tests/integration_stack_test.sh:129-145`) und vor Schritt 8 (das Zertifikat aus Schritt 2 gilt dort noch; Schritt 8b widerruft das Gerät später). (a) Aus dem server-Container (`e2e_dc exec -T server python -c …`, `urllib.request`) an `http://server:8080/api/servers` mit `Authorization: Bearer $JWT` (Schritt 5), `X-Client-Verify: SUCCESS` und `X-Client-Cert` = das erste Zertifikat aus `$E2E_WORK/client-fullchain.pem` (`openssl x509`), URL-kodiert mit `urllib.parse.quote` wie `$ssl_client_escaped_cert` → 403: der Stack läuft mit `MTLS_ENFORCE=true` (`:38`), die Gegenstelle ist nicht das Gateway. (b) Gegenprobe derselbe Weg ohne die beiden Header → 403 (der Direktweg erreicht den Server, nur die Identität fehlt), damit (a) nicht an etwas anderem hängt. (c) Gegenprobe über das Gateway wie Schritt 6 (`:124-127`) → 200. (d) Adresse des Containers `gateway` im Default-Netz merken (`docker inspect`), `e2e_dc up -d --no-deps --force-recreate gateway` (ohne `--build`), warten, bis `:443` certless wieder 400 liefert (wie Schritt 3, höchstens 60 s), dann sofort die Anfrage aus (c) → 200; alte und neue Adresse als Info-Zeile im Log. Auf HEAD ist (a) 200 — der Schritt kann fallen. Den echten Lauf fährt die Session (Dispatch des `integration-stack`-Jobs auf dem Branch oder `/test` in der Lane); seine Summary-Zeile `integration_stack_test: N passed, 0 failed` kommt in den PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T2
Beweis: Code-Lesung scripts/tests/integration_stack_test.sh:38 (`e2e_init true`), :124-127; apps/server/app/core/identity.py:84-105
HEAD: 53a7dbc5

### T4 — Server: `MTLS_ENFORCE` wieder mit Default lesen (Env-Parität)  [x]
Komponente: server · Dateien: apps/server/app/core/config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @263cb7ec 2026-10-23T18:06:28+02:00
Review: approve (.ah-out/review/mtls-consistency/T4.verdict.json)
Änderung: T1 hat `os.environ.get("MTLS_ENFORCE", "true")` zu `os.environ.get("MTLS_ENFORCE")` gemacht; seitdem meldet `apps/server/tests/test_env_parity.py::test_every_variable_without_a_default_is_set_in_compose` `{'scheduler': ['MTLS_ENFORCE']}` (der scheduler liest die Server-Config, Compose setzt ihm `MTLS_ENFORCE` nicht). Die Zuweisung liest wieder mit Default: `MTLS_ENFORCE = parse_mtls_enforce(os.environ.get("MTLS_ENFORCE", "true"))`. Verhalten unverändert (ungesetzt → `"true"` → erzwungen; leer → erzwungen); `parse_mtls_enforce(None)` bleibt wie es ist (Paritätstest, Fall „ungesetzt“). Keine Compose-Änderung, kein Test geändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_env_parity.py tests/test_mtls_enforce_parse.py tests/test_mtls_scope.py
Doku: keine (Verhalten unverändert)
Abhängt von: T1
Beweis: feature/mtls-consistency@4291f912 · bash scripts/dev/verify.sh server --strict (volle Server-Suite nach dem Merge von origin/main e7b255b9) → 1 failed: tests/test_env_parity.py::test_every_variable_without_a_default_is_set_in_compose
Orakel: contract — Env-Paritätstest (Lesen ohne Default gegen die Compose-Umgebung)
HEAD: 4291f912

### T5 — Tests: zweite Auffrischung außer der Reihe und Ausräumen der Warn-Einträge  [x]
Komponente: server · Dateien: apps/server/tests/test_identity_source.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2461ea69 2026-10-23T18:47:43+02:00
Review: approve (.ah-out/review/mtls-consistency/T5.verdict.json)
Änderung: Nur Tests, kein Produktcode. (1) `test_a_new_gateway_address_counts_at_once` (`tests/test_identity_source.py:140`) bekommt ein zweites Neuanlegen des Gateways nach Ablauf von `_NAME_URGENT_GAP`: `identity._GATEWAY._urgent_at -= 1` (eine Sekunde später, Muster `_ignored_logged[OTHER] -= 60` in `:127`), `dns.answer = ["192.0.2.21"]`; eine Anfrage mit gültigen Headern von `192.0.2.21` ist verifiziert, und `dns.calls == 3` (genau eine weitere Auflösung außer der Reihe). Heute belegt kein Test, dass nach der ersten Auflösung außer der Reihe je eine zweite startet; die Mutante `if urgent is None:` in `apps/server/app/core/middleware.py` (`has_address`, `:121-123`) bliebe grün. Neue Adresse nur aus RFC 5737. (2) Neuer Test in derselben Datei: ein Eintrag in `identity._ignored_logged`, der älter als `_IGNORED_LOG_INTERVAL` ist, ist nach der nächsten Warnung für eine andere Gegenstelle ausgeräumt (`apps/server/app/core/identity.py:125-127`); heute bliebe eine Mutante ohne die Schleife grün. Zuerst rot: (1) gegen die Mutante `if urgent is None:`, (2) gegen die Mutante ohne die Schleife (beide nur als Probe, nicht committen).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_source.py tests/test_ip_filter.py
Doku: keine (Test)
Abhängt von: T2
Beweis: tester-Urteil über feature/mtls-consistency (`.ah-out/review/mtls-consistency/tester.verdict.json`): wichtig `apps/server/app/core/middleware.py:121`, nit `apps/server/app/core/identity.py:125`
Orakel: mutation-sample — die Tests fallen gegen die genannten Mutanten
HEAD: c19307fc

### T6 — Stack-Prüfung: Adresswechsel des Gateways erzwingen  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @25d64272 2026-10-23T20:50:40+02:00
Review: approve (.ah-out/review/mtls-consistency/T6.verdict.json)
Änderung: Schritt 7b(d) in `identity_from_gateway` (`scripts/tests/integration_stack_test.sh:221-243`) beweist die Auffrischung heute nicht: Im Stack-Dispatch auf 28e97ee3 behielt das neu angelegte Gateway seine Adresse (Log: `before/after the recreate: '<a>' -> '<a>' (unchanged, so the server needed no fresh lookup)`), weil Docker die frei gewordene Adresse sofort wieder vergibt. (1) Den Adresswechsel erzwingen: die alte Adresse des Gateways im Default-Netz des Projekts belegen, solange das Gateway neu startet. Ein Beispiel: Gateway stoppen und entfernen, einen Platzhalter-Container ins Default-Netz setzen, der die alte Adresse hält, Gateway starten, danach den Platzhalter mit vollem Namen entfernen. Das genaue Verfahren wählt der builder, nachdem er die Docker-Doku zur IPAM-Vergabe gelesen hat (`docker run --ip`/`network connect --ip` und Default-Netz ohne eigenes Subnetz; ob die Vergabe die niedrigste freie Adresse nimmt; nicht verifiziert). Hält der Platzhalter nicht genau die alte Adresse, ist das `bad`, kein stilles Weiter. (2) Der Platzhalter wird auch bei Abbruch entfernt. Der EXIT-Trap gehört `e2e_teardown` (`scripts/tests/lib_e2e_stack.sh:258`): nicht ersetzen. Ein Container im Default-Netz, der nicht von Compose stammt, kann `e2e_dc down -v` am Entfernen des Netzes hindern. Das Image des Platzhalters muss ohne Pull lokal da sein, etwa ein Image des Stacks. (3) `old == new` wird `bad` statt `info`, damit (d) fallen kann; die Info-Zeile mit alter und neuer Adresse bleibt. (a)–(c) bleiben unverändert. Test-Adressen in neuen Zeilen nur aus RFC 5737, falls welche nötig sind.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T3
Beweis: Stack-Dispatch auf feature/mtls-consistency@28e97ee3 (Session): integration-stack grün, Schritt 7b(d) mit unveränderter Gateway-Adresse
Orakel: contract — (d) muss fallen, wenn das Gateway seine Adresse behält oder der Server die neue nicht annimmt
HEAD: 28e97ee3
