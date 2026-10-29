<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Hooks: Worker-Start, Antwortzeit, Cron-Zeitzone, Webhook-Body, CLI-Passwort

Stand des Codes: `origin/main@53a7dbc5`. Alle `datei:zeile` beziehen sich auf diesen Stand, außer wo ein anderer
Branch genannt ist. Ledger: `tasks/hooks-hardening.md`. Roadmap R-0778 (T2), R-0756 (T3); T1, T4 und T5 gehören zum
Paket (Härtung, Kevin 2026-10-22).

## Problem / Motivation

1. **Der Hook-Worker nimmt die User-Site mit (T1).** `run_hook_script` startet den Worker mit
   `[sys.executable, _WORKER_SCRIPT]` (`apps/server/app/modules/hooks/script_runner.py:150-159`), also ohne `-s`, und
   setzt `HOME` auf den Wert des Servers oder, fehlt er, auf `/tmp` (`:115`). Ein Python ohne venv, wie im Image
   (`Dockerfile:14`, `:32`: `python:3.12-slim`, `pip install` ins System), legt dann
   `$HOME/.local/lib/python3.X/site-packages` auf `sys.path` und führt dort ein `usercustomize` aus; mit dem Rückfall
   liegt das unter `/tmp`. Probe (Python 3.13 des Hosts, dreimal identisch): `HOME=/tmp python3 -c "import site;
   print(site.ENABLE_USER_SITE, site.getusersitepackages())"` → `True /tmp/.local/lib/python3.13/site-packages`; mit
   `-s` → `False`. Gewollt: der Worker lädt den Code des Images und das Hook-Skript, sonst nichts.

2. **Antwortzeit über dem Lese-Timeout des Gateways (T2, R-0778).** Nach `proc.wait(timeout)` (`script_runner.py:197`)
   wartet der Runner auf die beiden Lese-Threads je bis `timeout` (`:217-218`), killt bei Bedarf die Prozessgruppe und
   wartet noch einmal je bis `timeout` (`:219-230`). Hält ein Hintergrundprozess, den das Skript gestartet hat, stdout
   oder stderr offen, dauert ein Lauf so Laufzeit des Workers plus `2 × timeout`, öffnet der Prozess eine eigene
   Session, plus `4 × timeout`. Probe (`origin/main@53a7dbc5`, Dev-Venv, `run_hook_script(…, timeout=3)`, Skript
   startet `sleep 40` mit geerbtem stdout, dreimal identisch): in derselben Prozessgruppe 7,7–7,8 s,
   `success: true`; mit `start_new_session=True` 13,7–13,8 s, `error: "Ungueltige Worker-Ausgabe"`. Beim Default von
   30 s (`:60`) sind das über 60 s bzw. über 120 s. Das Gateway reicht `/api/…` ohne eigenes `proxy_read_timeout`
   weiter (`apps/gateway/nginx.conf:121-123`; nur der SSE-Stream setzt `1h`, `:114`); nginx schließt die Verbindung
   nach 60 s ohne Antwort (Default, siehe Externe Integrationen). `POST /api/hooks/trigger` und
   `POST /api/hooks/{id}/run` enden dann mit 504 statt mit dem Ergebnis, obwohl das Skript selbst längst fertig war.

3. **Cron-Hooks laufen in der Zeitzone des Containers (T3, R-0756).** `_parse_trigger`
   (`apps/server/app/modules/hooks/scheduler.py:91-101`) baut `CronTrigger.from_crontab(…)` (`:98`) und
   `IntervalTrigger(…)` (`:94`) ohne `timezone`. APScheduler 3.x nimmt dann `tzlocal.get_localzone()`, also `TZ`,
   nicht die Zeitzone des Schedulers (`timezone="UTC"`, `:23-30`); die gilt nur für Trigger, die der Scheduler aus
   einem Alias selbst baut. Compose setzt `TZ=${TZ:-Europe/Berlin}` für alle Dienste, auch den Scheduler
   (`docker-compose.yml:141`). Probe (APScheduler 3.11.3 im Dev-Venv, gepinnt 3.11.2, dreimal identisch):
   `CronTrigger.from_crontab("0 9 * * *").get_next_fire_time(None, 2026-07-01T00:00Z)` → mit `TZ=Europe/Berlin`
   `09:00+02:00` (07:00 UTC), mit `TZ=UTC` `09:00+00:00`. Dazu schreibt der Scheduler `next_run` als
   `job.next_run_time.replace(tzinfo=None)` (`:126`, `:166`): das wirft den Offset weg, ohne nach UTC umzurechnen.
   Gespeichert ist so die Ortszeit, die API gibt sie als UTC mit `Z` aus (`apps/server/app/core/time.py:47-55`).
   Probe wie oben: mit `TZ=Europe/Berlin` ist `next_run` eines Cron-Hooks `09:00` (gelaufen wird um 07:00 UTC), der
   eines Intervall-Hooks liegt zwei Stunden hinter dem echten nächsten Lauf. Die Doku legt UTC fest:
   `docs/admin/betrieb.html:170` — „Die API gibt Zeitstempel davon unabhängig in UTC mit <code>Z</code> aus […], und
   geplante Hooks rechnen in UTC.“ (EN `docs/en/admin/operations.html:128` — „and scheduled hooks run on UTC.“)

4. **Der Body des Webhook-Triggers läuft an der Body-Prüfung vorbei (T4).** `_do_trigger` liest den Body mit
   `await request.json()` (`apps/server/app/modules/hooks/router.py:201-204`) und gibt ihn als `payload` an das
   Skript (`:210-221`). Jedes Request-Schema lehnt einen String mit NUL-Byte ab (`RequestModel`,
   `apps/server/app/core/bounds.py:72-111`), nach `feature/server-hardening` T5 auch ein einzelnes Surrogat
   (U+D800 bis U+DFFF, `_find_unstorable`). Der Trigger hat kein Schema. Probe (Starlette aus dem Dev-Venv, dreimal
   identisch): `json.loads('{"a": "\\ud800"}')` liefert ein einzelnes Surrogat; über den Weg Runner → Worker →
   Runner (`json.dumps`/`json.loads` wie `script_runner.py:97-103` und `apps/server/app/modules/hooks/script_worker.py:198`) bleibt es erhalten,
   und `JSONResponse` mit diesem Wert wirft `UnicodeEncodeError`. Gibt das Skript den Payload zurück, ist die Antwort
   500; speichert es ihn, scheitert der Lauf an der Datenbank.

5. **`create-admin --password` und Event-Hooks (T5).** Auf `feature/audit-coverage` (PR #268, T7) feuert
   `create_admin` nach dem Commit `user.created` (`apps/server/app/cli.py`, nach `db.commit()` in `create_admin`);
   der Executor der Event-Hooks wird beim Beenden des Interpreters abgewartet, die Event-Hooks laufen also im
   CLI-Prozess bzw. als seine Kindprozesse. Bei `--password` steht das Passwort in der Kommandozeile dieses Prozesses
   (`cli.py:125-129`: „INSECURE: visible in the process argv (/proc/<pid>/cmdline) for the duration of the call —
   prefer --password-stdin.“), solange er läuft. Gewollt: Code, der beim Anlegen läuft, sieht das Passwort nicht.
   `scripts/install.sh:297-300` nutzt schon `--password-stdin`; das README zeigt `--password` (`README.md:205`).

## Ziel & Nicht-Ziele

Ziel:
- T1: Der Worker startet mit `-s` und bekommt `PYTHONNOUSERSITE=1`; er und Python-Prozesse, die ein Skript startet,
  laden keine User-Site. `HOME` und sein Rückfall bleiben.
- T2: Ein Lauf endet spätestens `timeout` plus zwei kurze Wartefristen für die Ausgabe nach dem Ende des Workers;
  beim Default deutlich unter 60 s. `SCRIPT_TIMEOUT_SECONDS` (30 s), die Texte und die Felder der Antwort bleiben.
- T3: Cron-Ausdrücke gelten in UTC, unabhängig von `TZ`; `next_run` ist der echte nächste Lauf in UTC, auch für
  Intervall-Hooks.
- T4: Ein String oder Schlüssel mit NUL-Byte oder einzelnem Surrogat irgendwo im JSON-Body des Triggers ergibt 422 im
  Format von FastAPI, mit dem Ort im `loc`; das Skript läuft dann nicht.
- T5: `create-admin --password` gibt das Passwort über stdin an einen frischen Prozess weiter, bevor es den Benutzer
  anlegt; die Option bleibt, ihr Verhalten nach außen auch.

Nicht-Ziele (YAGNI):
- Kein `-I`/`-E` für den Worker: er braucht `PYTHONPATH` (`script_runner.py:117`), `-E` ignorierte es.
- Kein anderer `HOME`-Rückfall (offene Frage 1); die Doku nennt `/tmp` (`docs/developer/hooks.html:85`).
- Kein anderer Hook-Timeout und keine Einstellung dafür; das Gateway bleibt, wie es ist.
- Keine Änderung an Intervall-Triggern der System-Jobs (`scheduler.py:248-254`, `:283-289`): ein Intervall läuft in
  absoluter Zeit, die Zeitzone ändert dort nichts.
- Keine Prüfung des Ergebnisses, das ein Skript selbst erzeugt (ein Skript, das von sich aus ein Surrogat
  zurückgibt), und keine Prüfung von `NaN`/`Infinity` im Body (Kandidat, siehe Offene Fragen 3).
- Kein 422 im OpenAPI-Schema von `POST /api/hooks/trigger`: die Route dokumentiert dort auch 401, 403, 404 und 429
  nicht (`apps/server/tests/openapi.snapshot.json`); die API-Referenz nennt den Fall.
- `reset-admin --password` bleibt, wie es ist: `reset_admin` feuert kein Event (`cli.py:72-98`, auch auf
  `feature/audit-coverage`), dort läuft kein Hook. `--password` bleibt erhalten (Test
  `apps/server/tests/test_cli.py:84-89`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/modules/hooks/script_runner.py`, `apps/server/tests/test_hook_isolation.py`, `docs/developer/hooks.html`, `docs/en/developer/hooks.html`, `CHANGELOG.md` |
| T2 | server | `apps/server/app/modules/hooks/script_runner.py`, `apps/server/tests/test_hook_isolation.py`, `docs/developer/hooks.html`, `docs/en/developer/hooks.html`, `CHANGELOG.md` |
| T3 | server | `apps/server/app/modules/hooks/scheduler.py`, `apps/server/tests/test_scheduler_timezone.py` (neu), `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |
| T4 | server | `apps/server/app/modules/hooks/router.py`, `apps/server/tests/test_hooks_webhook_payload.py` (neu), `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T5 | server | `apps/server/app/cli.py`, `apps/server/tests/test_cli.py`, `README.md`, `CHANGELOG.md` |

Keine Datei steht auf `scripts/dev/review-risk.txt`.

Geteilte Dateien mit anderen Vorhaben und Reihenfolge der Merges:
- `feature/audit-coverage` (PR #268): `cli.py`, `test_cli.py` (T5 baut darauf auf), `hooks/router.py` (andere
  Funktionen als `_do_trigger`), `docs/developer/api-reference.html` (fügt nach `:122` eine Notiz ein; T4 ändert
  `:122`), `hooks.html` und `server.html` (andere Zeilen), `CHANGELOG.md`. Muss vor T5 gemergt sein.
- `feature/server-hardening`: `apps/server/app/core/bounds.py` (`_find_unstorable`, das T4 nutzt; T4 ändert
  `bounds.py` nicht), `server.html`, `CHANGELOG.md`. Muss vor T4 gemergt sein.
- `feature/server-fixes`: `scheduler.py` (T2 dort ändert `add_hook`, T3 hier `_parse_trigger`, `_execute_scheduled_hook`
  und `get_next_run`), `hooks/router.py` (`update_hook`), `api-reference.html`, `server.html`, `hooks.html`,
  `CHANGELOG.md`. Reihenfolge frei; wer später merged, holt `origin/main` herein.
- `server.html` und `CHANGELOG.md` teilen außerdem `feature/auth-sessions`, `feature/docs-drift` und
  `feature/compose-hardening` (andere Zeilen).

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld, keine neue Route; OpenAPI bleibt unverändert (kein Docstring und keine Signatur
einer Route ändert sich; T4 pinnt das mit `tests/test_openapi_snapshot.py`). Verhalten nach außen:
- T2: dieselben Antworten, nur früher; ein Hintergrundprozess, der die Ausgabe nach dem Ende des Workers offen hält,
  wird nach der kurzen Frist gekillt wie heute nach `timeout`.
- T3: Cron-Hooks laufen in UTC. Bei `TZ=Europe/Berlin` (Voreinstellung) läuft ein bestehender Cron-Hook nach dem
  Update eine Stunde (Winter) bzw. zwei Stunden (Sommer) später als bisher, zu der Zeit, die die Doku nennt. `next_run`
  wird beim nächsten Abgleich (30 s) neu geschrieben.
- T4: `POST /api/hooks/trigger` und `/trigger/{token}` antworten auf einen solchen Body mit 422 statt das Skript zu
  starten; Reihenfolge der Prüfungen: Ratelimit (429), Token (404), aktiv (403), Body (422).
- T5: keine Änderung an Optionen, Ausgaben oder Exit-Codes; ein Passwort mit Zeilenumbruch oder eines, das nicht in
  den Puffer einer Pipe passt, lehnt `--password` ab (Exit 2), wie es `--password-stdin` nie annehmen konnte.
Kein Vertrags-Drift zu Web, Desktop oder Agent.

## Externe Integrationen

- nginx `proxy_read_timeout` (nginx.org/en/docs/http/ngx_http_proxy_module.html, gelesen 2026-10-22): „Default:
  proxy_read_timeout 60s;“ — „The timeout is set only between two successive read operations, not for the
  transmission of the whole response. If the proxied server does not transmit anything within this time, the
  connection is closed.“
- Python-Kommandozeile (docs.python.org/3/using/cmdline.html, gelesen 2026-10-22): `-s` — „Don't add the user
  site-packages directory to sys.path.“; `PYTHONNOUSERSITE` — „This is equivalent to the -s option.“; `-I` — „This
  also implies -E, -P and -s options.“; `-E` — „Ignore all PYTHON* environment variables, e.g. PYTHONPATH […]“.
  Probe im Dev-Venv: `sys.flags.no_user_site` ist ohne `-s` 0, mit `-s` und mit `PYTHONNOUSERSITE=1` 1 (in einem venv
  ist `site.ENABLE_USER_SITE` immer `False`, deshalb prüft der Test das Flag).
- APScheduler 3.x (`apscheduler/triggers/cron/__init__.py` und `triggers/interval.py` der installierten 3.11.3):
  ohne `timezone`, `start_date` und `end_date` setzt der Trigger `self.timezone = get_localzone()` (tzlocal);
  `from_crontab(expr, timezone=None)` reicht `timezone` durch. Die Docstrings sagen „defaults to scheduler timezone“,
  der Code tut das nur über `add_job(trigger="cron", …)`.
- Linux-Pipes: `fcntl.F_GETPIPE_SZ` (Python ≥ 3.10) liefert die Kapazität einer Pipe (Default 64 KiB).

## Trade-offs & Alternativen

1. **User-Site (T1).** (a) `-s` plus `PYTHONNOUSERSITE=1` im Worker-Env — **Empfehlung**: der Worker und jedes
   Python, das ein Skript startet, lassen die User-Site weg; `PYTHONPATH` bleibt. (b) Nur `-s`: Python-Kindprozesse
   eines Skripts nähmen die User-Site unter `HOME` weiter mit. (c) `-I`: ignoriert `PYTHONPATH`, der Worker fände
   `app` nicht. (d) Den `HOME`-Rückfall ändern: siehe offene Frage 1.
2. **Wartefrist für die Ausgabe (T2).** (a) Eine feste kurze Frist (`_READER_GRACE_SECONDS`, 2 s) für beide
   Lese-Threads zusammen nach `proc.wait`, dann `killpg`, dann noch einmal dieselbe Frist — **Empfehlung**: Obergrenze
   `timeout + 4 s`, beim Default 34 s; ein Worker, der regulär endet, hat seine Ausgabe dann geschrieben, die Frist
   deckt nur das Lesen des Rests. (b) Die Fristen vom `timeout` abziehen (eine Gesamtfrist): verkürzt die Zeit, die
   ein langsames Skript hat, also sichtbares Verhalten. (c) `timeout` senken: sichtbar und dokumentiert
   (`docs/developer/hooks.html:87`). (d) `proxy_read_timeout` im Gateway erhöhen: verschiebt nur die Grenze, der
   Runner bliebe ohne feste Obergrenze.
3. **Zeitzone (T3).** (a) UTC für Cron-Trigger und `next_run` sauber nach UTC umrechnen — **Empfehlung**, so steht es
   in `betrieb.html:170`. (b) `TZ` gilt, Doku anpassen: hielte bestehende Cron-Hooks auf ihrer Zeit, widerspricht aber
   der Doku und der API-Konvention (alles UTC). Der Intervall-Trigger bekommt keine Zeitzone: er läuft in absoluter
   Zeit; der Fehler dort war nur `next_run`, das T3 an beiden Stellen (`:126`, `:166`) mit
   `astimezone(timezone.utc)` umrechnet.
4. **Prüfung des Bodys (T4).** (a) `_find_unstorable` aus `bounds.py` auf den gelesenen Payload, 422 als
   `RequestValidationError` mit `loc` `("body", …)` und `msg` wie bei `RequestModel` — **Empfehlung**: eine Regel an
   einer Stelle, der 422-Handler (`apps/server/app/main.py:409-421`) schreibt ein Surrogat schon escaped zurück.
   (b) Ein Schema für den Body: Webhooks nehmen beliebiges JSON (auch Listen und Strings), ein Schema müsste `Any`
   sein und brächte nichts. (c) Ersetzen statt ablehnen: ändert still, was das Skript bekommt.
5. **Passwort aus `--password` (T5).** (a) Neustart: `main` legt `--password` (nur beim echten Aufruf, `argv is None`)
   mit Zeilenumbruch in eine Pipe, macht sie zu stdin und ersetzt den Prozess per `os.execv` durch
   `python -m app.cli create-admin --username U --password-stdin` — **Empfehlung**: die Option bleibt, kein Code läuft
   mehr in einem Prozess mit dem Passwort in der Kommandozeile, nachdem der Benutzer angelegt ist; der Aufruf von
   `main([...])` im Prozess (Tests) bleibt wie heute. (b) `--password` entfernen: bricht Aufrufer und den Test
   `test_cli.py:84-89`; Entscheidung bei Kevin. (c) Nur warnen und die Doku auf stdin umstellen: Restrisiko bleibt;
   Entscheidung bei Kevin. (d) Event-Hooks bei `--password` nicht feuern: widerspricht `feature/audit-coverage` T7.

## Risiken & Rollback

- T3 verschiebt die Laufzeit bestehender Cron-Hooks um 1–2 h (CHANGELOG nennt es). Wer die Ortszeit wollte, schreibt
  den Ausdruck in UTC um.
- T2: Ein Skript, dessen Hintergrundprozess die Ausgabe absichtlich länger als 2 s nach dem Ende des Workers offen
  hält, verliert sie früher als heute (heute nach `timeout`). Der Prozess wird wie heute gekillt.
- T5: `os.execv` ersetzt das Prozessabbild; Interpreter-Optionen des ersten Aufrufs (`python -X …`) gehen dabei
  verloren. Zwischen Start und Neustart steht das Passwort weiter in der Kommandozeile (Imports der CLI); vor
  `feature/audit-coverage` T7 galt das für den ganzen Aufruf. Der Neustart passiert vor `SessionLocal()`.
- T4: Ein Aufrufer, der heute NUL-Bytes im Body schickt, bekommt 422; das Skript lief bisher, scheiterte aber,
  sobald es den Wert speicherte.
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt. `next_run` schreibt der nächste
  Abgleich neu.

## Doku-Impact

T1: `docs/developer/hooks.html:85` (DE+EN) nennt `PYTHONNOUSERSITE` und `-s`; CHANGELOG (Changed). T2:
`hooks.html:87` (DE+EN) nennt die Wartefrist und die Obergrenze; CHANGELOG (Fixed). T3: `docs/developer/server.html:161`
(DE+EN) sagt, dass Cron-Ausdrücke in UTC gelten; `betrieb.html:170` stimmt schon; CHANGELOG (Fixed, mit dem Hinweis auf
die verschobene Laufzeit). T4: `docs/developer/api-reference.html:122` (DE+EN) nennt den 422; CHANGELOG (Changed). T5:
`README.md:205` zeigt `--password-stdin`; CHANGELOG (Changed).

## Offene Fragen

1. **`HOME`-Rückfall (keine Task hängt daran).** Fehlt dem Server `HOME`, bekommt der Worker `HOME=/tmp`
   (`script_runner.py:115`, dokumentiert `hooks.html:85`, gepinnt `test_hook_isolation.py:156-160`). T1 nimmt die
   User-Site von Python heraus; andere Programme, die ein Skript startet, lesen ihre Konfiguration weiter unter
   `HOME`. Empfehlung: als eigene Roadmap-Zeile, Rückfall auf ein eigenes Verzeichnis des Servers (etwa unter
   `DATA_DIR`); im Container ist `HOME` gesetzt, der Rückfall greift nur außerhalb.
2. **T3, Zeitzone.** Die Doku legt UTC fest; T3 folgt ihr. Wer stattdessen `TZ` will, entscheidet das vor dem Bau
   von T3 (dann ändert T3 die Doku statt des Codes).
3. **Kandidat: `NaN`/`Infinity` im Webhook-Body.** `request.json()` liest die Tokens `NaN`/`Infinity`; gibt ein
   Skript sie zurück, kann die Antwort sie nicht schreiben. Nicht gemessen; eigene Zeile, wenn gewünscht.
