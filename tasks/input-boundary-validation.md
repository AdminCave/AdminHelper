<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Randvalidierung für Zahlen und Text — Task-Ledger
Status: blockiert · Branch: feature/input-boundary-validation · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/input-boundary-validation.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: path-gated — der Diff berührt `apps/server`-Routen; am Abschluss am realen Diff entscheiden (reine Eingangsprüfung ohne Datenfluss-Änderung ⇒ vermutlich nicht nötig, dann mit Begründung überspringen).
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entschieden am Gate (Kevin, 2026-09-22): Obergrenzen sind die **technischen** Grenzen der Spalte;
die tz-naiven Zeitstempel bleiben **draußen** (eigene Roadmap-Zeile); PR #29 ist gemergt, also
baubereit. Spec und Ledger sind der erste Commit dieses Branches, gesetzt am Gate — das Artefakt ist
also versioniert, bevor freigegeben wird, und eine Lane kann den Branch auschecken.

**Die Fundmenge kommt aus dem OpenAPI-Schema, nicht aus einem grep.** Worker2 hat am 2026-09-22
für PR #29 genau diese Suche gefahren — alle Integer-Parameter ohne `maximum`, also die Menge,
die ein Fuzzer bis `2**63` treiben kann: **neun** im Server, **drei** im Monitoring. Drei der
neun Server-Treffer standen bis dahin nur check-granular in der Ausschlussliste, `not_a_server_error`
lief dort also weiter. Diese Liste ist die Vorgabe für T2–T4; wer sie erweitert, nennt den Beleg.
**Bekannte Grenze der Suche:** sie deckt Query- und Pfadparameter ab, nicht Integer-Felder in
Request-Bodies — dafür ist T5 da, und dort ist bisher nur `mark_read` belegt. Eine Route wurde
ausdrücklich **nicht** gelistet, weil sie bei `2**63` mit 404 antwortet statt zu überlaufen; ein
Eintrag „vorsorglich" wäre eine Behauptung ohne Befund. Dieselbe Regel gilt hier.

Regel für dieses Vorhaben: **Jede Schranke wird aus dem Spaltentyp des Modells abgeleitet, nicht
geraten.** Wer eine Grenze setzt, ohne das Modell gelesen zu haben, macht gültige Ids ungültig.
Zweite Regel: Ein Test je Fundstelle prüft **beide** Ränder — der höchste erlaubte Wert wird
akzeptiert, der erste unerlaubte ergibt 422.

### T1 — Begrenzte Typen an einer Stelle  [x]
Komponente: server · Dateien: apps/server/app/core/bounds.py (neu, SPDX), apps/server/tests/test_bounds.py (neu, SPDX)
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @84db6e9e 2026-09-22T18:33:48+02:00
Review: approve (sonnet, 2 Runden)
Änderung: `Annotated[int, Field(...)]`-Typen für die drei Grenzen: `IntPk` (`ge=1, le=2147483647`), `BigIntPk` (`ge=1, le=9223372036854775807`), `Offset` (`ge=0, le=2147483647`). Jeder Typ mit einem Satz Kommentar, welche Spaltenart er abdeckt. Keine Verwendung in diesem Task, nur der Baustein plus Test, dass die Ränder halten.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bounds.py
Doku: keine (intern)

### T2 — Server: Paginierung begrenzen  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/app/modules/connections/router.py, apps/server/app/modules/audit/router.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @6936bff4 2026-09-22T18:56:09+02:00
Review: approve (sonnet)
Änderung: die drei `Query(0, ge=0)` auf `Offset` aus T1 umstellen. Nur der Typ, keine Logik.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T3 — Server: Paginierung begrenzen, zweiter Teil  [x]
Komponente: server · Dateien: apps/server/app/modules/servers/router.py, apps/server/app/modules/notifications/router.py, apps/server/tests/test_pagination.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @f666ca22 2026-09-22T19:14:53+02:00
Review: approve (sonnet, 2 Runden)
Änderung: dieselbe Umstellung für die restlichen zwei Router; im bestehenden `test_pagination.py` ein Grenzfall-Test je Richtung (höchster erlaubter Offset ⇒ 200, erster unerlaubter ⇒ 422).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_pagination.py
Doku: keine (intern)
Abhängt von: T1

### T4 — Server: int-Pfadparameter begrenzen  [x]
Komponente: server · Dateien: apps/server/app/modules/users/router.py, apps/server/app/modules/api_keys/router.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_id_bounds.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @8604bf11 2026-09-22T19:38:16+02:00
Review: approve (sonnet, Mutationsprobe)
Änderung: die Pfadparameter `*_id: int` auf `IntPk`/`BigIntPk` umstellen — je Route am Spaltentyp des adressierten Modells geprüft. Das ist die Route, auf der `user_id ≥ 2**31` heute 500 liefert.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T5 — Server: Integer-Felder und Id-Listen im Body begrenzen  [x]
Komponente: server · Dateien: apps/server/app/core/bounds.py, apps/server/app/modules/notifications/schemas.py, apps/server/app/modules/frp/schemas.py, apps/server/tests/test_id_bounds.py, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @2d915289 2026-09-22T20:08:47+02:00
Review: approve (sonnet, Mutationsprobe)
Änderung: zuerst dieselbe Schema-Suche wie für die Parameter, aber über die **Request-Bodies** (Integer-Felder ohne `maximum`) — das ist die von Worker2 benannte Lücke. Dann `data.ids` (`notifications`) und `server_ids` (`users` zwei Stellen, `frp`) sowie die dabei gefundenen Felder im Schema auf `list[IntPk]` bzw. `list[BigIntPk]`; die Prüfung gehört ins Schema, nicht vor den `in_()`-Aufruf. Test für den belegten Fall (`ids` jenseits von BIGINT ⇒ 422).
Beim Bau korrigiert (2026-09-22): Die Schema-Suche über die Request-Bodies findet 13 Integer-Felder ohne `maximum`. Zwölf davon sind die FRP-Ports und -Zähler (`bind_port`, `vhost_https_port`, `dashboard_port`, `max_ports_per_client`, `local_port`, `visitor_port`, je in der Create- und der Update-Klasse) — alle `Column(Integer)`, alle einzeln nachgestellt: `2**63` ⇒ `NumericValueOutOfRange`, ungefangen. Das dreizehnte ist `MarkReadRequest.ids` (`Column(BigInteger)`, `2**63-1` ⇒ 200, `2**63` und `-(2**63)-1` ⇒ Überlauf). **`server_ids` ist kein Integer-Feld:** `users/schemas.py:60,66` deklariert `list[str]`, weil `servers.id` eine `String`-Spalte ist — hier gibt es keine Zahlschranke abzuleiten, und die Stelle in `frp/generate_router.py:56` ist überhaupt keine Eingabe, sondern wird aus `user.servers` gebildet. Die drei Router aus der ursprünglichen `Dateien:`-Liste entfallen damit; die Prüfung sitzt wie verlangt im Schema. Für Kevin notiert (Review-Fund, hier bewusst nicht geändert): `connections/schemas.py:16,44` begrenzt seinen `port` bereits fachlich auf `ge=1, le=65535`, ebenfalls auf einer `Column(Integer)`. Die FRP-Ports bekommen hier nur die Spaltenbreite, weil eine Portrange eine Produktentscheidung wäre, die das Gate nicht getroffen hat — die Inkonsistenz bleibt damit bestehen und gehört als eigene Zeile in die Roadmap, nicht in diesen Bugfix.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T6 — `_validate_tags` lehnt ab statt zu werfen  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @bd992d66 2026-09-22T20:28:47+02:00
Review: approve (sonnet, 2 Runden, Mutationsprobe)
Änderung: `_validate_tags` (Zeile 65) prüft als Erstes den Typ — kein `list` bzw. ein Element ohne `str` ergibt `ValueError` mit Feldbezug statt `AttributeError`/`TypeError`. `mode="before"` bleibt (die Normalisierung soll rohe Werte sehen), die sechs Registrierungen in `frp/`, `ansible/`, `servers/schemas.py` bleiben unberührt. Test mit dict, int, None und bool als `tags`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py
Doku: keine (intern)

### T7 — Server: NUL-Byte in Textfeldern ablehnen  [x]
Komponente: server · Dateien: apps/server/app/core/bounds.py, apps/server/app/modules/enrollment/router.py, apps/server/app/modules/audit/router.py, apps/server/tests/test_text_bounds.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @290b31bc 2026-09-22T20:53:13+02:00
Review: approve (sonnet, Mutationsprobe)
Änderung: ein `SafeText`-Typ in `bounds.py`, der `\x00` ablehnt (Postgres nimmt kein NUL in Textwerten), und sein Einsatz im Benutzernamen-Feld dieser Route. Bewusst nur dort, wo der Fuzz-Lauf es belegt hat — kein Flächen-Refactor aller Textfelder (YAGNI).
Beim Bau erweitert (2026-09-22), mit Beleg: der Ausschluss `list_audit_api_audit_get` in `tests/schemathesis_exclude.toml` steht seit dem Lauf vom 2026-09-21 wegen genau derselben Klasse über einen QUERY-Parameter. Alle sechs Textfilter von `GET /api/audit` einzeln nachgestellt: jeder endet in `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`, ungefangen. Ohne diese sechs könnte T10 den Audit-Ausschluss nicht entfernen. Das Schema hinter `POST /api/enrollment/token/for` ist die Inline-Klasse `EnrollmentTokenForRequest` in `enrollment/router.py`, keine eigene `schemas.py`. `SafeText` ist ein `AfterValidator`, kein `Field`-Constraint — er taucht deshalb nicht im OpenAPI-Schema auf, der Snapshot bleibt unverändert und das oasdiff-Gate (T11) sieht diese Task nicht.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)
Abhängt von: T1

### T8 — Server: Fremdschlüssel-Verletzung am Rand fangen  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_isolation.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @a1a9e519 2026-09-22T21:09:22+02:00
Review: approve (sonnet, Mutationsprobe)
Änderung: beim Anlegen einer Verbindung mit `server_id` die Existenz prüfen und mit 422 plus Feldbezug antworten, statt die `ForeignKeyViolation` durchlaufen zu lassen. Keine neue Fehlerform, dasselbe Format wie die übrigen 422.
Beim Bau erweitert (2026-09-22), mit Beleg: derselbe Fehler steht auf drei Routen desselben Routers, nicht nur auf dem Anlegen. Einzeln nachgestellt, alle drei mit ungefangener `psycopg.errors.ForeignKeyViolation`: `POST /api/connections`, `PUT /api/connections/{conn_id}` und `POST /api/connections/import` (mit `mode`, sonst scheitert schon das Schema). Nur die erste zu fixen hieße, eine von drei gekoppelten Stellen zu ziehen. Die ersten beiden werfen `RequestValidationError`, damit der Body die im Schema deklarierte `HTTPValidationError`-Form behält; die Import-Route meldet in ihrer eigenen `rejected`-Liste weiter, statt eine zweite Fehlerform zu erfinden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_isolation.py
Doku: keine (intern)

### T9 — Monitoring: Paginierung und Id-Listen begrenzen  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/bounds.py, apps/monitoring/app/routers/alerts.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_pagination.py, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @27b453ae 2026-09-22T21:17:29+02:00
Review: approve (sonnet, Mutationsprobe)
Änderung: dieselben Grenzen wie im Server, hier lokal deklariert (Monitoring ist ein eigener Dienst und teilt keinen Code mit dem Server): die drei `Query(0, ge=0)` in `alerts.py` und `checks.py` (zwei Stellen) und die `template_ids`-Liste. Das sind die zwei Routen, an denen der erste echte CI-Lauf des Fuzz-Jobs gefallen ist.
Beim Bau korrigiert (2026-09-22): **`template_ids` ist keine Eingabe.** `routers/templates.py:55` und `:88` bilden die Liste serverseitig aus bereits geladenen Zeilen (`[t.id for t in templates]` bzw. `[a.template_id for a in assignments]`), sie kommt nie aus einem Request — es gibt dort keine Schranke abzuleiten. Dieselbe Schema-Suche wie im Server bestätigt das: die drei Treffer des Monitorings sind genau die drei `offset` (`/checks`, `/status`, `/alerts`), kein vierter. `templates.py` entfällt damit aus der Dateiliste. Die Grenze steht wie verlangt lokal in `apps/monitoring/app/core/bounds.py`, nicht als Import aus dem Server.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (intern)

### T10 — Obsolete Ausschlüsse entfernen  [x]
Komponente: server · Dateien: apps/server/tests/schemathesis_exclude.toml, apps/monitoring/tests/schemathesis_exclude.toml, apps/server/app/modules/hooks/schemas.py, apps/server/app/modules/users/schemas.py, apps/server/app/modules/notifications/schemas.py, apps/server/tests/test_text_bounds.py, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @494270f8 2026-09-22T23:12:50+02:00
Review: approve (sonnet, 3 Runden, Mutationsproben)
Änderung: jeden Eintrag, den T2–T9 erledigt haben, entfernen — und den Fuzz-Lauf danach real fahren, um zu sehen, was übrig bleibt. Ein Eintrag, der weiter nötig ist, bekommt eine **neue** Begründung aus diesem Lauf; keiner bleibt mit der alten stehen. `CHANGELOG` unter Unreleased: 422 statt 500 an den Rändern.
Beim Bau (2026-09-22): Der Lauf hat geliefert, wofür er da war. Von 27 Server-Ausschlüssen waren zunächst 12 ganz weg und fünf auf check-granular geschrumpft; **T14 hat acht davon zurückgeholt** (siehe dort). Endstand, gegen `git show main:` nachgezählt: 27 vorher, 25 nachher — sechs entfernt, vier verengt (`list_audit`, `list_hooks`, `list_servers`, `get_connections`), vier hinzugekommen (Monitoring-Proxy). Im Monitoring sind die drei `offset`-Einträge weg, der `tag-sync`-Eintrag bleibt. Dabei kam **ein neuer Produktfehler derselben Klasse** zum Vorschein, den vorher ein Ausschluss verdeckt hatte: ein NUL-Byte im `script` von `POST /api/hooks` (`DataError` beim INSERT, ungefangen). Er ist behoben, nicht ausgeschlossen — `SafeText` auf den Textfeldern von `HookCreate`/`HookUpdate`, plus Test. Zweiter Treffer war `GET /api/audit` mit `negative_data_rejection` (Pydantic-lax-Koerzierung plus die bekannte Header-Blindstelle) — bekanntes Framework-Verhalten, deshalb wieder ein Eintrag, aber check-granular und mit der Begründung aus genau diesem Lauf.
Zweite Runde, im Lauf von `task-close` (dieselbe Suite, andere Sammelreihenfolge): noch **ein** Fund derselben Klasse — ein NUL-Byte in `server_ids` von `POST /api/users` erreichte `Server.id.in_()` und starb im Treiber. Auch behoben (`list[SafeText]`, plus Test); die Feststellung aus T5 bleibt richtig, dort ging es um eine **Zahl**-Schranke, die es für eine `String`-Spalte nicht gibt. Und ein dritter, den ich beim ersten Lesen des Protokolls übersehen hatte (der Review hat ihn gefunden): `POST /api/internal/events` mit NUL in `source_id` — jedes Textfeld eines eingehenden Events wird unverändert in eine `Notification`-Zeile geschrieben, `source_id` zusätzlich gegen `Server.id` verglichen. Alle sieben Textfelder von `IncomingEvent` tragen jetzt `SafeText`, mit Test. Dazu die vier Catch-all-Routen des Monitoring-Proxys (`/api/monitoring/{path}`): sie teilen sich einen prozessweiten httpx-Client, den der Lifespan-Shutdown schließt — wer danach drankommt, stirbt im Transport. alle vier Methoden sind in demselben Lauf einzeln so gefallen, und es ist eine Ursache und kein Routenproblem; `until` zeigt wie beim schon bestehenden Geschwister-Eintrag auf Stufe 8c. Das ist der einzige Ausschluss, den dieses Vorhaben **hinzufügt**.
**Korrektur an der Verify-Zeile:** `run.sh` löst `AH_TEST_DB` nicht auf (das tut nur `verify.sh`, CLAUDE.md §7), die geplante Zeile scheitert auf der Dev-Box also an `Datenbank »adminhelper« existiert nicht`. Verify steht deshalb jetzt in `verify.sh`-Form; der dienstübergreifende Fuzz-Lauf ist separat gefahren und unten belegt.
Verify: bash scripts/dev/verify.sh server --strict
Doku: CHANGELOG
Abhängt von: T2, T3, T4, T5, T6, T7, T8, T9

### T11 — oasdiff-Gate: maximum/minimum am Request-Rand ist ERR  [?] (Gate-Anpassung (oasdiff --severity-levels: die vier request-parameter- und acht request-body/property-Ids auf WARN) als eigenes Harness-Vorhaben vor diesem PR mergen — oder diesen PR anders schneiden? Ohne sie ist er nicht mergebar.)
Dateien: keine in diesem Branch (Harness-Vorhaben, `scripts/dev/openapi-breaking.sh`)
Änderung: keine hier. Befund aus dem Bau, belegt gegen die in CI gepinnte oasdiff-Version v1.32.0: eine neu gesetzte Schranke auf einer Request-Eingabe ist dort ERR, nicht WARN — `checker/rules.go` Z. 272 (`request-parameter-max-set`, `EffectNarrows` + `DirectionRequest` ⇒ ERR), Z. 288 (`request-parameter-min-set`), Z. 381/408 (`request-property-max-set`/`-min-set`). `.github/workflows/ci.yml:611/613` fährt `openapi-breaking.sh`, und das ruft `oasdiff breaking … --fail-on ERR` ohne Severity-Datei (`scripts/dev/openapi-breaking.sh:98`). Damit setzt **jede** Task dieses Vorhabens das Gate rot: T2/T3/T4 über Parameter, T5 über Body-Felder, T9 über die Monitoring-Parameter. Der Check ist Pflicht im Ruleset 23772038 ohne Bypass-Akteure (nachgeprüft von adminhelper-04) — der PR ist damit nicht rot, sondern **nicht mergebar**, bis die Gate-Anpassung auf `main` liegt. Lokal nicht nachfahrbar: `bash scripts/dev/openapi-breaking.sh server --base main` → „oasdiff not installed (75)".
Verify: keine (kein Code in diesem Branch)
Doku: keine (Befund, gehört als eigene Roadmap-Zeile)

### T12 — NUL-Byte: Einzelfeld-Härtung oder Flächenregel?  [?] (NUL-Härtung Feld für Feld weiterlaufen lassen (jeder Fuzz-Fund ein Fix), oder eine Flächenregel über alle Request-Schemas als eigenes Vorhaben schneiden? Der erste Weg hält den Fuzz-Gate dauerhaft in Bewegung, der zweite ist ein Refactor über jedes Schema.)
Dateien: keine in diesem Branch (Entscheidung, danach eigenes Vorhaben)
Änderung: keine hier. Befund aus dem Bau: T7 hat `SafeText` bewusst nur dort gesetzt, wo ein Lauf es belegt hatte (YAGNI, so steht es in der Spec). Der Fuzz-Lauf von T10 hat danach sofort die nächste Stelle gefunden — `POST /api/hooks`, `script` —, und die ist ebenfalls behoben. Das Muster ist damit belegt: **jedes** `str`-Feld, das in eine Postgres-Textspalte fließt, ist ein potenzieller 500er, und der Fuzzer liefert sie einzeln nach, genau so wie die Spec es für die Paginierungsklasse beschrieben hat („liefert CI Ausschlüsse in Raten nach"). Heute ungehärtet sind unter anderem `servers`, `connections`, `ansible`, `frp`, `notifications` und `provisioning`. Zwei Wege: (a) so weiterlaufen und je Fund ein Feld härten, (b) eine Flächenregel — ein gemeinsames Basis-Modell oder ein `model_validator`, der jeden `str` im Body gegen NUL prüft, einmal statt je Feld. (b) ist ein Flächen-Refactor über alle Schemas und damit ausdrücklich etwas, das ein Design-Gate entscheidet, nicht ein Bau.
Belegliste aus dem Abschluss-Review, jede Stelle einzeln nachgestellt (2026-09-23, jeweils ungefangener `psycopg.DataError`, HTTP 500): **Body-Textfelder** — `POST /api/servers` (`name`, `hostname`, `notes`), `POST /api/ansible/playbooks` (`name`, `description`), `POST /api/connections` (`host`, `notes`). **String-Query-Parameter** — `GET /api/frp/tunnels` (`server_id`, `frp_config_id`), `GET /api/frp/generate/frps-toml` und die drei Geschwister in `generate_router.py` (`config_id`). **String-Pfadparameter** — `%00` prozentkodiert erreicht den Wert: `/api/servers/{server_id}`, `/api/hooks/{hook_id}`, `/api/frp/tunnels/{tunnel_id}`, `/api/ansible/playbooks/{playbook_id}`; rund zwanzig solcher Parameter gibt es im Server. Die Routen, die dieses Vorhaben stummgeschaltet zurückgegeben hätte, sind über T14 wieder gedeckt; die übrigen sind Altbestand, den bisher schlicht kein Lauf getroffen hat. Das ist die vollständige Fläche, über die Weg (b) entscheiden müsste.
Verify: keine (kein Code in diesem Branch)
Doku: keine (Befund, gehört als eigene Roadmap-Zeile)

### T13 — Roter Lauf: Ursache gefunden, geteilte Test-DB  [~] (geklärt: parallele Läufe auf derselben Test-DB, kein Produktfehler — Abhilfe liegt als tasks/lane-isolation.md schon bereit)
Dateien: keine in diesem Branch (Beobachtung)
Änderung: keine. Im Abschluss ist `schemathesis` **einmal** rot geworden, und später fiel auch `server pytest` mehrfach mit `psycopg.errors.UndefinedTable: Relation »users« existiert nicht` aus. Ursache gefunden und nachgestellt: `tests/conftest.py` fährt `pg_engine` session-weit und ruft im Teardown `Base.metadata.drop_all()` — **zwei gleichzeitige pytest-Sitzungen auf `$AH_TEST_DB` zerstören sich gegenseitig das Schema**. Genau das ist passiert: der Abschluss-`/code-review` hat als Sub-Agent eigene Suiten gefahren, während hier der Gesamtlauf lief. Gegenprobe, jeweils allein und mit nichts anderem auf der Box: `pytest -q -m "not schemathesis"` → **614 passed, 2 skipped**, sowohl mit als auch ohne Zufallsreihenfolge. Meine erste Vermutung (`pytest-randomly`, das unangemeldet im lokalen venv liegt) war damit **falsch** — die Reihenfolge ist nicht die Ursache, die Gleichzeitigkeit ist es. Kein Produktfehler und nichts, was dieses Vorhaben eingebaut hat. Die Abhilfe liegt bereits als eigenes Kurz-Ledger `tasks/lane-isolation.md` vor (T1 dort: `flock` für die schweren Python-Schritte, mit zwei Belegen vom 2026-09-18 und 2026-09-21); dieser Lauf ist der dritte Beleg.
Verify: keine (kein Code in diesem Branch)
Doku: keine (Beobachtung; gehört zu tasks/lane-isolation.md)

### T14 — Zurückgegebene Routen, die weiter 500 liefern  [x]
Komponente: server · Dateien: apps/server/tests/schemathesis_exclude.toml, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @10f7a2d3 2026-09-23T02:25:42+02:00
Review: approve (sonnet, 2 Runden, Lese-Prüfung)
Änderung: Befund des Abschluss-`/code-review`, von mir einzeln nachgestellt: T10 hat Ausschlüsse anhand ihrer **dokumentierten** Begründung entfernt, nicht anhand der Route. Bei sechs Operationen war die dokumentierte Ursache (Tag-Validator bzw. FK) zwar behoben — die Route stirbt aber weiter an einem NUL-Byte in einem **anderen** Feld, und durch das Entfernen läuft `not_a_server_error` dort jetzt scharf. Einzeln nachgestellt 2026-09-23, alle mit ungefangenem `psycopg.DataError`: `POST /api/servers` (`hostname`, `notes`), `PUT /api/servers/{server_id}` (Pfad), `PUT /api/frp/tunnels/{tunnel_id}` (Pfad), `POST /api/ansible/playbooks` (`name`, `description`), `PUT /api/ansible/playbooks/{playbook_id}` (Pfad), `POST /api/connections` (`host`, `notes`) und `GET /api/frp/tunnels` (`server_id` als Query). Der Review zu dieser Task hat eine **achte** gefunden, die ich übersehen hatte, und eine falsche Angabe korrigiert: `POST /api/frp/tunnels` stirbt an `server_id`, `frp_config_id` und `protocol` (alle roh aus dem Body in einen Vergleich bzw. in eine `Column(String)`), und bei `POST /api/servers` ist **nicht** `name` betroffen — das trägt über `_validate_server_name` schon eine Steuerzeichen-Prüfung und antwortet mit 422 — sondern `hostname`. Beides nachgestellt. Die acht bekommen ihren Eintrag zurück, mit der Begründung aus diesem Lauf statt der alten — das ist ehrlicher als ein Deckel, den niemand geprüft hat, und ehrlicher als ein grüner PR, der sechs 500er freilegt. Den Klassenfix entscheidet T12; hier wird nichts geraten und nichts stillgelegt, was behoben ist.
Verify: bash scripts/dev/verify.sh server --strict
Doku: CHANGELOG (die Zahl der entfernten Ausschlüsse stimmt sonst nicht mehr)
