<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Hooks: Worker-Start, Antwortzeit, Cron-Zeitzone, Webhook-Body, CLI-Passwort — Task-Ledger
Status: erledigt · Branch: feature/hooks-hardening · Review: pro Task
Spec: docs/features/hooks-hardening.md (Roadmap R-0778, R-0756; T1, T4, T5 gehören zum Paket, Härtung, Kevin 2026-10-22)
Heavy: linux-full — Server-API-Verhalten: `POST /api/hooks/trigger` antwortet auf einen Body mit NUL-Byte oder einzelnem Surrogat mit 422 (T4), Hook-Läufe enden früher (T2), der Scheduler-Dienst rechnet Cron in UTC (T3); läuft im Sammellauf. Routen, Schemas und OpenAPI bleiben, keine Migration; kein Gateway-, PKI-, FRP-, Compose- oder Install-Pfad (`scripts/install.sh:297-300` nutzt `--password-stdin`, T5 ändert nur `--password`), kein Cross-Host-Datenpfad: kein `scenario`, kein `windows`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Der Hook-Worker lädt keine User-Site. (2) Ein Hook-Lauf endet beim Default deutlich unter 60 s, auch wenn
ein Hintergrundprozess die Ausgabe offen hält. (3) Cron-Hooks rechnen in UTC, `next_run` ist UTC. (4) Der Body des
Webhook-Triggers folgt der Regel aller Request-Bodies (kein NUL-Byte, kein einzelnes Surrogat). (5)
`create-admin --password` legt den Benutzer in einem Prozess an, dessen Kommandozeile das Passwort nicht trägt.
Zeilenangaben: origin/main@53a7dbc5; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 vor T2 (dieselben Dateien). T3 ist unabhängig. T4 erst, wenn `feature/server-hardening` auf `main`
  ist (`_find_unstorable` in `apps/server/app/core/bounds.py`); T5 erst, wenn `feature/audit-coverage` (PR #268) auf
  `main` ist (`fire_event("user.created", …)` in `create_admin`). Vor T4 bzw. T5 `origin/main` in den Branch mergen
  und die Zeilen neu greppen.
- `feature/server-fixes` ändert `scheduler.py` (`add_hook`), `hooks/router.py` (`update_hook`),
  `docs/developer/api-reference.html`, `server.html`, `hooks.html` und `CHANGELOG.md`; wer später merged, holt
  `origin/main` herein.
- Neue Code-Strings (Fehlertexte, Hilfetexte, Kommentare) englisch; bestehende deutsche Texte bleiben.
- Neue Testdateien mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`).
- Tests, die einen Hook-Lauf mit Hintergrundprozess starten, beenden diesen Prozess im `finally` (PID über eine Datei
  unter `tmp_path`, die das Skript schreibt); kein `sleep` überlebt den Test.
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737.

### T1 — Hook-Worker startet ohne User-Site  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hook_isolation.py, docs/developer/hooks.html, docs/en/developer/hooks.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7477f9cb 2026-10-23T06:36:13+02:00
Review: approve (.ah-out/review/hooks-hardening/T1.verdict.json)
Änderung: Der Worker startet mit `[sys.executable, "-s", _WORKER_SCRIPT]` (`script_runner.py:150-159`), und `worker_env` (`:113-120`) bekommt `"PYTHONNOUSERSITE": "1"`, damit auch Python-Prozesse, die ein Skript startet, die User-Site weglassen. Kommentar fürs Warum an der Popen-Zeile: der `HOME`-Rückfall (`:115`) ist `/tmp`, und ein Python ohne venv nähme `$HOME/.local/…/site-packages` samt `usercustomize`; `-I`/`-E` gehen nicht, weil der Worker `PYTHONPATH` braucht (`:117`). `HOME`, `LANG`, `PYTHONPATH`, die Proxy-Weitergabe und alles andere bleiben. Tests in `test_hook_isolation.py` mit `_worker_env` (`:31-37`) bzw. `run_hook_script`: (a) ein Skript loggt `sys.flags.no_user_site` → `1`; (b) `_worker_env("PYTHONNOUSERSITE")` → `{"PYTHONNOUSERSITE": "1"}`; (c) wie (a) mit `_unset_server_env(monkeypatch, "HOME")` (der Rückfall-Fall). Zuerst rot: (a) und (b) auf HEAD (im venv ist `site.ENABLE_USER_SITE` immer `False`, deshalb prüft der Test das Flag, nicht das Laden). Die bestehenden Env-Tests (`:137-182`) bleiben grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py
Doku: docs/developer/hooks.html:85 + docs/en/developer/hooks.html:85 (Liste des Env um `PYTHONNOUSERSITE=1` ergänzen; der Worker startet mit `-s`, ohne User-Site) · CHANGELOG.md (Changed, umlautfrei: der Hook-Worker startet mit `-s` und `PYTHONNOUSERSITE=1` und laedt keine Python-Pakete aus dem Benutzerverzeichnis; Pakete fuer Hooks gehoeren ins Image)
Beweis: Code-Lesung apps/server/app/modules/hooks/script_runner.py:150-159
Orakel: contract — der Worker und seine Python-Kindprozesse laufen mit `sys.flags.no_user_site == 1`
HEAD: 53a7dbc5

### T2 — Hook-Lauf endet unter dem Lese-Timeout des Gateways (R-0778)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hook_isolation.py, docs/developer/hooks.html, docs/en/developer/hooks.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @75690d71 2026-10-23T06:54:09+02:00
Review: approve (.ah-out/review/hooks-hardening/T2.verdict.json)
Abhängt von: T1
Änderung: Neue Konstante `_READER_GRACE_SECONDS = 2` neben `SCRIPT_TIMEOUT_SECONDS` (`script_runner.py:60`). Nach `proc.wait` warten die beiden Lese-Threads zusammen höchstens diese Frist (eine Deadline über `time.monotonic()` für `t_out.join` und `t_err.join`, `:217-218`) statt je `timeout`; lebt danach einer, `killpg` wie heute (`:219-224`) und noch einmal höchstens dieselbe Frist für beide zusammen (`:229-230`). Der Kommentar `:211-216` und `:225-228` nennt die Obergrenze `timeout + 2 × _READER_GRACE_SECONDS` und das Warum: das Gateway schließt `/api/…` nach 60 s ohne Antwort (nginx-Default `proxy_read_timeout 60s`, `apps/gateway/nginx.conf:121-123` setzt keinen eigenen). Der Timeout-Zweig (`:198-208`), die Texte und `SCRIPT_TIMEOUT_SECONDS` bleiben. Tests in `test_hook_isolation.py` neben `test_hook_backgrounded_grandchild_does_not_hang_parent` (`:119-134`): (a) Skript startet `sleep 40` mit `start_new_session=True` und geerbtem stdout, schreibt die PID nach `tmp_path`, `timeout=5` → `elapsed < 10`; (b) dasselbe ohne eigene Session → `elapsed < 8` und `success` wie heute `True` mit `result` des Skripts; (c) `SCRIPT_TIMEOUT_SECONDS + 2 * _READER_GRACE_SECONDS < 60` mit dem Grund im Kommentar. Zuerst rot: (a) und (b) auf HEAD (Probe: Lauf + `4 × timeout` bzw. `2 × timeout`); (c) fehlt auf HEAD die Konstante. `tests/test_hooks.py::TestHookWorkerRobustness::test_timeout_kills_grandchildren` (`:545-566`) bleibt grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py tests/test_hooks.py::TestHookWorkerRobustness
Doku: docs/developer/hooks.html:87 + docs/en/developer/hooks.html:87 (nach dem Satz zur Prozessgruppe: nach dem Ende des Workers wartet der Runner höchstens 2 s auf den Rest der Ausgabe; hält ein Kindprozess stdout oder stderr länger offen, killt er die Gruppe und wartet noch einmal höchstens 2 s; ein Lauf dauert so höchstens 34 s) · CHANGELOG.md (Fixed, umlautfrei: startete ein Hook einen Hintergrundprozess, der stdout oder stderr erbte, kam die Antwort von `/api/hooks/trigger` und `/api/hooks/{id}/run` erst nach mehr als 60 s, am Gateway als 504; jetzt nach hoechstens 34 s)
Beweis: origin/main@53a7dbc5 · Probe (Dev-Venv, `DATABASE_URL` auf `192.0.2.1:1`, `run_hook_script(…, timeout=3)`, Skript startet `sleep 40` mit geerbtem stdout): mit `start_new_session=True` `elapsed=13.7s`, `13.7s`, `13.7s`, `error='Ungueltige Worker-Ausgabe'`; ohne `elapsed=7.7s`, `7.8s`, `7.8s`, `success=True`
Orakel: contract — ein Lauf dauert höchstens `timeout + 2 × _READER_GRACE_SECONDS` plus Start des Workers
Dedup-Key: bug:server:hooks/script_runner.py:worst-case-exceeds-gateway
HEAD: 53a7dbc5
Semantik: `docs/developer/hooks.html:34` — „registrierte Scripts laufen in einer sanitisierten Subprozess-Umgebung mit harter Timeout-Grenze.“; `:87` — „<strong>Timeout</strong>: Default 30&nbsp;s.“

### T3 — Cron-Hooks rechnen in UTC, `next_run` in UTC (R-0756)  [x]
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c594ef77 2026-10-23T07:05:32+02:00
Review: approve (.ah-out/review/hooks-hardening/T3.verdict.json)
Entscheidung: Kevin 2026-10-22 (Q14, AskUserQuestion in der Session): (a) UTC wie dokumentiert, CHANGELOG-Hinweis zur Verschiebung bestehender Hooks.
Komponente: server · Dateien: apps/server/app/modules/hooks/scheduler.py, apps/server/tests/test_scheduler_timezone.py, docs/developer/server.html, docs/en/developer/server.html, CHANGELOG.md
Änderung: `_parse_trigger` (`scheduler.py:91-101`) baut den Cron-Trigger mit `CronTrigger.from_crontab(…, timezone=timezone.utc)` (`:98`); Kommentar fürs Warum: ein Trigger-Objekt ohne `timezone` nimmt `tzlocal.get_localzone()` (`TZ`), nicht `timezone="UTC"` des Schedulers (`:23-30`), und die Doku verspricht UTC. Der Intervall-Trigger (`:94`) bleibt (absolute Zeit). `_execute_scheduled_hook` (`:125-126`) und `get_next_run` (`:162-167`) schreiben `next_run` als `job.next_run_time.astimezone(timezone.utc).replace(tzinfo=None)` (naiv UTC, Konvention `apps/server/app/core/time.py:8-17`), eine kleine Hilfsfunktion für beide Stellen ist erlaubt. Neue Testdatei `apps/server/tests/test_scheduler_timezone.py` (SPDX) mit dem Muster `_clean_scheduler` aus `tests/test_scheduler_reconcile.py:36-45`; `get_localzone` in `apscheduler.triggers.cron` und `apscheduler.triggers.interval` per `monkeypatch` auf `ZoneInfo("Europe/Berlin")`: (a) `_parse_trigger("0 9 * * *").get_next_fire_time(None, 2026-07-01T00:00Z)` → `2026-07-01T09:00Z`, ebenso am 2026-01-15 → `09:00Z`; (b) `_parse_trigger("0 9 * * 1-5")` mit Wochentag-Übersetzung → nächster Lauf an einem Montag `09:00Z`; (c) `add_hook("tz-int", "1h")`, `get_next_run("tz-int")` liegt höchstens eine Minute neben `utcnow_naive() + 1h`; (d) wie (c) mit `"0 9 * * *"` → `get_next_run` hat `hour == 9`. Zuerst rot: (a), (c), (d) auf HEAD (07:00 bzw. 08:00 UTC; `next_run` zwei Stunden daneben). `tests/test_scheduler_cron.py` und `tests/test_scheduler_reconcile.py` bleiben grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_scheduler_timezone.py tests/test_scheduler_cron.py tests/test_scheduler_reconcile.py
Doku: docs/developer/server.html:161 + docs/en/developer/server.html:161 (nach „oder Cron (5 Felder)“: Cron-Ausdrücke gelten in UTC, unabhängig von `TZ`) · CHANGELOG.md (Fixed, umlautfrei: Cron-Ausdruecke von Schedule-Hooks gelten in UTC, wie in der Betriebsdoku beschrieben; bisher galt `TZ` des Containers (Voreinstellung Europe/Berlin). Bestehende Cron-Hooks laufen dort nach dem Update 1 h (Winter) bzw. 2 h (Sommer) spaeter als bisher; `next_run` zeigte bei `TZ` ungleich UTC die Ortszeit als UTC, auch bei Intervall-Hooks)
Beweis: origin/main@53a7dbc5 · Probe (APScheduler 3.11.3 aus dem Dev-Venv, gepinnt 3.11.2; `python -I` im Scratch): `CronTrigger.from_crontab("0 9 * * *").get_next_fire_time(None, 2026-07-01T00:00Z)` mit `TZ=Europe/Berlin` → `2026-07-01T09:00:00+02:00`, naiv `09:00`, UTC `07:00`; mit `TZ=UTC` → `09:00+00:00`; `IntervalTrigger(hours=1)` mit `TZ=Europe/Berlin` → Trigger-Zeitzone `Europe/Berlin`, naiv zwei Stunden nach dem UTC-Wert; je dreimal identisch
Orakel: contract — ein Cron-Ausdruck feuert zur UTC-Zeit, die er nennt; `next_run` ist der nächste Lauf in naivem UTC
Dedup-Key: bug:server:hooks/scheduler.py:cron-trigger-timezone
HEAD: 53a7dbc5
Semantik: `docs/admin/betrieb.html:170` — „Die API gibt Zeitstempel davon unabhängig in UTC mit <code>Z</code> aus (Web und Desktop zeigen sie in der Ortszeit des Browsers bzw. Rechners), und geplante Hooks rechnen in UTC.“ (EN `docs/en/admin/operations.html:128`)

### T4 — Webhook-Trigger: NUL-Byte oder einzelnes Surrogat im JSON-Body ergibt 422  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/test_hooks_webhook_payload.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f2464810 2026-10-23T12:00:46+02:00
Review: approve (.ah-out/review/hooks-hardening/T4.verdict.json)
Änderung: Erst nach dem Merge von `feature/server-hardening`. In `_do_trigger` (`router.py:185-225`) nach dem Lesen des Payloads (`:201-204`, der Rückfall `{}` bei ungültigem JSON bleibt) und vor `run_hook_script`: `found = _find_unstorable(payload)` aus `app.core.bounds`; ist etwas gefunden, `raise RequestValidationError([{"type": "value_error", "loc": ("body", *loc), "msg": f"Value error, {reason}", "input": value}])` — dieselbe Regel und dieselbe Form wie `RequestModel`. Der 422-Handler (`apps/server/app/main.py:409-421`) schreibt ein Surrogat escaped zurück. Reihenfolge bleibt: Ratelimit, Token (404), aktiv (403), dann Body. Kein Docstring, keine Signatur und kein `responses=` einer Route ändert sich. Neue Testdatei `apps/server/tests/test_hooks_webhook_payload.py` (SPDX) mit den Helfern aus `tests/test_hooks_webhook_dos.py:16-29` (kopiert, `reset_backend_for_tests()` je Test), Skript `result['echo'] = payload`, Body als rohes `content=` mit `Content-Type: application/json`: (a) `{"a": "\ud800"}` (JSON-Escape) → 422, `loc == ["body", "a"]`; (b) `{"items": ["ok", "x\u0000y"]}` → 422, `loc == ["body", "items", 1]`; (c) Surrogat in einem Schlüssel → 422; (d) ein JSON-String auf oberster Ebene mit Surrogat → 422, `loc == ["body"]`; (e) über `/trigger` mit `X-Hook-Token` wie (a); (f) `{"gruss": "Grüße"}` → 200, Echo gleich; (g) ungültiges JSON → 200 mit `payload == {}` wie heute. Zuerst rot: (a)–(e) auf HEAD (500 bzw. 200).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_webhook_payload.py tests/test_hooks_webhook_dos.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html:122 + docs/en/developer/api-reference.html:122 (ein NUL-Byte oder ein einzelnes Surrogat (U+D800 bis U+DFFF) in einem String oder Schlüssel des JSON-Bodys → `422` mit dem Ort im `loc`, das Skript läuft nicht) · CHANGELOG.md (Changed, umlautfrei: der Webhook-Trigger prueft seinen JSON-Body wie jeder andere Request-Body und antwortet auf ein NUL-Byte oder ein einzelnes Surrogat mit 422, statt das Skript damit zu starten)
Beweis: Code-Lesung apps/server/app/modules/hooks/router.py:201-204
Orakel: contract — kein String im `payload` eines Hooks trägt ein NUL-Byte oder ein einzelnes Surrogat
HEAD: 53a7dbc5

### T5 — CLI: `create-admin --password` legt den Benutzer in einem frischen Prozess an  [x]
Komponente: server · Dateien: apps/server/app/cli.py, apps/server/tests/test_cli.py, README.md, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @45e63675 2026-10-23T12:21:49+02:00
Review: approve (.ah-out/review/hooks-hardening/T5.verdict.json)
Änderung: Erst nach dem Merge von `feature/audit-coverage`. In `main` (`cli.py:119-184`), Zweig `create-admin` (`:159-166`), vor `SessionLocal()`: kommt das Passwort aus `--password` und ist `argv is None` (echter Aufruf, nicht `main([...])` im Prozess), ruft `main` eine neue Funktion, die (1) ein Passwort mit `\n` per `parser.error` ablehnt (`--password-stdin` liest nur eine Zeile, `:160-161`), (2) `os.pipe()` öffnet, `os.fsencode(password) + b"\n"` schreibt, wenn es in die Pipe passt (`fcntl.fcntl(w, fcntl.F_GETPIPE_SZ)`), sonst per `parser.error` ablehnt, (3) das Schreibende schließt, das Leseende per `os.dup2` auf fd 0 legt und (4) `os.execv(sys.executable, [sys.executable, "-m", "app.cli", "create-admin", "--username", <username>, "--password-stdin"])` aufruft. Fehlertexte englisch. Docstring der Funktion mit dem Warum: `create_admin` feuert `user.created`, die Event-Hooks laufen im Prozess der CLI und seinen Kindprozessen. Die Hilfe von `--password` (`:125-129`) sagt, dass die CLI das Passwort vor dem Anlegen über stdin an einen frischen Prozess gibt, und empfiehlt weiter `--password-stdin`; das Beispiel im Modul-Docstring (`:7`) zeigt `--password-stdin`. `reset-admin` bleibt. Tests am Ende von `test_cli.py` (nach den Tests von `feature/audit-coverage`), mit `_FakeDB` (`:66-68`), `monkeypatch` auf `sys.argv`, `cli.os.execv` (Recorder, der eine eigene Exception wirft), `cli.os.dup2` (Recorder, der das Leseende behält statt fd 0 zu ersetzen) und `cli.create_admin` (schlägt fehl, wenn gerufen): (a) `main()` mit `--password arg-secret` → `execv` mit genau der Liste oben, `arg-secret` in keinem Argument, aus dem Leseende kommt `b"arg-secret\n"`, `create_admin` nicht gerufen; (b) Rundlauf: `main(<Argumente aus (a) ab "create-admin">)` mit `sys.stdin` aus dem gelesenen Inhalt → `create_admin` bekommt `arg-secret`; (c) `--password "a\nb"` → `SystemExit`, kein `execv`; (d) ein Passwort größer als die Pipe → `SystemExit`, kein `execv`. Zuerst rot: (a), (c), (d) auf HEAD. `test_main_create_admin_still_accepts_password_arg` (`:84-89`) und die Event-Tests von `feature/audit-coverage` bleiben grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cli.py
Doku: README.md:205 (Beispiel mit `--password-stdin` und `docker compose exec -T`, Passwort per `printf '%s\n'` aus einer Shell-Variablen wie `scripts/install.sh:299`) · CHANGELOG.md (Changed, umlautfrei: `create-admin --password` gibt das Passwort vor dem Anlegen ueber stdin an einen frischen Prozess weiter; Hooks auf `user.created` laufen in einem Prozess, dessen Kommandozeile das Passwort nicht traegt. Empfohlen bleibt `--password-stdin`)
Beweis: Code-Lesung apps/server/app/cli.py:159-166
Orakel: contract — nach dem Anlegen läuft kein Code der CLI in einem Prozess mit dem Passwort in der Kommandozeile
HEAD: 53a7dbc5
