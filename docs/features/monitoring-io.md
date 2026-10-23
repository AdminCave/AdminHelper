<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: I/O ohne gehaltene DB-Verbindung, begrenzter HTTP-Check, VictoriaMetrics-Fehler, Agent-Report, Cooldown, Glocken-Titel

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/monitoring-io.md`. Roadmap R-0615, R-0616 (Paket „monitoring-io“), R-0631, R-0632, R-0633, R-0635, R-0636,
R-0637 (alle BUG, Komponente monitoring).

## Problem / Motivation

1. **VictoriaMetrics-Schreiben und Checks halten Verbindungen und Threads (R-0615).** `VictoriaClient.write`
   (`apps/monitoring/app/core/victoria.py:109-135`) schreibt synchron: drei Versuche mit je 10 s Timeout
   (`:107`) und `time.sleep` dazwischen (`:135`), zusammen bis ~31 s. `execute_check`
   (`apps/monitoring/app/check_engine.py:275-370`) öffnet die Session in `:277`, liest den Check und hält die
   Transaktion (und damit eine Pool-Verbindung) über `checker.run` (`:315`) und `victoria.write_check_result`
   (`:329`) bis zum Commit in `:354`. Der Scheduler hat 30 Worker (`apps/monitoring/app/scheduler.py:39`), der Pool
   30 Verbindungen (`apps/monitoring/app/core/database.py:14-15`). Hängt VictoriaMetrics oder ein Check-Ziel, sind
   alle Verbindungen belegt, und Agent-Reports und API-Anfragen scheitern. `POST /checks/{id}/run`
   (`apps/monitoring/app/routers/checks.py:341-365`) hält die Request-Session aus `:343` offen und ruft
   `execute_check` (`:361`) mit einer zweiten Session, also zwei Verbindungen über den ganzen Lauf. Auch
   `GET /checks/{id}/metrics` (`:427-492`) hält die Request-Transaktion aus `:433` über bis zu drei
   `query_range`-Aufrufe (`:470`, `:477`, `:482`) mit je 10 s Timeout. Der Push-Pfad hält beim Schreiben keine
   Verbindung (die Commits in `apps/monitoring/app/routers/agent.py:93` und
   `apps/monitoring/app/template_suggestions.py:91` liegen davor, der zweite Write in `routers/agent.py:310` nach dem
   Commit in `:299`), blockiert aber den Request zweimal (`:181`, `:310`), bis ~63 s; der Server-Proxy wartet 30 s
   (`apps/server/app/modules/monitoring_proxy/router.py:43`).
2. **HTTP-Check ohne Größenlimit und ohne Gesamtfrist (R-0616).** `HttpChecker.run`
   (`apps/monitoring/app/checkers/http.py:21-117`) holt jede Antwort mit `client.request` (`:53`, `:81`), also samt
   ganzem Body, auch ohne `search_string`; nur `:103` liest ihn (`resp.text`). Der Timeout aus der Konfiguration (bis
   300 s, `apps/monitoring/app/check_configs.py:47`) gilt je Phase und Anfrage: httpx-Doku, „Read timeout … the
   maximum duration to wait for a chunk of data to be received“, ein einzelner Wert setzt alle vier Phasen. Mit bis
   zu fünf Redirects (`http.py:15`) sind es sechs Anfragen; ein Server, der den Body tröpfeln lässt, hält den Check
   unbegrenzt. Das läuft im Scheduler-Worker unter offener Transaktion (1.) und synchron bei `POST /checks/{id}/run`.
3. **Cooldown bricht alle Regeln (R-0631).** `_is_in_cooldown` (`apps/monitoring/app/alerter.py:451-464`) rechnet
   `utcnow_naive() - timedelta(minutes=rule.cooldown_minutes)` (`:453`). Das Schema erlaubt `ge=0` bis int32
   (`apps/monitoring/app/schemas.py:73`, `:83`, `:138`; `apps/monitoring/app/core/bounds.py:33`). Probe
   (Python 3.13.5, `datetime(2026, 10, 22, 12, 0)`): 1 000 000 000 Minuten gehen, 1 070 000 000 und 2 147 483 647
   werfen `OverflowError`, die Grenze liegt bei 1 065 471 120 Minuten. Dazu ist die Spalte nullable
   (`apps/monitoring/app/models.py:147`), und `PUT /alerts/{id}` mit `"cooldown_minutes": null` setzt `None`
   (`apps/monitoring/app/routers/alerts.py:107`): `timedelta(minutes=None)` wirft `TypeError`. Aufgerufen wird
   `_is_in_cooldown` in `process_alert` vor dem `try` je Regel (`alerter.py:195-203`) und im Sammelversand in einer
   List-Comprehension (`apps/monitoring/app/alert_bundle.py:362`), beides nach dem Claim-Commit: Die Ausnahme bricht
   den Versand für alle Regeln und die Glocke ab, die Meldung ist verloren.
4. **Eigene Helfer im Router-Metrikpfad (R-0632).** Der Push-Handler hat `_num` (`routers/agent.py:35-55`), das
   Zahl-Strings annimmt, und `_capped` (`:67-70`), das Nicht-Objekte durchlässt. Probe: `_num("97")` = `97.0`,
   `agent_number("97")` = `None` (der Checker bewertet Zahl-Strings seit R-0517 nicht); `_capped(["x", {}])` =
   `["x", {}]`, `capped_objects(["x", {}])` = `[{}]`; ein String in `disks` wirft im Router `AttributeError`, und das
   breite `except` (`:174-179`) setzt `lines = []`: alle Metriken des Reports fehlen. `_MAX_REPORT_ITEMS`
   (`:61`) und `_MAX_REPORT_ENTRIES` (`apps/monitoring/app/checkers/agent.py:124-126`) sind dieselbe Grenze zweimal.
5. **CPU/RAM doppelt, SMART-Zeilen ungelesen (R-0633).** Der Router schreibt `monitor_agent_cpu_percent` und
   `monitor_agent_memory_percent` mit `server_id` (`routers/agent.py:130-133`), der Checker `agent_resources` dieselben
   Namen als Messwerte mit `check_id`, `check_type`, `name`, `server_id` (`checkers/agent.py:361`, `:369`). Der
   Metrik-Endpunkt filtert `agent_resources` nur nach `server_id` (`routers/checks.py:444-457`). Probe gegen das
   Image aus `docker-compose.yml` (VictoriaMetrics v1.144.0, Digest `dc030542…`), zwei Zeilen, eine je Quelle:
   `{__name__=~"monitor_agent_cpu_percent_value",server_id="srv-1"}` liefert zwei Serien. Der Desktop beschriftet
   beide gleich (`apps/desktop/ui/src/lib/models/monitoring.ts:154-158`) und schlüsselt die Liste der aktuellen Werte
   nach der Beschriftung (`apps/desktop/ui/src/components/monitoring/MonCurrentValues.svelte:43`); Svelte 5.56.2 wirft
   bei doppeltem Schlüssel auch im Produktions-Build (`each_key_duplicate`, `svelte/src/internal/client/dom/blocks/each.js`,
   `errors.js`). Die SMART-Zeilen des Routers (`routers/agent.py:154-172`, nur `server_id` und `device`) liest
   niemand: `smart_health` filtert nach `check_id` (`routers/checks.py:452-457`, nicht in `agent_types`), und der
   Checker schreibt dieselben Namen mit Check-Labels (`apps/monitoring/app/checkers/smart.py:239-244`).
6. **Report-Auswertung ohne Savepoint (R-0635).** Die Schleife über die Push-Checks (`routers/agent.py:212-295`)
   isoliert je Check mit `except Exception: continue` (`:293-295`) in einer gemeinsamen Transaktion. Ein DB-Fehler
   (Deadlock, Abbruch am `FOR UPDATE`, ein gescheiterter Flush) lässt die Session in einem Zustand, in dem jeder
   folgende Check mit `PendingRollbackError` scheitert und der Commit (`:297-306`) mit 500 endet; die Ergebnisse
   des ganzen Reports sind weg. Probe (SQLAlchemy 2.0.54, SQLite in-memory, `StaticPool`, dreimal identisch): ohne
   Savepoint scheitern der zweite Eintrag und der Commit (`PendingRollbackError`), mit `with db.begin_nested():` je
   Eintrag fällt nur der fehlerhafte weg, der Commit geht durch.
7. **`query_range`-Fehler sehen aus wie „keine Daten“ (R-0636).** `query_range` (`victoria.py:194-210`) gibt bei
   jedem Fehler `{"status": "error", "data": {"result": []}}` zurück (`:210`). Die Aufrufer lesen nur `data.result`:
   der Metrik-Endpunkt antwortet 200 mit leeren Reihen (`routers/checks.py:470-491`), `disk_forecast` meldet „No disk
   history yet“ (`apps/monitoring/app/checkers/forecast.py:64-69`). Der Befund „nicht unterscheidbar“ stimmt nur für
   die Aufrufer: die Rückgabe trägt den Fehler schon. `write` wiederholt jeden `httpx.HTTPError` (`victoria.py:122-135`),
   auch ein 4xx aus `raise_for_status` (`:125`). Probe gegen das Image aus 5.: eine ungültige Zeile im Body ergibt
   HTTP 400 für den Schreibvorgang („cannot process influx line protocol data: incorrect influx line …“), ein
   zweiter Versuch mit demselben Body kann nicht anders ausgehen; ein ungültiger Query HTTP 422 mit
   `{"status":"error","errorType":"422",…}`.
8. **Glocken-Titel über 512 Zeichen (R-0637).** `_emit_to_hub` schickt `msg["subject"]` als `title`
   (`alerter.py:404`), gebaut als `"[AdminHelper Monitor] <STUFE>: {check.name}"` (`:498`, `:510`); `name` hat
   keine Längengrenze (`schemas.py:26`). Der Hub nimmt `title` bis 512 Zeichen
   (`apps/server/app/modules/notifications/schemas.py:27`). Der Präfix hat 32 Zeichen (CRITICAL, RECOVERY): ab 481
   Zeichen Name antwortet `/api/internal/events` mit 422, Glocke, Hub-Mail und Event-Hook fehlen, im Log steht nur
   „Hub-Emit abgelehnt“ (`alerter.py:432-434`). `alert_bundle` spiegelt die Grenze `source_ids` von Hand
   (`alert_bundle.py:54`), für den Titel gibt es keine.

## Ziel & Nicht-Ziele

Ziel:
- Kein Check, kein manueller Lauf und keine Metrik-Abfrage hält während Netzwerk-I/O (Checker, VictoriaMetrics)
  eine Pool-Verbindung.
- `VictoriaClient.write` kehrt sofort zurück: Zeilen gehen in einen begrenzten Puffer, ein eigener Thread schreibt
  sie; 4xx wird nicht wiederholt; beim Herunterfahren wird der Puffer begrenzt geleert.
- Der HTTP-Check liest den Body nur mit `search_string` und höchstens 1 MiB; `timeout` ist eine Frist über alle Hops
  und das Lesen.
- Ein Metrik-Abruf bei nicht erreichbarem VictoriaMetrics antwortet 502, `disk_forecast` meldet das mit eigenem Text.
- Je Metrik eine Quelle: CPU/RAM nur vom Push-Handler je Server, SMART nur vom Checker; der Endpunkt liest für
  `agent_resources` nur die Serien des Push-Handlers.
- Der Router nimmt die Helfer des Checkers (`agent_number`, `capped_objects`, `entry_text`), ein kaputter
  Listeneintrag kostet nur sich selbst.
- Ein DB-Fehler bei einem Check eines Reports kostet nur diesen Check.
- `_is_in_cooldown` wirft für keinen gespeicherten Wert (beliebig großes `cooldown_minutes`, `NULL`).
- Der Glocken-Titel hält die Grenze des Hubs ein; ein Paritätstest hält beide Zahlen gleich.

Nicht-Ziele (YAGNI):
- Keine neue Eingabegrenze an `cooldown_minutes` oder `name` (beides oasdiff-ERR, offene Frage 1 und 2).
- `POST /checks/{id}/run` bleibt synchron; bei einem `timeout` über ~25 s kann der Server-Proxy (30 s) die Antwort
  abschneiden, der Lauf schreibt seinen Zustand trotzdem.
- Keine Persistenz des Schreib-Puffers: was beim harten Abbruch des Prozesses darin liegt, fehlt.
- Kein Umbau des Alert-Protokolls (R-0693) und der Typ-Tabellen (R-0694); kein `pattern=` statt `regex=` (R-0697).
- Der Metrik-Endpunkt filtert die übrigen Agent-Typen (`service_process`, `docker_health`, `proxmox_backup`,
  `zfs_health`, `agent_ping`) weiter nach `server_id` (`routers/checks.py:444-457`); zwei Checks desselben Typs auf
  einem Server liefern so ebenfalls zwei gleich beschriftete Serien. Eigener Fund, Vorschlag einer neuen Zeile.
- Der Router behält seine Rückfallwerte für Platten ohne `mount` (`"/"`) und Sensoren ohne Namen (`"unknown"`);
  dass `"/"` mit der Wurzel kollidiert (der Checker nimmt `"?"`, `checkers/agent.py:30`), ist ein eigener Fund.
- Keine Desktop-Änderung: nach T4 liefert der Endpunkt je Beschriftung eine Serie. Ein eindeutiger `each`-Schlüssel
  in `MonCurrentValues.svelte` wäre zusätzliche Absicherung (Desktop, eigene Zeile).
- Alert-Dispatch: `process_alert` hält während Webhook/SMTP eine Verbindung (nach `_build_message`), begrenzt auf
  die fünf Threads von `_alert_pool` (`check_engine.py:34`); bleibt.

## Betroffene Komponenten & Dateien

| Task | Zeile | Dateien |
|---|---|---|
| T1 | R-0615 | `apps/monitoring/app/check_engine.py`, `apps/monitoring/app/routers/checks.py`, `apps/monitoring/tests/test_execute_check.py`, `apps/monitoring/tests/test_checks_metrics.py`, `CHANGELOG.md` |
| T2 | R-0615, R-0636 | `apps/monitoring/app/core/victoria.py`, `apps/monitoring/app/main.py`, `apps/monitoring/tests/test_victoria.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`, `CHANGELOG.md` |
| T3 | R-0636 | `apps/monitoring/app/routers/checks.py`, `apps/monitoring/app/checkers/forecast.py`, `apps/monitoring/tests/test_checks_metrics.py`, `apps/monitoring/tests/test_checker_forecast.py`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |
| T4 | R-0633 | `apps/monitoring/app/checkers/agent.py`, `apps/monitoring/app/routers/checks.py`, `apps/monitoring/tests/test_agent_resources_checker.py`, `apps/monitoring/tests/test_agent_report.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`, `CHANGELOG.md` |
| T5 | R-0633 | `apps/monitoring/app/routers/agent.py`, `apps/monitoring/app/core/victoria.py`, `apps/monitoring/tests/test_agent_report.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`, `CHANGELOG.md` |
| T6 | R-0632 | `apps/monitoring/app/routers/agent.py`, `apps/monitoring/app/checkers/agent.py`, `apps/monitoring/tests/test_agent_report.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`, `CHANGELOG.md` |
| T7 | R-0635 | `apps/monitoring/app/routers/agent.py`, `apps/monitoring/tests/test_agent_report.py`, `CHANGELOG.md` |
| T8 | R-0631 | `apps/monitoring/app/alerter.py`, `apps/monitoring/tests/test_alerter.py`, `CHANGELOG.md` |
| T9 | R-0637 | `apps/monitoring/app/alerter.py`, `apps/monitoring/tests/test_alerter_hub.py`, `CHANGELOG.md` |
| T10 | R-0616 | `apps/monitoring/app/checkers/http.py`, `apps/monitoring/tests/test_http_checker.py`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |

Auf `scripts/dev/review-risk.txt` stehen `check_engine.py` (T1), `routers/agent.py` (T5, T6, T7) und `alerter.py`
(T8, T9): diese Tasks bekommen zusätzlich `security`. T9 liest `apps/server/app/modules/notifications/schemas.py`
im Paritätstest, ändert es nicht.

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld, keine neue Route, kein Request-Schema geändert; `tests/openapi.snapshot.json`
bleibt (keine Route und kein Docstring einer Route ändert sich). Verhalten an der API:
- `GET /checks/{id}/metrics` antwortet 502 `{"detail": "Metrics store unavailable"}`, wenn eine der Abfragen
  scheitert (T3), und liefert für `agent_resources` nur die Serien ohne `check_id` (T4). FastAPI nimmt geworfene
  `HTTPException`-Codes nicht ins Schema auf. Der Server-Proxy reicht den Status durch
  (`apps/server/app/modules/monitoring_proxy/router.py:158-160`); der Desktop zeigt in der aufgeklappten Grafik den
  Fehlertext (`apps/desktop/ui/src/components/monitoring/section/ExpandChart.svelte:43-46`), Sparkline und Heartbeat
  bleiben leer wie bei „keine Daten“ (`MonSparkline.svelte:46-48`). Keine Desktop-Änderung nötig.
- `POST /agent/{id}/report`: Antwortfelder bleiben; `metricsWritten` zählt die Zeilen, die der Handler dem Puffer
  übergibt (T2), ohne SMART-Zeilen (T5) und ohne Zahl-Strings (T6).
- VictoriaMetrics: die Serien `monitor_agent_cpu_percent`/`monitor_agent_memory_percent` mit Check-Labels und
  `monitor_smart_*` mit nur `server_id`/`device` kommen nicht mehr dazu; alte bleiben bis zur Retention
  (`VM_RETENTION`, Default 90d) und werden für `agent_resources` nicht mehr gelesen.
Kein Vertrags-Drift zu Server, Web, Agent; Desktop wie oben.

## Externe Integrationen

- **VictoriaMetrics** (`docs.victoriametrics.com/victoriametrics/integrations/influxdb/`, gelesen 2026-10-22):
  „An arbitrary number of lines delimited by ‘\n’ … can be sent in a single request“; „The maximum request size for
  Influx HTTP endpoints is limited by -influx.maxRequestSize (default: 64MB)“. Statuscodes von `/write` und
  `/api/v1/query_range` nennt die Doku nicht (auch nicht `url-examples/`); belegt durch die Probe gegen das gepinnte
  Image (`victoriametrics/victoria-metrics:v1.144.0@sha256:dc030542…`, eigener Container, danach entfernt):
  `/write` 204, ungültige Zeile 400, ungültiger Query/Step 422 mit JSON `status: error`;
  `{…,server_id="srv-1",check_id=""}` liefert nur die Serie ohne `check_id`. MetricsQL: „MetricsQL is
  backwards-compatible with PromQL“ (`docs.victoriametrics.com/victoriametrics/metricsql/`).
- **Prometheus-Selektoren** (`prometheus.io/docs/prometheus/latest/querying/basics/`): „Label matchers that match
  empty label values also select all time series that do not have the specific label set at all.“ Fehlerformat
  (`…/querying/api/`): `400` falsche Parameter, `422` nicht ausführbarer Ausdruck, `503` Timeout/Abbruch.
- **httpx 0.28.1** (`python-httpx.org/advanced/timeouts/`): vier Phasen connect/read/write/pool, ein Float setzt
  alle, „Read … the maximum duration to wait for a chunk of data“; eine Gesamtfrist nennt die Seite nicht.
  `Response.iter_bytes()` liefert dekodierte (entpackte) Bytes, `Client.stream()` liest den Body nicht vorab.
- **SQLAlchemy 2.0** `Session.begin_nested()` (SAVEPOINT): Probe oben (6.); auf Postgres ein echter `SAVEPOINT`,
  den nur der Stack fährt (`Heavy:`).
- **oasdiff 1.32.0** (lokal): `maximum` 525600 an `cooldown_minutes` meldet `request-property-max-decreased` (ERR, vier
  Stellen), `maxLength` an `CheckCreate.name` `request-property-max-length-set` (ERR); beide stehen nicht in
  `scripts/dev/oasdiff-severity.levels`.

## Trade-offs & Alternativen

1. **Schreiben (T2).** (a) Puffer im Prozess + ein Schreib-Thread — **Empfehlung**: kein Aufrufer wartet, die
   Grenze ist ein Wert. (b) Kürzere Timeouts, keine Wiederholung — Aufrufer warten weiter bis zu einigen Sekunden je
   Write. (c) Writes in den Alert-Pool — teilt fünf Threads mit Webhook/SMTP. Puffer 100 000 Zeilen (etwa eine Stunde
   bei 250 Servern), Stapel bis 10 000 Zeilen je POST (weit unter 64 MB); ist der Puffer voll, wird der neue Stapel
   verworfen und gezählt (WARNING höchstens einmal je Minute mit der Zahl). Heute gehen dieselben Zeilen nach drei
   Versuchen verloren; der Puffer hält sie bis zu seiner Grenze. Der Thread startet beim ersten `write`; der Lifespan
   ruft beim Herunterfahren `close()` (höchstens 5 s Leeren).
2. **Wiederholen (T2).** Timeout, Verbindungsfehler und 5xx: drei Versuche wie bisher (0,5 s und 1 s Pause, jetzt im
   Schreib-Thread). 4xx: kein zweiter Versuch, eine WARNING mit Status und den ersten 200 Zeichen der Antwort (VM
   nennt dort die fehlerhafte Zeile).
3. **Transaktion vor I/O beenden (T1).** `execute_check` liest den Check, merkt sich, was Lauf und Metrik brauchen,
   und beendet die Lesetransaktion vor `checker.run`; danach Lock auf den State, Check neu lesen, `apply_result`,
   Commit. Ein in der Zwischenzeit gelöschter Check: Ergebnis verwerfen (DEBUG), kein Exception-Log. Alternative
   zwei Sessions — dasselbe mit mehr Code. `run_check_now` und `get_check_metrics` beenden die Request-Transaktion
   vor `execute_check` bzw. den Abfragen.
4. **Fehler von `query_range` (T3).** (a) Aufrufer prüfen `status == "error"` (die vorhandene Rückgabe, gepinnt von
   `tests/test_victoria.py::test_query_range_non_json_returns_empty_fallback`) — **Empfehlung**, kein Test fällt
   weg. (b) Eine eigene Exception — zwingt beide Aufrufer zum `try`, ändert den gepinnten Rückgabewert. Geprüft wird
   `== "error"`, nicht `!= "success"`: die Fakes der Tests liefern kein `status`. Der Endpunkt antwortet 502, sobald
   eine der bis zu drei Abfragen scheitert (keine Teilergebnisse).
5. **Eine Quelle je Metrik (T4).** (a) Der Push-Handler bleibt Quelle für CPU/RAM (je Server, auch ohne Check), der
   Checker schreibt sie nicht mehr; der Endpunkt liest für `agent_resources` mit `check_id=""` — **Empfehlung**, wie
   schon bei Platten und Temperaturen (`checkers/agent.py:439-441`, `:464-465`), und die alten Serien mit Check-Labels
   fallen sofort aus der Anzeige. (b) Der Router lässt CPU/RAM weg — ohne `agent_resources`-Check gäbe es keine
   Historie, Platten/Temperaturen bräuchten weiter `server_id`. `agent_resources` schreibt danach nur seinen Status
   (keine Dauer, wie andere Push-Checks ohne Messwerte).
6. **Helfer (T6).** Der Router importiert `agent_number`, `capped_objects`, `entry_text` aus `app.checkers.agent`
   (er importiert von dort schon `EXCLUDED_FSTYPES`, `routers/agent.py:21`); ein neutrales Modul bringt nichts, die
   Importrichtung Router → Checker besteht. Zahl-Strings schreibt der Router danach nicht mehr (wie der Checker).
7. **Cooldown (T8).** (a) `_is_in_cooldown` wird total: ein Fenster, das über den Kalenderanfang reicht, zählt jeden
   früheren erfolgreichen Versand (Grenze `datetime.min`); `NULL` gilt als der Default 30 (Schema-, Template- und
   Spalten-Default, Admin-Doku „Default 30“) — **Empfehlung**, deckt `process_alert` und den Sammelversand an einer
   Stelle. (b) Aufruf in die Isolation je Regel ziehen — ein DB-Fehler vergiftet die Transaktion ohnehin, und das
   `except` müsste „senden oder nicht“ wählen. (c) Obergrenze im Schema — oasdiff-ERR (offene Frage 1).
8. **Titel (T9).** Titel über `HUB_TITLE_MAX` = 512 Zeichen: die ersten 511 plus `…`, nur im Hub-Event; Betreff
   von Mail und Webhook bleiben. Alternative `name` begrenzen: oasdiff-ERR (offene Frage 2).
9. **HTTP-Check (T10).** `client.stream` je Hop; Frist = Start + `timeout`, geprüft vor jedem Hop und nach jedem
   Chunk, jede Anfrage mit der Restzeit als httpx-Timeout. Body nur mit `search_string`, bis 1 MiB, dekodiert mit
   `resp.encoding` (wie `resp.text`), Rest ungelesen; nicht gefunden in einem gekürzten Body: „… not found in the
   first 1 MiB of the response“. `http_response_ms` misst bis zu dem, was der Check bewertet (Header, mit
   `search_string` der gelesene Teil); ohne `search_string` fällt die Download-Zeit weg. Ein strikter Deckel (Lauf in
   einem eigenen Thread mit `join(timeout)`) ließe hängende Threads zurück.

## Risiken & Rollback

- T2: Der Puffer liegt im Speicher; ein harter Abbruch verliert, was darin liegt (im Normalbetrieb Sekunden, bei
  hängendem VictoriaMetrics bis 100 000 Zeilen, die heute nach drei Versuchen ebenfalls verloren gingen).
  Single-Worker-Invariante (`apps/monitoring/app/main.py:88-93`): ein Schreib-Thread je Prozess.
- T2: Tests, die `victoria.write` nicht ersetzen, starten den Schreib-Thread; er schreibt ins Leere und loggt
  WARNINGs, blockiert aber keinen Test mehr (heute warten sie synchron auf drei Versuche).
- T10: Die Frist kann eine laufende Netzwerkphase überziehen (höchstens deren Restzeit; bei mehreren Adressen je
  Adresse ein Connect, `apps/monitoring/app/core/ssrf.py:242-253`), dazu die DNS-Prüfung je Hop mit eigenem Deckel
  (`ssrf.py:46`). Gepackte Bodies: `iter_bytes` entpackt je Rohstück; ein Stück bleibt im Speicher, die 1 MiB
  zählen entpackt. Heute wird der ganze Body gelesen.
- T7: Auf Postgres läuft je Check ein `SAVEPOINT`/`RELEASE`; die Unit-Suite fährt SQLite. Deshalb `Heavy:`.
- T4/T5: Wer VictoriaMetrics direkt abfragt, findet die Check-gelabelten CPU/RAM-Serien und die Router-SMART-Serien
  nicht mehr fortgeschrieben (CHANGELOG).
- Rollback: jede Task ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T2: `docs/developer/monitoring.html` VictoriaMetrics-Abschnitt (Puffer, Wiederholen, `metricsWritten`) DE+EN;
CHANGELOG. T3: `docs/admin/monitoring.html` Disk-Forecast-Absatz (`:227`, „Metrics store unavailable“, 502 der
Grafik) DE+EN; CHANGELOG. T4: `docs/developer/monitoring.html:264` (`agent_resources` ohne eigene Messwerte, Lesen mit
`check_id=""`) DE+EN; CHANGELOG. T5, T6: `docs/developer/monitoring.html:145` (keine SMART-Zeilen des Handlers; Zahlen
nur als JSON-Zahl, Einträge, die kein Objekt sind, übersprungen) DE+EN; CHANGELOG. T10: `docs/admin/monitoring.html:149`
(`timeout` als Frist über Redirects und Lesen, `search_string` in den ersten 1 MiB) DE+EN; CHANGELOG. T1, T7, T8, T9:
nur CHANGELOG.

## Offene Fragen

1. **Obergrenze für `cooldown_minutes` im Schema?** Empfehlung: nein. T8 behebt die Ursache für jeden Wert; eine
   Grenze (etwa 525 600) wäre oasdiff-ERR (`request-property-max-decreased`, POST/PUT `/alerts`, POST/PUT
   `/templates`) und lehnte Werte ab, die heute gehen. Keine Task hängt daran; bei „ja“ eine eigene Task mit
   Snapshot-Update und Kevins Freigabe des ERR.
2. **Längengrenze für den Check-Namen?** Empfehlung: nein. T9 kürzt nur den Glocken-Titel (vertragsneutral); eine
   `max_length` an `CheckCreate.name` wäre oasdiff-ERR (`request-property-max-length-set`). Keine Task hängt daran.
