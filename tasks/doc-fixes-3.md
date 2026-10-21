<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Fixes 3: Hook-Laufzeit in hooks.html, RFC-5737-Adressen im Webhook-Beispiel — Task-Ledger
Status: aktiv · Branch: feature/doc-fixes-3 · Review: am Ende
Spec: Roadmap R-0528, R-0532
Heavy: none — nur Doku unter `docs/` (`hooks.html` DE+EN) und ein Kommentar in `docs/examples`; keine API-, Gateway-, PKI-, Agent-, Compose-, Install- oder Desktop-Journey-Änderung
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zwei Doku-Zeilen als Kurz-Ledger (`--kurz` je Zeile, Session 2026-10-21): R-0528 (BUG) und R-0532 (REF), dazu in T2
ein Beifang auf derselben Seite. Das Soll ist der Code: Jede Task nennt unter `Semantik:` die Code-Stelle und die
falsche Doku-Stelle mit Zitat; jede Aussage, die die Doku neu bekommt, steht in `Änderung:` mit ihrer Code-Stelle. Die
Zeilen gelten für origin/main@82e4a7b8; der builder greppt Code- und Doku-Stellen vor dem Schreiben neu. Doku hat keinen
roten Test: `Beweis:` ist ein grep, der auf `HEAD:` die Stellen zeigt und nach der Task leer ist; wo etwas fehlt, zählt
eine Positiv-Probe vorher 0 und danach die neuen Stellen. `Verify:` von T1 und T2 ist der formale Lauf
`scripts -- doc_smoke_test` (prüft den Checker an Fixtures); der builder fährt bei T1 und T2 zusätzlich
`python3 scripts/dev/doc-smoke.py --paths --env --strict` mit Exit 0, Ergebnis in den Commit-Body (in der PR-CI
`.github/workflows/ci.yml:874`; neue Env-Namen wie `HOME` oder `HTTP_PROXY` kennt der Check aus `script_runner.py`).
T3 fährt `tests/test_hook_examples.py`, das jede Datei unter `docs/examples/*.py` mit `ast` parst. Kein CHANGELOG:
Doku- und Beispielkorrektur ohne Verhaltensänderung (wie doc-fixes und doc-fixes-2).

Nicht in diesem Ledger: der Abschnitt Fehlerverhalten (`hooks.html:96-98` DE+EN) und die Log-Zeile zu
`app.modules.hooks.scheduler` in `docs/admin/betrieb.html:122` bzw. `docs/en/admin/operations.html:81`. Ob dort der Code
oder die Doku zu ändern ist, ist eine Verhaltensfrage und gehört in eine eigene Zeile.

### T1 — R-0528: hooks.html, Environment-Modell und SSRF-Satz wie Runner und Guard  [x]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9ee1755c 2026-10-21T09:35:15+02:00
Review: am Ende (Branch-Review)
Änderung: DE und EN, gleiche Zeilen. Code-Stellen ohne Pfad liegen in `apps/server/app/modules/hooks/script_runner.py`.
(1) Environment-Modell `:82-89`. Der Einleitungssatz `:83` bleibt und nennt die Quelle: `run_hook_script` in `apps/server/app/modules/hooks/script_runner.py`. Die Punkte:
- Reduziertes Env (`:85`): Der Worker bekommt `PATH`, `HOME` (fehlt es, `/tmp`), `LANG` (fehlt es, `C.UTF-8`), `PYTHONPATH` (das Server-Verzeichnis), `DATABASE_URL` und `DATA_DIR` (`:107-115`). `HTTP_PROXY`, `HTTPS_PROXY` und `NO_PROXY`, auch kleingeschrieben, reicht der Runner nur durch, wenn der Server sie gesetzt hat (`:116-125`), damit `http_get` und `http_post` einen konfigurierten Proxy nutzen (Kommentar `:104-106`). Laut httpx-Doku (python-httpx.org/environment_variables, gelesen 2026-10-21) liest httpx `HTTP_PROXY`, `HTTPS_PROXY` und `NO_PROXY` standardmäßig. Ob es die kleingeschriebenen Formen liest, ist nicht verifiziert; die Doku behauptet es nicht. Alles andere fällt weg, etwa `ADMIN_PASSWORD`, `MONITOR_API_KEY` und `REDIS_URL` (`:100-101`). Der Satz zu `SECRET_KEY` und DB-Zugang („kein Secret-Jail“) bleibt.
- CWD (`:86`) bleibt (`cwd=server_dir`, `:151`).
- Timeout (`:87`): Default 30 s (`:60`, `:89`). Der Worker läuft in einer eigenen Prozessgruppe (`start_new_session=True`, `:153`). Läuft der Timeout ab, killt der Runner die ganze Gruppe (`:193-197`). Damit sterben auch Kindprozesse, die das Script gestartet hat, außer solchen, die eine eigene Session öffnen (Kommentar `:219-221`). Der Hook endet mit `success: false` und `error` „Timeout nach 30s“ (`:198-203`). `subprocess.run` fällt weg.
- Ausgabe (`:88`): „Kein Output-Limit“ fällt weg. Der Runner liest stdout und stderr des Workers je bis 8 388 608 Zeichen, bei ASCII 8 MiB (`_MAX_HOOK_OUTPUT_BYTES` `:75`, Textmodus `text=True` `:150`, `read(_MAX_HOOK_OUTPUT_BYTES + 1)` `:163`). Liest er mehr, killt er den Worker. Der Hook endet dann mit `success: false` und `error` „Hook-Ausgabe zu gross (Limit ueberschritten)“ (`:165-171`, `:229-241`). Auf stdout schreibt der Worker seine JSON-Antwort samt `result` und `logs` (`apps/server/app/modules/hooks/script_worker.py:187-188`); ein sehr großes `result` zählt also mit. „Kein User-Switch“ bleibt als eigener Punkt (`Popen` ohne `user=`, `:145-154`).
- Neu, Parallelität: Höchstens 8 Hook-Prozesse laufen gleichzeitig (`_MAX_CONCURRENT_HOOKS`, `:69-70`). Ist keiner frei, wartet der Aufruf nicht, sondern endet sofort mit `success: false` und `error` „Server ausgelastet (Hook-Limit erreicht)“ (`:127-133`).
(2) Der Abschnitt Script-Runner-Implementierung (`:100-125`) fällt weg. Sein Code-Auszug zeigt `subprocess.run` und vier Env-Variablen; der Runner nutzt `Popen`, sechs Variablen und die Proxy-Variablen (`:107-125`, `:145-154`). Ein neuer Auszug veraltet wieder; der Verweis aus (1) ersetzt ihn, wie feste Zählwerte in doc-fixes.
(3) Baum `:43`: „Subprocess-Spawn (async)“ wird „Subprocess-Spawn (blockierend)“, EN „Async subprocess spawn“ wird „Subprocess spawn (blocking)“. `run_hook_script` ist ein normales `def` (`:85`) und wartet auf den Worker. Die Aufrufer lagern es aus: `run_in_threadpool` (`apps/server/app/modules/hooks/router.py:207-211`), Event-Dispatch im Thread-Pool (`apps/server/app/core/events.py:19`, `:65-67`).
(4) SSRF-Satz `:77` (Helfer-Liste). Abgelehnt wird ein Ziel, wenn eine seiner aufgelösten Adressen privat, Loopback, Link-Local, reserviert, Multicast oder unspezifiziert (`0.0.0.0`, `::`) ist oder in `0.0.0.0/8` oder `100.64.0.0/10` liegt. IPv4-gemappte IPv6-Adressen zählen wie ihre IPv4-Adresse (`apps/server/app/core/ssrf.py:29-32`, `:149-167`, Mapping `:156-157`). Abgelehnt wird auch eine URL, die sich nicht lesen lässt oder keinen Host hat, und ein Name, der sich nicht binnen 5 s auflösen lässt (`:43`, `:138-148`). Der Rest von `:77` bleibt (kein Redirect, `ValueError`, 1 000 000 Bytes).
Sonst bleibt die Seite unverändert, auch Fehlerverhalten `:96-98` (siehe Kopf).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/hooks.html + docs/en/developer/hooks.html (die Task ist die Doku); kein CHANGELOG
Beweis: origin/main@82e4a7b8 · `grep -n -o -E 'Subprocess-Spawn \(async\)|Async subprocess spawn|Nur <code>PATH</code>, <code>PYTHONPATH</code>|only <code>PATH</code>, <code>PYTHONPATH</code>|subprocess\.run|nicht zwingend dessen Kindprozesse|not necessarily its child processes|Kein Output-Limit|No output limit|private, reservierte oder Link-Local-Adresse|private, reserved or link-local address' docs/developer/hooks.html docs/en/developer/hooks.html` → je Seite `:43`, `:77`, `:85`, `:87` (2×), `:88`, `:118`; nach der Task leer · je Seite `grep -o -F -e '<code>HOME</code>' -e '<code>LANG</code>' -e '<code>HTTP_PROXY</code>' -e '<code>NO_PROXY</code>' -e '100.64.0.0/10' -e 'ulticast' <seite> | sort -u | wc -l` → `0`, danach `6`
Dedup-Key: bug:docs:hooks.html:environment-model
HEAD: 82e4a7b8
Semantik: Soll ist der Code:
- `apps/server/app/modules/hooks/script_runner.py:104-106` — „HOME/LANG are set so HOME- and locale-sensitive code behaves predictably rather than defaulting oddly; a configured egress proxy is forwarded below so a hook's HTTP calls (http_get/http_post) honour it“; dazu `:107-125`, `:60`, `:69-75`, `:127-133`, `:141-154`, `:162-171`, `:193-203`, `:229-241` und `script_worker.py:187-188`.
- `apps/server/app/core/ssrf.py:27-32`, `:43`, `:138-167`; die Helfer werfen `ValueError` (`script_worker.py:61-68`, `:79-86`).
Doku, die das Soll trägt: `docs/developer/hooks.html:34` — „registrierte Scripts laufen in einer sanitisierten Subprozess-Umgebung mit harter Timeout-Grenze“.
Falsche Doku-Stellen: `:85` — „Nur <code>PATH</code>, <code>PYTHONPATH</code>, <code>DATABASE_URL</code> und <code>DATA_DIR</code> werden durchgereicht“; `:87` — „beim Ablauf wird der Worker-Prozess gekillt, nicht zwingend dessen Kindprozesse“; `:88` — „<strong>Kein Output-Limit</strong>“; `:77` — „die auf eine private, reservierte oder Link-Local-Adresse zeigen“.

### T2 — Beifang zu R-0528: hooks.html, Test-Lauf über `/run` wie Router und Web-Panel  [ ]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html
Änderung: DE und EN, Absatz `:137` unter Test-Execution; die Überschrift bleibt. Der Absatz sagt:
- Im Web-Panel startet „Ausführen“ (EN „Run“, `action.run`) einen Hook von Hand über `POST /api/hooks/{id}/run`, nur für Admins (`apps/server/app/modules/hooks/router.py:336-338`, `apps/web/src/lib/api/hooks.ts:41`, `apps/web/src/pages/Hooks.svelte:84-98`).
- Der Context ist kein Beispiel-Event. Er ist so belegt, wie die API-Referenz es beschreibt, mit Verweis dorthin (`router.py:345-356`, `docs/developer/api-reference.html:121`).
- Das Ergebnis zeigt ein Dialog nach dem Lauf als JSON: `success`, `result`, `logs`, bei Fehler `error` (`apps/web/src/modals/HookRunResultModal.svelte:24-27`). Es kommt nicht in Echtzeit und hat keine eigenen Felder für stdout, stderr oder `exit_code`. Endet der Worker mit Fehler, steht sein stderr in `error` und `logs` (`apps/server/app/modules/hooks/script_runner.py:243-250`).
Sonst bleibt die Seite unverändert.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/hooks.html + docs/en/developer/hooks.html (die Task ist die Doku); kein CHANGELOG
Beweis: origin/main@82e4a7b8 · `grep -n -o -E '/api/hooks/\{id\}/test|in Echtzeit|in real time|Beispiel-Event|sample event' docs/developer/hooks.html docs/en/developer/hooks.html` → je Seite `:137` (3×); nach der Task leer · `grep -c -F '/api/hooks/{id}/run' docs/developer/hooks.html docs/en/developer/hooks.html` → je `0`, danach je `1`
Dedup-Key: bug:docs:hooks.html:test-execution
HEAD: 82e4a7b8
Semantik: Soll ist der Code: `apps/server/app/modules/hooks/router.py:336-363` (`@router.post("/{hook_id}/run")`, `get_current_admin`, Context `:345-356`), `apps/web/src/lib/api/hooks.ts:41`, `apps/web/src/modals/HookRunResultModal.svelte:24-27` (`JSON.stringify(result, null, 2)`). Doku: `docs/developer/api-reference.html:121` — „Manueller Test-Lauf. Im Context sind <code>payload</code>, <code>headers</code>, <code>params</code> und <code>event_data</code> leer und <code>event_type</code> ist <code>null</code>“; `:54` — „Das <code>result</code> von <code>POST /api/hooks/{id}/run</code> und <code>/api/hooks/trigger</code> ist, was das Skript zur&uuml;ckgibt.“ Falsche Doku-Stelle: `docs/developer/hooks.html:137` — „Im Web-Panel kann jeder Hook mit einem Beispiel-Event geprüft werden: <code>POST /api/hooks/{id}/test</code>. Der Execution-Log zeigt stdout/stderr/exit_code in Echtzeit“.

### T3 — R-0532: Webhook-Beispiel mit Adressen aus RFC 5737  [ ]
Komponente: server · Dateien: docs/examples/webhook_http_import.py
Änderung: Die Beispielantwort im Kopfkommentar (`:24-25`) nennt `192.0.2.1` (`web-01`) und `192.0.2.2` (`db-01`) statt der zwei Adressen aus `10.0.0.0/8`. Sonst ändert sich nichts, auch nicht die Ausrichtung der Spalten. Der Test parst jede Datei unter `docs/examples/*.py` und prüft die Aufrufe von `http_get`/`http_post` (`apps/server/tests/test_hook_examples.py`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_examples.py
Doku: docs/examples/webhook_http_import.py (die Task ist die Doku); kein CHANGELOG
Beweis: origin/main@82e4a7b8 · `git grep -n -E '(^|[^0-9.])10\.[0-9]+\.[0-9]+\.[0-9]+' -- docs/examples` → `webhook_http_import.py:24`, `:25`; nach der Task leer · `grep -c -E '"ip": "192\.0\.2\.' docs/examples/webhook_http_import.py` → `0`, danach `2`
Metrik: Adressen aus `10.0.0.0/8` unter `docs/examples`: 2 → 0 (`git grep` wie im Beweis)
Dedup-Key: ref:docs:examples:rfc5737-ips
HEAD: 82e4a7b8
Semantik: keine Stelle in docs/ — gesucht mit `git grep -n -E '5737|192\.0\.2'` über `docs`, `.claude`, `CLAUDE.md`, `DEVELOPMENT.md` und `scripts/dev`, kein Treffer. Maßstab ist RFC 5737 §3 (rfc-editor.org/rfc/rfc5737, gelesen 2026-10-21) — „The blocks 192.0.2.0/24 (TEST-NET-1), 198.51.100.0/24 (TEST-NET-2), and 203.0.113.0/24 (TEST-NET-3) are provided for use in documentation.“ Falsche Stelle: `docs/examples/webhook_http_import.py:24-25` — die Beispielantwort der externen API nennt zwei Adressen aus `10.0.0.0/8`.
