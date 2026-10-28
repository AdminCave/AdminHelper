<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Metrik-Filter, Mount-Default, Speicher- und Eingabegrenzen, Nacharbeiten aus monitoring-io — Task-Ledger
Status: erledigt · Branch: feature/monitoring-hardening-2 · Review: pro Task
Spec: docs/features/monitoring-hardening-2.md (Roadmap R-0749, R-0753, R-0774, R-0799; T4, T6, T8 und T9 gehören zum Paket, Kevin 2026-10-22)
Heavy: none — nur Interna von `apps/monitoring` und Doku: keine Route, kein Response-Schema, keine OpenAPI-Änderung (`field_validator`/`model_validator(mode="before")` ändern das JSON-Schema nicht; `tests/test_openapi_snapshot.py` steht im Verify von T3 und T9), kein Alembic (nur bei Variante B von T9 käme eine Datenmigration und damit `linux-full` dazu), kein Agent-, Gateway-, Compose-, PKI-, FRP- oder Install-Pfad; T1 ändert nur den PromQL-Selektor des Metrik-Abrufs, T2 einen Tag-Wert
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: monitoring-io (PR #265, `tasks/monitoring-io.md` auf `feature/monitoring-io`) — der Branch steht auf dessen Stand 13f340e4, gebaut wird erst nach dem Merge; smtp-hardening (`feature/smtp-hardening`) vor T8, beide ändern `apps/monitoring/app/alerter.py`.

Ziel: (1) Der Metrik-Abruf zeigt je Check nur dessen Reihen (R-0749). (2) Eine Platte ohne `mount` heißt im
Push-Pfad wie im Checker `?` (R-0753). (3) Kein Body und kein Agent-Report mit ungepaartem Surrogat erreicht
Datenbank oder Schreibpuffer (R-0774). (4) Schreibpuffer und HTTP-Check halten begrenzten Speicher. (5) Der Betreff
einer Alert-Meldung ist einzeilig, neue Check-Namen tragen keine Steuerzeichen. (6) Die Nacharbeiten aus den
Prüfungen von monitoring-io (R-0799). Zeilenangaben: `origin/feature/monitoring-io@13f340e4`; vor T1 zieht der
builder `origin/main` nach (mit monitoring-io und smtp-hardening) und greppt jede Zeile vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge von oben nach unten. Echte Abhängigkeiten: T5 → T4, T7 → T6, T10 → T6. Sonst ordnet die gemeinsame
  Datei: `app/routers/checks.py` (T1, T12), `app/routers/agent.py` (T2, T3, T13), `app/core/victoria.py` (T4, T5),
  `tests/test_agent_report.py` (T2, T13), `tests/test_execute_check.py` (T12, T13), `docs/developer/monitoring.html`
  + EN (T1, T2, T3, T4, T5, T10), `docs/admin/monitoring.html` + EN (T8, T10).
- `scripts/dev/review-risk.txt` führt `app/routers/agent.py`, `app/alerter.py`, `app/check_engine.py` und
  `app/schemas.py`: T2, T3, T8, T9 und T13 bekommen zusätzlich `security`.
- Tests auf SQLite über `client_db` (`tests/conftest.py`). Ein Body mit ungepaartem Surrogat geht als JSON-Text
  (`content=` mit `\\ud800`, `content-type: application/json`): `json=` kodiert ihn nicht.
- Neue Code-Strings (Fehlertexte, Log-Zeilen) englisch; bestehende deutsche Texte bleiben. CHANGELOG umlautfrei
  unter `## [Unreleased]`.
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737.
- `feature/ssrf-followups` (Plan 560b112b) ändert dieselben Dateien `app/checkers/http.py`, `app/alerter.py`,
  `tests/test_http_checker.py`, `tests/test_alerter.py`, die Monitoring-Doku und `CHANGELOG.md` (andere Funktionen):
  wer als Zweiter merged, zieht `origin/main` nach und greppt neu.
- Kein Name mit führendem Unterstrich neu über Modulgrenzen (monitoring-ref-3 T10 setzt dafür einen Wächter): wer eine Konstante oder
  Funktion eines anderen Moduls braucht, macht sie öffentlich.

### T1 — Metrik-Abruf: nur `agent_resources` nach Server filtern (R-0749)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_checks_metrics.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ff436d7a 2026-10-23T21:01:36+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T1.verdict.json)
Änderung: In `get_check_metrics` (`app/routers/checks.py:440-517`) entfällt die Menge `agent_types` (`:462-469`); nach Server filtert nur `agent_resources` mit `server_id` (`server_id="…",check_id=""` wie heute `:476-482`), jeder andere Typ und ein `agent_resources`-Check ohne `server_id` nach `check_id="…"` (`:471-475`). Der Kommentar `:460-461` sagt dann, warum `agent_resources` der Sonderfall ist: Der Agent-Push schreibt CPU, RAM, Platten und Temperaturen je Server ohne `check_id` (`app/routers/agent.py:100-137`); die übrigen Push- und Pull-Typen schreiben ihre Werte mit Check-Labels (`app/core/victoria.py:223-261`). Tests in `tests/test_checks_metrics.py` mit der vorhandenen Naht, die die Abfragen sammelt (`:101-156`): (a) parametrisiert über `agent_ping`, `service_process`, `docker_health`, `proxmox_backup`, `zfs_health`, Check mit `server_id="srv-1"`: jede Abfrage trägt `check_id="<id>"` und kein `server_id=`; (b) zwei `docker_health`-Checks auf `srv-1` → zwei verschiedene Selektoren; (c) Gegenstück: `agent_resources` mit `server_id` fragt CPU/RAM und Platten/Temperaturen weiter mit `server_id="srv-1",check_id=""`. Zuerst rot: (a), (b) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checks_metrics.py
Doku: docs/developer/monitoring.html:265 + EN `:265` (ein Halbsatz: jeder andere Check-Typ liest seine Reihen über `check_id`) · CHANGELOG.md (Fixed, umlautfrei: der Metrik-Abruf von `agent_ping`, `service_process`, `docker_health`, `proxmox_backup` und `zfs_health` zeigt nur die Reihen des eigenen Checks; zwei Checks desselben Typs auf einem Server zeigten bisher beide Reihen doppelt)
Beweis: origin/feature/monitoring-io@13f340e4 · Code-Lesung `app/routers/checks.py:462-475` gegen die Schreiber `app/checkers/agent.py:236`, `:242`, `:690`, `app/checkers/plugins.py:139`, `:219`, `:438` und den Push-Pfad `app/routers/agent.py:226-234` (alle über `build_check_result_lines` mit `check_id`); ausführbar: Test (a) rot auf HEAD
Orakel: contract — der Selektor eines Checks enthält seine `check_id`, außer bei `agent_resources` mit `server_id`
Dedup-Key: bug:monitoring:routers/checks.py:metrics-filter-by-server-only
HEAD: 13f340e4

### T2 — Agent-Push: Platte ohne `mount` heißt `?` wie im Checker (R-0753, R-0799)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_report.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c7a6e593 2026-10-23T21:08:37+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T2.verdict.json)
Änderung: `_NO_MOUNT` (`app/checkers/agent.py:30`, Nutzer `:426`, `:504`, `:511`) heißt `NO_MOUNT`; `app/routers/agent.py:111` nimmt ihn statt `"/"` als Default von `entry_text(disk, "mount", …)`. `sensor` bleibt `unknown` (`:119`, Spec Nicht-Ziele). Nebenbei (R-0799): `ServiceProcessChecker._capped` (`app/checkers/agent.py:626-629`) kürzt mit `_MAX_REPORT_ENTRIES` statt der Zahl 500, und der Kommentar `:124-126` nennt beide Stellen, die Report-Listen kürzen (`capped_objects` für Listen von Objekten, `_capped` für die Unit-Listen). Test: `test_a_text_field_that_is_no_string_counts_as_missing` (`tests/test_agent_report.py:551-578`) erwartet für `{"mount": 5, …}` `mount=? value=50i` statt `mount=/ value=50i` (`:576`); neu daneben: eine Platte ganz ohne `mount` neben einer mit `mount="/"` → zwei Zeilen, `mount=?` und `mount=/`. Zuerst rot: beide auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_agent_resources_checker.py tests/test_checker_forecast.py
Doku: docs/developer/monitoring.html:145 + EN `:145` (`mount` dann `?` statt `/`) · CHANGELOG.md (Fixed, umlautfrei: eine Platte ohne lesbaren Mountpoint schreibt der Agent-Push als `mount=?` wie der Checker; bisher landete sie in der Reihe von `/` und verfaelschte deren Prognose in `disk_forecast`)
Assertion-Änderung: apps/monitoring/tests/test_agent_report.py::test_a_text_field_that_is_no_string_counts_as_missing — eine Zahl als mount ergibt jetzt mount=? statt mount=/ (R-0753, gewollte Verhaltensänderung)
Beweis: origin/feature/monitoring-io@13f340e4 · Code-Lesung `app/routers/agent.py:111` (`"/"`) gegen `app/checkers/agent.py:30` (`"?"`), Gruppierung nach `mount` in `app/checkers/forecast.py:82`; ausführbar: der neue Test rot auf HEAD
Orakel: contract — Push-Pfad und Checker nennen eine Platte ohne `mount` gleich
Dedup-Key: bug:monitoring:routers/agent.py:mount-default-root
HEAD: 13f340e4

### T3 — Eingaben: ungepaarte Surrogate wie NUL mit 422 abweisen (R-0774)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/bounds.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_nul.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md, apps/monitoring/tests/test_check_configs.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @ed474cc6 2026-10-23T21:24:24+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T3.verdict.json)
Änderung: `app/core/bounds.py:43-98` übernimmt die Regel des Servers wörtlich (`apps/server/app/core/bounds.py:51-125` auf `feature/server-hardening`, Commit `908a84b6`): `_LONE_SURROGATE`, `_unstorable(text) -> str | None` (Grund oder `None`), `_find_unstorable(data) -> tuple[tuple, str, str] | None` (Ort, Wert, Grund; Stack statt Rekursion, auch Dict-Schlüssel), `_refuse_unstorable`, `RequestModel._reject_unstorable_anywhere`; Texte „must not contain a NUL byte“ und „must not contain a lone surrogate (U+D800 to U+DFFF)“. `_find_nul`/`_refuse_nul`/`_reject_nul_anywhere` entfallen. `app/routers/agent.py:28`, `:68-84`: prüft mit `_find_unstorable` weiter nach der Liveness, WARNING `"Agent report from %s refused: %s at %s"` (Server, Grund, Ort), `msg` `f"Value error, {reason}"`. Tests in `tests/test_nul.py`: (a) `POST /checks` mit `_CHECK` (`:19`) und `name` `"a\ud800"` → 422, `loc` `["body", "name"]`, `msg` „Value error, must not contain a lone surrogate (U+D800 to U+DFFF)“; (b) dasselbe in `config.target` → `loc` `["body", "config", "target"]`, danach liefert `GET /checks` 200 (auf HEAD wird die Zeile gespeichert, `json.dumps` maskiert das Surrogat, und `GET /checks` endet danach mit 500); (c) ein Schlüssel mit Surrogat in `config` → 422 mit dem Schlüssel als letztem `loc`-Teil; (d) Agent-Report mit `{"resources": {"disks": [{"mount": "\ud800", "fstype": "ext4", "percent": 5}]}}` → 422, Liveness zählt, kein `victoria.write` (wie `:66-92`); (e) Gegenstück: ein gepaartes Surrogat (JSON `"😀"`) in `name` → 201. Die NUL-Tests bleiben unverändert grün. Zuerst rot: (a)–(d) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_nul.py tests/test_agent_report.py tests/test_openapi_snapshot.py tests/test_check_configs.py
Assertion-Änderung: apps/monitoring/tests/test_check_configs.py::test_a_lone_surrogate_in_the_input_is_escaped — ein Body mit Surrogat endet jetzt an RequestModel (422 an name, input das Surrogat) statt an der Config-Prüfung; der Fall Surrogat neben NaN steht als test_a_lone_surrogate_beside_a_non_finite_number_is_escaped am Handler selbst, wie der Server in 908a84b6 (R-0774, gewollte Verhaltensänderung)
Doku: docs/developer/monitoring.html:233 + EN `:233` („nach der Prüfung auf NUL und ungepaarte Surrogate“) · CHANGELOG.md (Fixed, umlautfrei: ein Body oder Agent-Report mit einem einzelnen UTF-16-Surrogat (JSON `\ud800`) wird mit 422 abgewiesen; bisher endete das Speichern oder eine spaetere Antwort mit HTTP 500, und im Agent-Report ging der ganze Schreibstapel nach VictoriaMetrics verloren)
Beweis: origin/feature/monitoring-io@13f340e4 · Probe (Python 3.13.5, SQLite): Binden von `"a\ud800"` → `UnicodeEncodeError`; `json.loads('"\\ud800"')` liefert das Surrogat; eine Agent-Zeile mit Surrogat-Mount im selben Stapel wie Zeilen eines zweiten Servers → `_send` scheitert in `content=body` (`app/core/victoria.py:199`), `_run` loggt (`:183-187`), in 3 von 4 Läufen kam keine Zeile des zweiten Servers an (zeitabhängig); ausführbar: Tests (a), (b) rot auf HEAD
Orakel: differential — gleiche Antwort wie der Server für denselben Body
Dedup-Key: bug:monitoring:core/bounds.py:no-surrogate-rule
HEAD: 13f340e4

### T4 — Schreibpuffer: Obergrenze auch in Bytes  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/victoria.py, apps/monitoring/tests/test_victoria.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c77b60a9 2026-10-23T21:35:53+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T4.verdict.json)
Änderung: Neu `_MAX_PENDING_BYTES = 64 * 1024 * 1024` neben `_MAX_PENDING_LINES` (`app/core/victoria.py:21`). `VictoriaClient` führt `self._pending_bytes`; `write` (`:126-157`) rechnet `sum(sys.getsizeof(line) for line in metrics)` vor dem Lock (gezählt wird der gehaltene Speicher, nicht die Zeichenzahl) und nimmt einen Aufruf nur, wenn Zeilen- und Byte-Grenze beide passen; sonst wie heute ganz verworfen und in `_dropped` gezählt. `_run` (`:181-182`) zieht die Bytes des entnommenen Stapels unter demselben Lock ab. Die WARNING (`:153-157`) nennt beide Grenzen: `"VictoriaMetrics write buffer full (%d lines or %d bytes): dropped %d lines since the last report"`. Der Kommentar `:19-20` sagt neu: Die beiden Grenzen deckeln den Speicher, solange VictoriaMetrics nicht annimmt; „about an hour of agent reports from 250 servers“ gilt nur für Zeilen von rund 100 Zeichen; ein Stapel hat höchstens `_MAX_BATCH_LINES` Zeilen. Tests in `tests/test_victoria.py` (`TestVictoriaWriter`, `:209`, Writer blockiert wie in `:240-271`): (a) mit der echten Konstante: 100 Aufrufe mit je einer Zeile von 1 MiB (dasselbe String-Objekt, damit der Test keinen echten Speicher braucht) → die ersten, deren Summe unter 64 MiB bleibt, landen im Puffer, der Rest wird verworfen und gezählt (auf HEAD landen alle 100); (b) nach dem Leeren durch den Writer ist `_pending_bytes` 0 und ein neuer Aufruf passt wieder; (c) die Zeilengrenze greift weiter allein (bestehender Test `:240` unverändert grün). Zuerst rot: (a) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_victoria.py
Doku: docs/developer/monitoring.html:263 + EN `:263` („Der Puffer fasst 100 000 Zeilen und höchstens 64 MiB“) · CHANGELOG.md (Ergänzung des Eintrags `:118-124`: der Puffer fasst bis 100 000 Zeilen und hoechstens 64 MiB)
Beweis: Code-Lesung apps/monitoring/app/core/victoria.py:137
HEAD: 13f340e4

### T5 — Schreibpuffer: Zahl verworfener Zeilen auch ohne weiteren Verwurf melden (R-0799)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/victoria.py, apps/monitoring/tests/test_victoria.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @9e320242 2026-10-23T21:47:31+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T5.verdict.json)
Änderung: Zeilen, die innerhalb von 60 s nach einer WARNING verworfen werden, zählt `write` still (`app/core/victoria.py:145-151`); bisher nennt erst der nächste Verwurf ihre Zahl. Neu: Ist der Puffer nach der Entnahme eines Stapels in `_run` (`:181-182`) leer und `_dropped` größer 0, nimmt `_run` die Zahl unter dem Lock (wie `:152`) und loggt dieselbe WARNING außerhalb des Locks; so meldet spätestens das Leeren (auch über `close()`) den Rest. Der Docstring `tests/test_victoria.py:44-45` nennt statt des „SMART push path (agent router)“ die heutigen Nutzer von `safe_metric_part` (Checker-Pfad; vorher greppen). Test in `TestVictoriaWriter`: Writer blockiert, Puffer voll, Verwurf 1 → WARNING mit seiner Zahl; Verwurf 2 nach 10 s (Uhr über `_now`) → keine WARNING; Writer frei, Puffer leer → genau eine weitere WARNING mit der Zahl von Verwurf 2. Zuerst rot auf HEAD (die zweite WARNING fehlt).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_victoria.py
Doku: docs/developer/monitoring.html:263 + EN `:263` (die WARNING kommt höchstens einmal je Minute und spätestens, wenn der Writer den Puffer geleert hat)
Abhängt von: T4
Beweis: origin/feature/monitoring-io@13f340e4 · Code-Lesung `app/core/victoria.py:145-151` (Verwurf im Fenster zählt nur) und `:170-187` (`_run` meldet nichts); ausführbar: der neue Test rot auf HEAD
Orakel: contract — jede verworfene Zeile steht in genau einer WARNING
Dedup-Key: ref:monitoring:io-nits
HEAD: 13f340e4

### T6 — HTTP-Check: komprimierte Antwort schrittweise und begrenzt entpacken  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/tests/test_http_checker.py, CHANGELOG.md, apps/monitoring/tests/test_checker_messages.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6668a47a 2026-10-23T22:40:32+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T6.verdict.json)
Änderung: `_read_head` (`app/checkers/http.py:145-160`) liest `resp.iter_raw()` statt `iter_bytes()` (`:149`) und entpackt selbst, mit derselben Auswahl wie httpx 0.28.1 (`httpx/_models.py` `_get_content_decoder`, `httpx/_decoders.py` `SUPPORTED_DECODERS`, `MultiDecoder` in umgekehrter Reihenfolge): `Content-Encoding` kommagetrennt, je Wert getrimmt und klein; `identity` reicht durch, `gzip` → `zlib.decompressobj(zlib.MAX_WBITS | 16)`, `deflate` → `zlib.decompressobj()`, scheitert dessen erstes Stück mit `zlib.error`, roh mit `-zlib.MAX_WBITS` (wie `DeflateDecoder`); jeder andere Wert (auch `br`, `zstd`, `x-gzip`; brotli und zstandard fehlen im Image) wird übersprungen wie in httpx. Jeder Schritt gibt höchstens die noch fehlenden Bytes bis `_MAX_BODY_BYTES + 1` aus (`decompress(data, max_length)`), den Rest hält `unconsumed_tail` und verarbeitet ihn vor dem nächsten rohen Stück; Zwischenschritte einer Kette ebenso begrenzt. `zlib.error` → `httpx.DecodingError(str(exc))` wie httpx; der Check endet dann wie heute über `except Exception` (`:142-143`). Frist (`deadline`) je rohem Stück und je entpackter Portion; Zeichensatz-Dekodierung `:159` bleibt. Tests in `tests/test_http_checker.py` über die Naht `httpx.HTTPTransport.handle_request` (`:66`) mit einem Stream in Stücken von 64 KiB: (a) Speicher: `tracemalloc`-Spitzenwert während `_read_head` für einen gzip-Body aus mindestens 32 MiB Nullen und für `Content-Encoding: gzip, gzip` aus mindestens 64 MiB Nullen (Daten schrittweise komprimiert, ohne den Klartext zu halten) unter 8 MiB, Ergebnis `truncated=True` und 1 MiB Text; (b) Parität gegen httpx (`iter_bytes`, erste 1 MiB) für identity, `gzip`, `deflate` mit zlib-Kopf, `deflate` roh, `gzip, gzip`, `GZIP`, `x-custom` und `br` (beide roh), Body genau 1 MiB (nicht abgeschnitten) und 1 MiB + 1 (abgeschnitten), je in Stücken von 1 Byte, 7 Bytes und 64 KiB; (c) kaputter gzip-Body → Status `unknown`, Meldung gleich wie auf HEAD (`Error: ` + zlib-Text). Zuerst rot: (a) auf HEAD; (b) und (c) grün vorher und nachher.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py tests/test_checker_messages.py
Doku: CHANGELOG.md (Ergänzung des Eintrags `:158-164`: eine komprimierte Antwort entpackt der Check schrittweise und hoechstens bis 1 MiB) · `docs/developer/monitoring.html:175` in T10
Beweis: Code-Lesung apps/monitoring/app/checkers/http.py:149
HEAD: 13f340e4

### T7 — HTTP-Check: Tests für Redirect-Zählung, Redirect ohne `Location`, Zeichensatz (R-0799)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_http_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @30a41314 2026-10-23T22:51:33+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T7.verdict.json)
Änderung: Neue Tests über die Naht `httpx.HTTPTransport.handle_request`: (a) fünf Redirects (sechs Anfragen) → `ok`; sechs Redirects → `critical` „Too many redirects (>5)“ nach genau sechs Anfragen (`app/checkers/http.py:89-90`); (b) 302 ohne `Location` → `critical` nach genau einer Anfrage (nur Status und Anfragezahl, den Text nicht: er ist irreführend und eine eigene Roadmap-Zeile, Spec, Nicht-Ziele); (c) `Content-Type: text/html; charset=iso-8859-1` mit `b"Gr\xfc\xdfe"` und `search_string` „Grüße“ → `ok` (`:159`), Gegenprobe: dieselben Bytes ohne `charset` → `critical` „Text 'Grüße' not found in response“. Mutations-Stichprobe in einer Kopie im eigenen Scratch-Verzeichnis, nie im Bau-Worktree: M1 `redirects == _MAX_REDIRECTS` → `redirects > _MAX_REDIRECTS` (`:89`) → (a) rot; M2 `resp.encoding or "utf-8"` → `"utf-8"` (`:159`) → (c) rot; Ergebnis und beide Summary-Zeilen (Datei vor und nach dem Diff) in den Commit-Body.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_http_checker.py
Doku: keine (nur Tests)
Abhängt von: T6
Beweis: origin/feature/monitoring-io@13f340e4 · `grep -n "Too many redirects\|charset" apps/monitoring/tests/test_http_checker.py` → leer (Planer, 2026-10-22); ob M1/M2 heute schon ein anderer Test fängt, misst der builder vorher (nicht verifiziert)
Orakel: mutation-sample — M1, M2 wie in `Änderung:`; eine Stichprobe, kein Beweis der Vollständigkeit
Metrik: Mutationen M1, M2, die `tests/test_http_checker.py` fängt: vorher (builder misst) → 2 von 2
Dedup-Key: ref:monitoring:io-nits
HEAD: 13f340e4

### T8 — Alert-Betreff einzeilig  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/alerter.py, apps/monitoring/tests/test_alerter.py, docs/admin/monitoring.html, docs/en/admin/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @96af02fc 2026-10-23T23:19:12+02:00
Review: approve (.ah-out/review/monitoring-hardening-2/T8.verdict.json)
Änderung: `_build_message` (`app/alerter.py:503-556`) setzt den Check-Namen im Betreff (`:515`, `:527`) über eine eigene Tabelle `_SUBJECT_TO_SPACE`, gleich gebaut wie `_AGENT_TEXT_TO_SPACE` (`app/checkers/agent.py:67-69`): jedes Steuerzeichen (C0, DEL, C1) und U+2028/U+2029 wird eins zu eins zum Leerzeichen; ein Kommentar nennt das Warum (der Betreff ist ein Kopfzeilen-Wert, Pythons `email`-Paket verweigert einen mehrzeiligen). `text` und `check_name` (Webhook, JSON) bleiben unverändert; der Glocken-Titel (`:405-408`) folgt dem Betreff. Der Docstring `tests/test_alerter.py:5-11` beschreibt, was die Datei heute testet (auch mit SQLite im Speicher, `:40`; R-0799). Tests in `tests/test_alerter.py` neben `test_build_message_recovery_escalation_and_details` (`:555`): (a) parametrisiert über `"web\r\nnext"`, `"a\nb"`, `"a\rb"`, `"a\x0bb"`, `"a\x1cb"`, `"a\x85b"`, `"a b"`, je als Alarm und Recovery: der Betreff enthält keins dieser Zeichen, an ihrer Stelle ein Leerzeichen, `text` enthält den Namen unverändert; (b) eine `MIMEMultipart("alternative")` mit diesem Betreff wie in `_send_email` (`:676-680`), serialisiert wie `smtplib.SMTP.send_message` (`email.generator.BytesGenerator`, `linesep="\r\n"`) → keine Exception, genau ein `Subject:`-Kopf; (c) Gegenstück: ein Name ohne Steuerzeichen ergibt den Betreff wie bisher. Zuerst rot: (a), (b) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_alerter.py tests/test_alerter_dispatch.py
Doku: docs/admin/monitoring.html:344 + EN `:344` (nach den Betreff-Formaten: Zeilenumbrüche und andere Steuerzeichen im Check-Namen stehen im Betreff als Leerzeichen) · CHANGELOG.md (Fixed, umlautfrei: eine Alert-Mail fuer einen Check mit Zeilenumbruch im Namen scheiterte mit „SMTP error (HeaderParseError)“; der Betreff ist jetzt einzeilig, Text und Webhook tragen den Namen unveraendert)
Beweis: Code-Lesung apps/monitoring/app/alerter.py:677
HEAD: 13f340e4

### T9 — Check-Namen: Steuerzeichen mit 422 abweisen  [x]
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @20a19223 2026-10-28T15:31:56+01:00
Review: approve (.ah-out/review/monitoring-hardening-2/T9.verdict.json)
Entscheidung: Kevin 2026-10-23: Variante A, 422 für CheckCreate, CheckUpdate (wenn gesendet) und TemplateCheckDef, ohne Migration.
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/tests/test_check_names.py, CHANGELOG.md
Änderung (Variante A): ein Helfer in `app/schemas.py` und `field_validator("name")` in `CheckCreate` (`:24-26`), `CheckUpdate` (`:45-47`, nur wenn gesendet) und `TemplateCheckDef` (`:87-89`): ein Zeichen unter U+0020 oder U+007F → `ValueError("must not contain control characters")` → 422 mit `loc` `["body", "name"]` bzw. `["body", "check_definitions", <i>, "name"]`. Grenze wie die FRP-Felder des Servers (`apps/server/app/modules/frp/schemas.py:24-36`, C0 und DEL); C1 und U+2028/U+2029 bleiben erlaubt, den Betreff deckt T8. Alert-Regel- und Template-Namen bleiben (nicht im Betreff). Neue Datei `tests/test_check_names.py` (SPDX per `reuse annotate`): (a) `POST /checks` mit `name` `"a\nb"`, `"a\rb"`, `"a\tb"`, `"a\x7fb"` → 422, `loc`, `msg` „Value error, must not contain control characters“; (b) `PUT /checks/{id}` mit einem solchen Namen → 422, ohne `name` → 200; (c) `POST /templates` mit `check_definitions[0].name` `"x\ny"` → 422 mit `loc`; (d) Gegenstück: `"Web 1 – Grüße ✓"` und `"a b"` → 201. Zuerst rot: (a)–(c) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_names.py tests/test_openapi_snapshot.py
Doku: CHANGELOG.md (Changed, umlautfrei: Check-Namen mit Steuerzeichen (Zeilenumbruch, Tab, DEL) lehnt das Monitoring mit 422 ab, wie der Server seine FRP-Felder); `docs/` nennt keine Namensregel, bleibt
Beweis: Code-Lesung apps/monitoring/app/schemas.py:26
HEAD: 13f340e4

### T10 — Doku und CHANGELOG nach monitoring-io präzisieren (R-0799)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @68c3f527 2026-10-28T15:41:13+01:00
Review: approve (.ah-out/review/monitoring-hardening-2/T10.verdict.json)
Änderung: DE und EN an denselben Stellen, Code-Stellen nach T6 greppen. (1) `docs/admin/monitoring.html:149`, `timeout`: gilt für den ganzen Check, jede Anfrage bekommt die verbleibende Zeit, das Lesen des Bodys endet mit der Frist; ein einzelner Lesevorgang, auch der Kopfzeilen, wartet bis zur verbleibenden Zeit, eine Antwort, die stückweise kommt, kann den Check über `timeout` hinaus halten (`app/checkers/http.py:73`). (2) `:227`: Die aufgeklappte Grafik zeigt bei HTTP 502 des Metrik-Abrufs „Fehler beim Laden“ (EN „Error loading“, `apps/desktop/ui/src/components/monitoring/section/ExpandChart.svelte:80`, `apps/desktop/ui/src/lib/i18n/dictionaries.ts:674`, `:1464`) statt leerer Reihen. (3) `docs/developer/monitoring.html:175`, `http.py`: `search_string` wird in den ersten 1 MiB des entpackten Bodys gesucht; `gzip` und `deflate` entpackt der Check schrittweise selbst, andere Kodierungen bleiben roh (nach T6). (4) `CHANGELOG.md`: `:127` (Grafik zeigt „Fehler beim Laden“), `:137-139` (ein Eintrag, der kein Objekt ist, wird uebersprungen; eine Liste als `fstype` zaehlt wie ein fehlender `fstype`, die Platte wird geschrieben), `:145-146` (der Report endete mit HTTP 500 oder speicherte still nichts), `:160-161` (wie (1)).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Stellen selbst
Abhängt von: T6
Beweis: origin/feature/monitoring-io@13f340e4 · Code-Lesung an den genannten Stellen; Lese-Probe des Prüfers von monitoring-io (`timeout=1.0`, Kopfzeilen in Stücken von 8 Bytes alle 0,4 s → Antwort 200 nach 3,29 s)
Dedup-Key: ref:monitoring:io-nits
HEAD: 13f340e4

### T11 — Test: Fehlertext „Metrics store unavailable“ (R-0799)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_api_error_texts.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2e0da1da 2026-10-28T15:48:06+01:00
Review: approve (.ah-out/review/monitoring-hardening-2/T11.verdict.json)
Änderung: Ein Fall für `GET /checks/{id}/metrics`, dessen VictoriaMetrics-Abfrage scheitert (Naht wie `tests/test_checks_metrics.py:159-166`) → 502, `detail` exakt „Metrics store unavailable“; die Datei verspricht „One case per text the API can reach“ (`tests/test_api_error_texts.py:5-8`). Mutations-Stichprobe in einer Kopie im eigenen Scratch-Verzeichnis: der Text in `app/routers/checks.py` (`_series_or_502`, vorher greppen) geändert → der neue Fall rot; Ergebnis und beide Summary-Zeilen in den Commit-Body.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_api_error_texts.py
Doku: keine (nur Tests)
Beweis: origin/feature/monitoring-io@13f340e4 · `grep -n "Metrics store unavailable" apps/monitoring/tests/test_api_error_texts.py` → leer
Orakel: mutation-sample — der geänderte Text wird rot
Metrik: Texte der API ohne Fall in `tests/test_api_error_texts.py`, davon „Metrics store unavailable“: 1 → 0
Dedup-Key: ref:monitoring:io-nits
HEAD: 13f340e4

### T12 — Manueller Lauf: ein währenddessen gelöschter Check ergibt 404 statt 500 (R-0799)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_execute_check.py, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @47454047 2026-10-28T15:57:32+01:00
Review: approve (.ah-out/review/monitoring-hardening-2/T12.verdict.json)
Änderung: `run_check_now` (`app/routers/checks.py:340-368`) liest den Check nach `execute_check(check_id)` (`:364`) neu; fehlt er, `HTTPException(404, "Check not found")` (Text wie `:345`). `db.expire_all()` (`:366`) entfällt: `db.rollback()` (`:363`) hat alle Objekte der Session schon abgelaufen. Tests in `tests/test_execute_check.py`: (a) wie `test_manual_run_holds_no_pooled_connection` (`:258`) mit einem Lauf, der den Check löscht (wie `deleting_run`, `:239-243`) → 404 `{"detail": "Check not found"}`; auf HEAD wirft die Antwort `ObjectDeletedError` (500); (b) `test_a_check_deleted_during_its_run_drops_the_result` (`:235-255`) prüft zusätzlich, dass der Lauf lief, und die DEBUG-Zeile „Check c1 was deleted during its run, result dropped“ (`app/check_engine.py:363`); seine Assertions bleiben. Zuerst rot: (a) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_execute_check.py tests/test_api_error_texts.py
Doku: CHANGELOG.md (Fixed, umlautfrei: `POST /checks/{id}/run` auf einen Check, der waehrend des Laufs geloescht wird, antwortet 404 statt 500)
Beweis: origin/feature/monitoring-io@13f340e4 · Code-Lesung `app/routers/checks.py:363-368` (`check.to_dict` auf das abgelaufene, gelöschte Objekt); ausführbar: Test (a) rot auf HEAD
Orakel: contract — ein Lauf eines gelöschten Checks antwortet wie jeder andere Zugriff auf ihn
Dedup-Key: ref:monitoring:io-nits
HEAD: 13f340e4

### T13 — Statuswechsel erst nach dem Speichern loggen (R-0799)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_agent_report.py, apps/monitoring/tests/test_execute_check.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @06f881fc 2026-10-28T16:43:00+01:00
Review: approve (.ah-out/review/monitoring-hardening-2/T13.verdict.json)
Änderung: `apply_result` (`app/check_engine.py:167`) loggt nicht mehr (`:244-253` entfällt, der Docstring `:180-183` nennt die Log-Zeile nicht mehr); neue öffentliche Funktion `log_transition(name, old_status, new_status, message)` in `app/check_engine.py`, Logger `monitor.engine`, Text wie heute `"Check '%s': %s -> %s (%s)"`. Bedingung und Meldung wie heute (`:242-253`): Es gab vorher einen Zustand (`state is not None` vor `apply_result`) und `eff_status != old_status`; die Meldung ist das `message` des Ergebnisses. `execute_check` ruft sie nach `db.commit()` (`:368`); der Push-Pfad merkt den Wechsel eines Checks erst nach dem Ende seines Savepoints (neben `check_lines`, `app/routers/agent.py:256`) und loggt nach dem gemeinsamen Commit (`:261-270`). Tests: (a) in `tests/test_agent_report.py` wie `test_a_database_error_costs_only_its_check` (`:846-890`, beide Parameter), aber beide Checks vorher `ok` → genau eine Zeile `ok -> critical` unter `monitor.engine`, die von `chk-b`; (b) in `tests/test_execute_check.py`: `db.commit` scheitert (Naht über die Session-Fabrik wie `_wire_counting`) → keine Zeile `->`, die ERROR-Zeile „execute_check(c1) fehlgeschlagen“ kommt; Erfolgsfall mit Wechsel → genau eine Zeile. `test_status_transition_is_logged_on_the_push_path` (`:800-836`) bleibt unverändert grün. Zuerst rot: (a), (b) auf HEAD.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py tests/test_execute_check.py tests/test_check_engine.py
Doku: keine (die Doku nennt den Zeitpunkt der Zeile nicht; vorher `grep -n "\-> \|Statuswechsel\|transition" docs/developer/monitoring.html`)
Abhängt von: T12
Beweis: origin/feature/monitoring-io@13f340e4 · Code-Lesung `app/check_engine.py:247-253` (Log in `apply_result`) vor `app/routers/agent.py:178` (Savepoint) und `app/check_engine.py:368` (Commit); ausführbar: Tests (a), (b) rot auf HEAD
Orakel: contract — eine Log-Zeile je gespeichertem Wechsel, keine für einen verworfenen
Dedup-Key: ref:monitoring:io-nits
HEAD: 13f340e4
