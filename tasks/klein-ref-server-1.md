<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-1 — Task-Ledger
Status: erledigt · Branch: feature/klein-ref-server-1 · Review: pro Task
Spec: docs/features/klein-ref-server-1.md (Roadmap R-0838, R-0895, R-0906, R-0940, R-0941)
Heavy: none — Log-Formatierung, OpenAPI-Beschreibung und Doku im Server, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Request-Pfad in Warn-Logs escapen (R-0906)  [x]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/app/core/identity.py, apps/server/tests/test_log_request_path.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @a49c3de5 2026-10-29T18:19:57+01:00
Review: approve (.ah-out/review/klein-ref-server-1/T1.verdict.json)
Änderung: Alle `logger.*`-Aufrufe mit `request.url.path` (`middleware.py` IPFilter, `identity.py` fünf Warnungen und eine Debug-Zeile) schreiben den Pfad mit `%r`. Neue Testdatei (SPDX-Header): ein Pfad mit `%0A` und ESC-Zeichen erzeugt eine einzeilige Logmeldung ohne rohes Steuerzeichen, für den IP-Filter und `_deny_refused`.
Beweis: Code-Lesung origin/main apps/server/app/core/middleware.py:238, identity.py:134,220,240,295,327,336
Dedup-Key: ref:server:logs:decoded-request-path
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_log_request_path.py tests/test_nul_middleware.py tests/test_identity_source.py tests/test_mtls_scope.py
Doku: keine (nur Log-Formatierung)

### T2 — Redis-Logs: nur Fehlertyp, englisch (R-0940, R-0941)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/stream_hub.py, apps/server/app/core/rate_limit.py, apps/server/tests/test_stream_reconnect.py, apps/server/tests/test_rate_limit.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b2a0db3c 2026-10-29T18:21:52+01:00
Review: approve (.ah-out/review/klein-ref-server-1/T2.verdict.json)
Änderung: `stream_hub.py` (publish, `_await_subscribed`, `_reader`) loggt ohne `exc_info` den Fehlertyp (`type(e).__name__`) in englischem Text; `get_backend()` meldet englisch wie die übrigen Warnungen. Tests: `caplog` zeigt Typ, kein `exc_info`, keine Verbindungsdaten.
Beweis: Code-Lesung origin/main stream_hub.py:97,113,136-157; rate_limit.py:174,178,181
Dedup-Key: ref:server:stream_hub.py:log-exc-info
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_stream_reconnect.py tests/test_rate_limit.py
Doku: keine (nur Log-Text)

### T3 — FRP: abgelehnter Tunnel warnt einmal, Wortlaut getestet, Servername-strip dokumentiert (R-0895)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_config_generator.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6a3ba9ad 2026-10-29T18:27:16+01:00
Review: approve (.ah-out/review/klein-ref-server-1/T3.verdict.json)
Änderung: `without_refused_extra_config` loggt die Warnung einmal je `(tunnel.id, abgelehnte Schlüssel)` (Cache begrenzt); Tests: zweiter Aufruf loggt nicht, geänderte Schlüssel loggen erneut, `plugin keys` erscheint für reine Plugin-Schlüssel, sonst `entries the API refuses`. api-reference DE+EN: ein Satz, dass `name` am Server vor der Prüfung mit `strip()` gekürzt wird.
Beweis: Code-Lesung origin/main config_generator.py:139-163, docs/developer/api-reference.html:101
Dedup-Key: ref:server:config_generator.py:refused-warning-per-poll
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_config.py
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html

### T4 — OpenAPI: Fehlercodes der Hook-Trigger-Routen (R-0838)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_hooks.py, changelog.d/klein-ref-server-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c03e9867 2026-10-29T18:31:48+01:00
Review: approve (.ah-out/review/klein-ref-server-1/T4.verdict.json)
Änderung: `responses=` an `POST /api/hooks/trigger` (401, 403, 404, 429) und `/trigger/{token}` (403, 404, 429); der Docstring bleibt unberührt (er wäre die OpenAPI-Beschreibung). Snapshot per `--update-openapi-snapshot` neu; ein Test pinnt die deklarierten Codes. Dazu das CHANGELOG-Fragment (`### Changed`, umlautfrei) für alle vier Tasks. 413 setzt das Gateway, nicht die App, und fehlt daher.
Beweis: Code-Lesung origin/main hooks/router.py:255-272, _do_trigger 196-215
Dedup-Key: ref:server:hooks:trigger-openapi-errors
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py tests/test_hooks.py
Doku: changelog.d/klein-ref-server-1.md

### T5 — Test-Isolation der FRP-Warnung (Folge aus T3, R-0895)  [x]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/test_config_generator.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9779b25a 2026-10-29T19:03:06+01:00
Review: approve (.ah-out/review/klein-ref-server-1/T5.verdict.json)
Änderung: Die PR-CI zeigte vier rote Tests in `test_frp_input_hardening.py`: die Warnung kommt jetzt einmal je Prozess, die Tests erwarten sie je Test. Der Reset von `_refused_warned` wandert als autouse-Fixture in die `conftest.py` (wie das Rate-Limit-Backend) und gilt für alle Tests; der lokale Fixture in `test_config_generator.py` entfällt.
Beweis: PR #312, Lauf 40923264643, Job "Server (pytest, image lock)": 4 failed in tests/test_frp_input_hardening.py
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_input_hardening.py tests/test_frp_config.py
Doku: keine (Test-Isolation)

## Entscheidungen
- T5: T3 verifizierte nur zwei Testdateien; der Dedup-Cache ist prozessglobal, daher Reset für die ganze Suite in conftest.py. Künftig bei einer Änderung an geteiltem Zustand alle Testdateien des Moduls (grep) ins Verify.
