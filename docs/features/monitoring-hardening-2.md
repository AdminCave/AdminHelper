<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Metrik-Filter, Mount-Default, Speicher- und Eingabegrenzen, Nacharbeiten aus monitoring-io

Stand des Codes: `origin/feature/monitoring-io@13f340e4` (PR #265, noch nicht auf `main`). Der Branch zweigt bewusst
dort ab, weil fast jede Task Code aus monitoring-io berührt; gebaut wird erst nach dessen Merge. Alle `datei:zeile`
beziehen sich auf diesen Stand. Ledger: `tasks/monitoring-hardening-2.md`. Roadmap R-0749 (T1), R-0753 (T2), R-0774
(T3), R-0799 (T5, T7, T10–T13, Teile von T2, T4, T8); T4, T6, T8 und T9 gehören zum Paket (Kevin 2026-10-22).
Pfade ohne Präfix liegen unter `apps/monitoring/`.

## Problem / Motivation

1. **Metrik-Abruf filtert fünf Check-Typen nur nach Server (R-0749).** `get_check_metrics`
   (`app/routers/checks.py:440-517`) fragt für `agent_ping`, `service_process`, `docker_health`, `proxmox_backup` und
   `zfs_health` nach `server_id` statt nach `check_id` (`:462-475`); der Kommentar `:460-461` sagt, diese Serien
   schreibe der Agent-Router ohne `check_id`. Das stimmt nur noch für `agent_resources` (`:476-482`): Die fünf
   anderen Typen schreiben ihre Werte über `CheckResult`-Metriken mit Check-Labels
   (`app/checkers/agent.py:236`, `:242`, `:690`; `app/checkers/plugins.py:139`, `:219`, `:438`; im Push-Pfad
   `app/routers/agent.py:226-234` über `build_check_result_lines`). Zwei Checks desselben Typs auf einem Server
   bekommen deshalb dieselben Reihen, beide doppelt. Die Serien trugen schon vor monitoring-io `check_id`; ein
   Wechsel auf `check_id` verliert keine Historie.
2. **Mountlose Platte landet in der Reihe von `/` (R-0753).** Der Agent-Push schreibt eine Platte ohne lesbares
   `mount` mit `mount=/` (`app/routers/agent.py:111`), der Checker zeigt sie als `?` (`app/checkers/agent.py:30`,
   `:426`, `:504`, `:511`). `disk_forecast` gruppiert nach `mount` (`app/checkers/forecast.py:82`), so mischt sich
   eine mountlose Platte in die Füllraten-Reihe der Root-Platte.
3. **Ungepaarte UTF-16-Surrogate (R-0774).** JSON darf `"\ud800"` schreiben, Python liest daraus einen String mit
   einem einzelnen Surrogat. Das Monitoring weist nur NUL ab (`app/core/bounds.py:43-98`). Ein solcher String
   (a) lässt sich nicht als UTF-8 binden: Ein Check-Name scheitert beim Speichern, ein Wert in `config` wird über
   `json.dumps` (`app/routers/checks.py:165`, `:258`, `:326`; `app/template_sync.py:302`, `:456`) maskiert
   gespeichert, und jede spätere Antwort mit diesem Check endet mit HTTP 500; (b) im Agent-Report landet er als
   Tag-Wert in einer Zeile für VictoriaMetrics, `_send` (`app/core/victoria.py:199`) kodiert den Stapel als UTF-8
   und scheitert mit `UnicodeEncodeError`; `_run` (`:183-187`) loggt, und der ganze Stapel ist verloren, samt den
   Zeilen anderer Server. Beleg: Probe an 13f340e4 (Python 3.13.5): Zeile mit Surrogat-Mount im Stapel mit Zeilen
   eines zweiten Servers, gesendete Stapel leer. Der Server hat die Regel auf `feature/server-hardening`
   (`apps/server/app/core/bounds.py:51-125`, Commit `908a84b6`): `_unstorable`, `_find_unstorable`,
   `RequestModel._reject_unstorable_anywhere`, Text „must not contain a lone surrogate (U+D800 to U+DFFF)“.
4. **Schreibpuffer ohne Obergrenze in Bytes (T4).** `VictoriaClient.write` (`app/core/victoria.py:126-157`) zählt
   Zeilen (`_MAX_PENDING_LINES`, `:21`), nicht ihren Umfang. Eine Zeile trägt Tag-Werte aus dem Agent-Report (Mount,
   Sensor), die `_esc_tag` (`:44-55`) maskiert, aber nicht kürzt; ein Report darf bis zur Body-Grenze des Gateways
   (`apps/gateway/nginx.conf:85`, 10 MiB) groß sein, Listen bis 500 Einträge (`app/checkers/agent.py:127`). Wie viel
   Speicher der Puffer hält, solange VictoriaMetrics nicht annimmt, folgt damit nicht aus den 100 000 Zeilen. Der
   Kommentar `:19-20` beschreibt den Puffer als „about an hour of agent reports from 250 servers“; das ist eine
   Rechengröße, keine Zusage.
5. **Entpacken ohne Obergrenze im HTTP-Check (T6).** `_read_head` (`app/checkers/http.py:145-160`) liest
   `resp.iter_bytes()` (`:149`). httpx 0.28.1 entpackt jedes rohe Stück (httpcore liest bis 64 KiB je Stück) in
   einem Aufruf ohne Längengrenze (`httpx/_decoders.py`, `GZipDecoder.decode`, `zlib.decompressobj().decompress(data)`;
   mehrere Kodierungen kettet `MultiDecoder`). Die Grenze von 1 MiB (`:18`) greift erst nach dem Entpacken eines
   Stücks; der Speicher beim Lesen folgt dem entpackten Umfang eines Stücks, nicht der Grenze. Probe an 13f340e4
   (Python 3.13.5, httpx 0.28.1, `tracemalloc`, echte `_read_head`): Der Spitzenwert wächst mit dem entpackten
   Umfang des ersten Stücks und liegt um ein Vielfaches über 1 MiB.
6. **Steuerzeichen im Check-Namen (T8, T9).** Der Betreff einer Alert-Meldung ist
   `[AdminHelper Monitor] <STUFE>: <Check-Name>` (`app/alerter.py:515`, `:527`), `_send_email` setzt ihn unverändert
   (`:677`). Ein Zeilenumbruch im Namen macht den Betreff mehrzeilig; Pythons `email`-Paket verweigert dann das
   Serialisieren (`HeaderParseError`), die Mail geht nicht raus, das Alert-Log zeigt `SMTP error (HeaderParseError)`.
   Probe (Python 3.13.5 und 3.12.13 wie im Image, identisch): `\r\n`, `\n`, `\r`, `\v`, `\f` und `\x1c`–`\x1e` im
   Namen → Fehler beim Serialisieren; U+2028, C1-Zeichen und DEL gehen kodiert durch. Weder die Schemas
   (`app/schemas.py:24-26`, `:45-47`, `:87-89`) noch das Modell (`app/models.py:59`, `Column(String)`) begrenzen
   Namen. Template-Checks erben ihren Namen über `{{hostname}}`/`{{server_name}}` (`app/template_sync.py:73-83`), die
   `app/tag_sync.py:145-173` ohne API aus dem Server-Inventar übernimmt; dort prüft der Server `name`, `hostname`
   nicht. Ob gespeicherte Namen schon Steuerzeichen tragen, lässt sich ohne Betriebsdaten nicht sagen.
7. **Nacharbeiten aus den Prüfungen von monitoring-io (R-0799).** Am Code geprüft, je mit Stelle:
   - `app/core/victoria.py:145-157`: Verworfene Zeilen innerhalb von 60 s nach einer WARNING meldet erst der nächste
     Verwurf; leert sich der Puffer danach, bleibt ihre Zahl ungemeldet (T5).
   - `app/checkers/agent.py:124-126`: Der Kommentar nennt `capped_objects` „the one cap on a report list“, daneben
     kürzt `ServiceProcessChecker._capped` (`:626-629`) mit eigener Konstante 500 (T2).
   - `app/check_engine.py:247-253`: `apply_result` loggt den Statuswechsel, bevor der Savepoint im Push-Pfad
     (`app/routers/agent.py:178`) bzw. der Commit im Scheduler (`app/check_engine.py:368`) gelaufen ist; scheitert
     einer, steht im Log ein Wechsel, den es nicht gab (T13).
   - `app/routers/checks.py:363-368`: Löscht jemand den Check während `POST /checks/{id}/run`, endet die Antwort mit
     HTTP 500 (`check.to_dict` auf ein gelöschtes Objekt); `db.expire_all()` (`:366`) nach `db.rollback()` (`:363`)
     ist wirkungslos (T12).
   - Tests: `tests/test_victoria.py:44` (Docstring nennt einen SMART-Pfad des Agent-Routers, den es nicht mehr gibt),
     `tests/test_alerter.py:5-11` („Tested without a real DB“, `:40` baut SQLite im Speicher),
     `tests/test_execute_check.py:235-255` (prüft nicht, dass der Lauf lief und die DEBUG-Zeile kam),
     `tests/test_api_error_texts.py` (kein Fall für „Metrics store unavailable“, HTTP 502), `app/checkers/http.py`:
     Redirect-Zählung `:89-90` und Zeichensatz `:159` ohne Test (T5, T7, T8, T11, T12).
   - Doku und CHANGELOG: `docs/admin/monitoring.html:149` (EN `:149`) sagt, `timeout` gelte für den ganzen Check
     samt Redirects und Lesen; auf die Kopfzeilen wartet httpx aber je Lesevorgang bis zur Restzeit
     (`app/checkers/http.py:73`), eine Antwort, deren Kopf in kleinen Stücken kommt, hält den Check länger. `:227`
     (EN `:227`) sagt, die aufgeklappte Grafik zeige „diesen Fehler (HTTP 502)“; der Desktop zeigt „Fehler beim
     Laden“ / „Error loading“ (`apps/desktop/ui/src/components/monitoring/section/ExpandChart.svelte:80`,
     `apps/desktop/ui/src/lib/i18n/dictionaries.ts:674`, `:1464`). `docs/developer/monitoring.html:175` (EN `:175`)
     nennt die 1-MiB-Grenze der Suche nicht. `CHANGELOG.md:127` (Grafik), `:137-139` (eine Liste als `fstype` lässt
     den Eintrag nicht weg, sie zählt wie ein fehlender `fstype`), `:145-146` (ohne Savepoint endete ein Report mit
     HTTP 500 oder speicherte still nichts), `:160-161` (wie `:149`) (T10).

## Ziel & Nicht-Ziele

**Ziele**
- T1: Der Metrik-Abruf filtert nur `agent_resources` nach Server (mit `check_id=""`), jeder andere Typ nach
  `check_id`.
- T2: Eine Platte ohne lesbares `mount` heißt im Push-Pfad wie im Checker `?`; `docs/developer/monitoring.html:145`
  (EN `:145`, „mount dann /“) sagt dann `?`.
- T3: Kein String eines Request-Bodys und kein Agent-Report trägt ein ungepaartes Surrogat; Abweisung mit 422 und
  Ort, wie NUL heute, im Agent-Report nach der Liveness.
- T4: Der Schreibpuffer hat neben der Zeilen- eine Byte-Obergrenze (64 MiB, gemessen als gehaltener Speicher der
  Zeilen); was nicht passt, wird wie heute ganz verworfen und gezählt.
- T5: Die Zahl verworfener Zeilen kommt auch dann ins Log, wenn kein weiterer Verwurf folgt.
- T6: `_read_head` entpackt schrittweise und hält höchstens 1 MiB + 1 Byte entpackt; Ergebnis und Fehlertexte
  bleiben wie mit httpx.
- T8: Der Betreff einer Alert-Meldung ist einzeilig: Steuerzeichen (C0, DEL, C1) und U+2028/U+2029 werden zu
  Leerzeichen, wie `cap_agent_text` (`app/checkers/agent.py:67-83`) es für Agent-Texte tut; der Glocken-Titel folgt.
- T9 `[?]`: Neue Check-Namen ohne Steuerzeichen (C0, DEL), sonst 422, wie die FRP-Felder des Servers
  (`apps/server/app/modules/frp/schemas.py:24-36`).
- T5, T7, T10–T13: die Nacharbeiten aus Problem 7.

**Nicht-Ziele**
- Datenverlust bei einer 4xx-Antwort von VictoriaMetrics (`app/core/victoria.py:205-212`, ganzer Stapel verloren):
  R-0798, eigenes Vorhaben docs-residual-risks (Kevin 2026-10-22). Die Doku zum Puffer (`docs/developer/monitoring.html:263`) ändern T4
  und T5; der Satz zu 4xx bleibt.
- `docs/developer/monitoring.html:180` (`disk_forecast` fragt `monitor_agent_disk_percent_value` ohne
  `check_id=""`, `app/checkers/forecast.py:63`): kein Fehler. Plattenwerte schrieb nie ein Checker mit Check-Labels
  (der alte Checker nur CPU und RAM, `origin/main:apps/monitoring/app/checkers/agent.py:361`, `:369`), und `:265`
  nennt `check_id=""` für `agent_resources` schon.
- Default `sensor="unknown"` des Push-Pfads (`app/routers/agent.py:119`) gegen `?`: kollidiert mit keinem echten
  Sensor; ein Wechsel spaltete die Temperatur-Historie.
- Wartezeit auf die Kopfzeilen im HTTP-Check (`app/checkers/http.py:73`): T10 beschreibt sie richtig, eine eigene
  Grenze dafür ist eine neue Roadmap-Zeile, kein Teil dieses Pakets.
- Meldung für einen Redirect ohne `Location` (`app/checkers/http.py:89-90`): heute „Too many redirects (>5)“ schon
  nach der ersten Anfrage, das führt in die Irre. Ein eigener Text ist sichtbares Verhalten und eine neue
  Roadmap-Zeile; T7 schreibt nur Status und Anfragezahl fest, nicht den Text.
- Längengrenze für Check-Namen oder Tag-Werte: T4 begrenzt den Speicher am Puffer, T8 den Glocken-Titel
  (`HUB_TITLE_MAX`, `app/alerter.py:69`).
- Bereinigen oder Normalisieren gespeicherter Namen und aus Templates abgeleiteter Namen; der Hostname im
  Server-Inventar ist Sache des Servers.
- Der Surrogat-Text des Agent-Reports im Kodierer von `_send` (etwa `errors="replace"`): T3 behebt die Ursache an
  der Eingabe; andere Quellen von Tag-Werten (Namen aus Datenbank, IDs aus dem Pfad) können kein Surrogat tragen.

## Betroffene Komponenten & Dateien

Nur Komponente `monitoring` plus Doku (`scripts`, `doc_smoke_test`).

| Datei | Tasks |
|---|---|
| `app/routers/checks.py` | T1, T12 |
| `app/routers/agent.py` | T2, T3, T13 |
| `app/checkers/agent.py` | T2 (`NO_MOUNT`, `_capped`, Kommentar) |
| `app/core/bounds.py` | T3 |
| `app/core/victoria.py` | T4, T5 |
| `app/checkers/http.py` | T6 |
| `app/alerter.py` | T8 |
| `app/schemas.py` | T9 |
| `app/check_engine.py` | T13 |
| `tests/test_checks_metrics.py`, `tests/test_agent_report.py`, `tests/test_nul.py`, `tests/test_victoria.py`, `tests/test_http_checker.py`, `tests/test_alerter.py`, `tests/test_check_names.py` (neu), `tests/test_api_error_texts.py`, `tests/test_execute_check.py` | je Task |
| `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html` | T8, T10 |
| `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` | T1, T2, T3, T4, T5, T10 |
| `CHANGELOG.md` | T1–T4, T6, T8, T9, T10, T12 |

`scripts/dev/review-risk.txt` führt `routers/agent.py`, `alerter.py`, `check_engine.py` und `schemas.py`: T2, T3,
T8, T9 und T13 bekommen zusätzlich `security`.

## Datenmodell / API / Migrationen

- Keine Migration, kein neues Feld, keine neue Route.
- OpenAPI: Ein `field_validator` und ein `model_validator(mode="before")` ändern das JSON-Schema nicht; Routen,
  Docstrings und Antwortmodelle bleiben. `tests/test_openapi_snapshot.py` bleibt grün (T3 und T9 fahren ihn im
  `Verify:` mit).
- Sichtbar an der API: 422 statt 500 für Bodies mit Surrogat (T3), 422 für Check-Namen mit Steuerzeichen (T9 `[?]`),
  404 statt 500 für `POST /checks/{id}/run` auf einen während des Laufs gelöschten Check (T12).
- `GET /checks/{id}/metrics` liefert für die fünf Typen aus Problem 1 nur noch die Reihen des eigenen Checks (T1).

## Externe Integrationen

- **VictoriaMetrics, Line-Protocol:** unverändert; T2 ändert nur den Tag-Wert `mount` einer mountlosen Platte
  (`?` statt `/`), T1 nur den Selektor der Abfrage (`check_id="…"`), PromQL-Semantik wie bisher.
- **httpx 0.28.1 / httpcore 1.0.9 (T6):** gelesen in den installierten Quellen: `Response.iter_raw()` liefert die
  rohen Stücke; `iter_bytes()` entpackt sie mit den Decodern aus `httpx/_decoders.py` (`identity`, `gzip` mit
  `zlib.MAX_WBITS | 16`, `deflate` erst mit zlib-Kopf, bei Fehler roh mit `-zlib.MAX_WBITS`; `br`/`zstd` nur mit
  installiertem Paket, beide fehlen im Image; unbekannte Kodierungen bleiben roh). Pythons
  `zlib.Decompress.decompress(data, max_length)` gibt höchstens `max_length` Bytes zurück und hält den Rest in
  `unconsumed_tail` (Python-Doku `zlib`). T6 bildet genau diese Auswahl nach; eine Kodierung, die httpx nicht
  kennt, bleibt roh wie dort.
- **SMTP (T8):** Pythons `email`-Paket (Policy `compat32` von `MIMEMultipart`) faltet lange Betreffs selbst; T8
  entfernt nur Zeilenumbrüche und Steuerzeichen, kürzt nicht.

## Trade-offs & Alternativen

- **T1:** Typenliste umdrehen (nur `agent_resources` nach Server) statt die fünf Typen zu streichen und die Liste zu
  behalten: eine Stelle, der Sonderfall ist benannt.
- **T2 `?` statt Platte weglassen:** Der Checker zeigt die Platte als `?`, der Push-Pfad soll dieselbe Platte
  schreiben. Bestehende Reihen mit `mount=/` aus mountlosen Platten bleiben bis zum Ende der Retention. Der Router
  braucht die Konstante des Checkers; sie wird öffentlich (`NO_MOUNT`), weil monitoring-ref-3 Namen mit führendem
  Unterstrich über Modulgrenzen verbietet. Aus demselben Grund baut T8 eine eigene Tabelle im Alerter, statt
  `_AGENT_TEXT_TO_SPACE` zu importieren.
- **T3 Regel übernehmen statt eigener:** Der Server-Text und die Prüfung (Stack statt Rekursion, auch Dict-Schlüssel)
  kommen wörtlich, damit beide Dienste gleich antworten. `routers/agent.py` nutzt die Funktion weiter direkt
  (Liveness zuerst).
- **T4 `sys.getsizeof` statt `len(line)`:** gezählt wird, was der Puffer im Speicher hält (ein Nicht-ASCII-Zeichen
  kostet in Python 2 oder 4 Bytes je Zeichen der ganzen Zeile). 64 MiB liegen weit über dem üblichen Bedarf (100 000
  Zeilen zu rund 100 Zeichen sind etwa 13 MiB gehaltener Speicher) und weit unter dem, was ein Container hat. Eine
  Längengrenze für Tag-Werte im Router wäre eine zweite Stelle mit eigener Zahl; nicht nötig.
- **T6 eigene Decoder statt `iter_bytes`:** httpx bietet keine Grenze für das Entpacken. Alternative „`iter_raw` ohne
  Entpacken und `Accept-Encoding: identity` senden“: ein Server darf trotzdem komprimieren, und die Suche liefe dann
  über komprimierte Bytes; verworfen.
- **T8 Leerzeichen statt Abweisen:** Der Versand muss auch für gespeicherte Namen klappen (Problem 6); der Text der
  Meldung und der Webhook (`check_name`, JSON) bleiben unverändert.
- **T9 (offene Frage):** siehe unten; empfohlen ist 422 nur für die Eingabe, ohne Migration.
- **T13 Log nach dem Commit:** Die Zeile kommt erst, wenn der Wechsel gespeichert ist; im Push-Pfad nach dem
  gemeinsamen Commit (`app/routers/agent.py:261-270`). Ein Prozessabbruch zwischen Commit und Log verliert die Zeile;
  das ist der kleinere Fehler als eine Zeile ohne Wechsel.

## Risiken & Rollback

- T1 ändert, welche Reihen das Dashboard für fünf Typen zeigt; Prüfung über die Selektor-Tests, Rollback per Revert.
- T3 und T9 weisen bisher angenommene Bodies ab. Clients, die Surrogate senden, gibt es nicht (keine UTF-8-Form);
  für T9 siehe offene Frage.
- T4: Zu kleine Grenze verwirft Zeilen im Normalbetrieb. 64 MiB lassen etwa Faktor 4 bis 5 Luft über dem Zeilen-Deckel;
  die WARNING nennt beide Grenzen.
- T6 ersetzt den Lesepfad des HTTP-Checks; Paritätstests über alle Kodierungen von httpx und die Fehlertexte, dazu
  die bestehenden Tests in `tests/test_http_checker.py`.
- T13 verschiebt eine Log-Zeile; Tests prüfen Zahl und Text wie heute (`tests/test_agent_report.py:800-836`).
- Rollback je Task per Revert; keine Daten, kein Schema.

## Doku-Impact

- `docs/admin/monitoring.html` + EN: `:149` (`timeout`, T10), `:227` (Grafik, T10), `:344` (Betreff einzeilig, T8).
- `docs/developer/monitoring.html` + EN: `:145` (`mount` dann `?`, T2), `:175` (Suche in den ersten 1 MiB des
  entpackten Bodys, schrittweise entpackt, T10), `:233` (Prüfung auf NUL und ungepaarte Surrogate, T3), `:263`
  (Puffer: Byte-Grenze, Meldung beim Leeren, T4/T5), `:265` (jeder andere Check-Typ liest über `check_id`, T1).
- `CHANGELOG.md` unter `## [Unreleased]`, umlautfrei: neue Einträge (T1, T2, T3, T8, T9, T12 unter `### Fixed`),
  Ergänzungen der monitoring-io-Einträge (T4 `:118-124`, T6 `:158-164`), Korrekturen (T10).

## Reihenfolge und Parallelität

- **Hängt ab von monitoring-io** (PR #265): gebaut wird nach dessen Merge, mit `origin/main` im Branch.
- **smtp-hardening** (bereit) ändert in `app/alerter.py` `_send_email`, `_email_failure`, `_send_webhook`; T8 ändert
  `_build_message`. Gleiche Datei: smtp-hardening zuerst mergen, dann T8.
- **monitoring-ref-3** (Refactor, wartet auf monitoring-io) teilt `app/routers/agent.py`, `app/routers/checks.py`,
  `app/check_engine.py`, `app/alerter.py`, `app/core/bounds.py`, `app/checkers/agent.py`,
  `tests/test_checks_metrics.py`, `tests/test_alerter.py`, `docs/developer/monitoring.html` (+ EN) und
  `CHANGELOG.md`. Seriell, dieses Paket zuerst: Fehlerbehebungen vor einem Refactor derselben Stellen, und ref-3 T10
  benennt dann `_find_unstorable` (nach T3) statt `_find_nul` um.
- **ssrf-followups** (Plan `560b112b`; dessen Monitoring-Tasks warten ebenfalls auf monitoring-io) teilt `app/checkers/http.py` (dort der
  Fang um `check_target` und die Kommentare zum `InvalidURL`-Weg, hier `_read_head`, T6), `app/alerter.py` (dort der
  Webhook-Weg, hier `_build_message`, T8), `tests/test_http_checker.py` (T6, T7), `tests/test_alerter.py` (T8), die
  vier Monitoring-Doku-Seiten und `CHANGELOG.md`; `tests/test_alerter_dispatch.py` ändert nur ssrf-followups (hier
  nur im `Verify:` von T8). Andere Funktionen, also kein inhaltlicher Konflikt, aber seriell mergen: wer als Zweiter
  merged, zieht `origin/main` nach und greppt neu. Inhaltlich: Nach T3 weist die API einen Body mit Surrogat schon
  mit 422 ab; die Surrogat-Behandlung in ssrf-followups bleibt für Werte nötig, die nicht über einen Request-Body
  kommen (Template-Variablen aus dem Server-Inventar, gespeicherte Altdaten).
- **server-hardening**: andere Komponente, parallel-tauglich; T3 übernimmt dessen Regel aus Commit `908a84b6`.
- **R-0798** (eigenes Vorhaben docs-residual-risks): ändert voraussichtlich den Absatz `docs/developer/monitoring.html:263`, den T4 und
  T5 auch ändern; seriell.

## Offene Fragen

1. **T9 `[?]`: Wie mit gespeicherten Check-Namen umgehen, die schon Steuerzeichen tragen?** Kevin hat 422 für
   Steuerzeichen festgelegt; ob Bestandsdaten betroffen sind, lässt sich ohne Betriebsdaten nicht prüfen (Wege:
   frühere API ohne Regel, Template-Namen aus Server-Hostnamen, Problem 6). Abfrage für Betreiber:
   `SELECT count(*) FROM monitor_checks WHERE name ~ '[\x01-\x1f\x7f]';`.
   - A (empfohlen): 422 für `CheckCreate.name`, `CheckUpdate.name` (wenn gesendet) und `TemplateCheckDef.name`; keine
     Migration. T8 hält den Versand für alte Namen am Laufen. Folge: Wer einen solchen Check bearbeitet, bekommt 422
     mit `loc` `name`, bis er ihn umbenennt (der Desktop sendet den Namen bei jedem Speichern mit,
     `apps/desktop/ui/src/components/monitoring/MonitorCheckModal.svelte:71`).
   - A2: wie A, `PUT /checks/{id}` prüft den Namen aber nur, wenn er sich ändert (Prüfung im Router statt im Schema);
     keine Sperre beim Bearbeiten, dafür zwei Orte der Regel; Templates bräuchten dasselbe je Check-Definition.
   - B: A plus Datenmigration (Steuerzeichen → Leerzeichen in `monitor_checks.name` und den Template-Definitionen):
     Alembic, Heavy `linux-full`.
   - C: Steuerzeichen still durch Leerzeichen ersetzen statt 422: keine Sperre, widerspricht der 422-Linie.
   - D: nur T8, keine Eingaberegel.
