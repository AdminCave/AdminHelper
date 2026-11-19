<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-neu-p1 — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-neu-p1 · Review: pro Task
Spec: docs/features/arch-monitoring-neu-p1.md (Roadmap R-1559, R-0805)
Heavy: linux-full — Server-Proxy-Freigabeliste (`monitoring_proxy`) und zwei Monitoring-Migrationen; kein Gateway-, PKI-, Agent-, FRP- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@39a08c2a7`. P1a der Monitoring-Neuordnung (ADR 0004, Kevins Schnitt 2026-11-19): Statuswechsel-Log,
Objektzustand, typisierte Objekte, Objekt-API. Unverändert bleiben `_details`, `MonitorStateOut`, `MonitorCheckOut`,
die Antwort von `GET /status/server/{id}/history`, Alerting und VictoriaMetrics; jede Checker-Task hält die
bestehenden `_details`-Tests unverändert grün. „Nicht erhoben“ (`not_collected`) nur in der Objekt-API. Neue
Quelldateien bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later
<datei>`). Postgres-Tests (`tests/test_migrations_smoke.py`, `tests/test_check_engine_concurrency.py`) laufen ohne
Postgres in `DATABASE_URL` als test-skip; die Tasks mit Migration oder Sperre fahren sie zusätzlich gegen die
Test-DB des Worktrees und nennen die Summary-Zeile im Commit-Body, die PR-CI fährt sie mit Postgres. Risikopfade
(`check_engine.py`, `routers/agent.py`, `schemas.py`, `alembic/versions/*`, `monitoring_proxy/*`): `security` je Task
dazu. Belegte Fehler außerhalb des Auftrags werden Roadmap-Zeilen (`roadmap.py add`).

### T1 — `execute_check` und `HttpChecker.run` in benannte Schritte zerlegen (R-0805)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/http.py
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped @7e98c031a 2026-11-19T14:53:51+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T1.verdict.json)
Änderung: Reines Refactoring ohne Verhaltensänderung: `execute_check` (`check_engine.py:459`) in Laden, Ausführen (samt `RunSkipped`), Metriken schreiben, Zustand sperren und anwenden, Melden; `HttpChecker.run` (`checkers/http.py:31`) in Anfrage, Bewertung, Ergebnis. Die Monitoring-Suite ist vorher und nachher grün (Summary-Zeile vorher im Commit-Body).
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (interne Zerlegung, Verhalten unverändert)

### T2 — Statuswechsel-Log: Tabelle, Übernahme aus dem Alarm-Log, Schreiben, Aufbewahrung (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/d2f4a6c8e0b1_status_change_log.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/scheduler.py, apps/monitoring/app/main.py, apps/monitoring/tests/test_status_log.py, apps/monitoring/tests/test_migrations_smoke.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2cb20485d 2026-11-19T15:01:18+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T2.verdict.json)
Änderung: Modell `MonitorStatusChange` (`monitor_status_log`: `check_id` FK `ON DELETE CASCADE`, `object_key` NULL, `old_status`, `new_status`, `at`, `origin`; Indizes `(check_id, at)`, `(at)`) und Revision nach `a7c9e1f3b5d7`, die jede `monitor_alert_log`-Zeile als `origin = alert_log` übernimmt (Downgrade löscht nur die neue Tabelle). `apply_result` schreibt eine Check-Zeile, wenn der gedämpfte Status wechselt — damit beide Wege (Scheduler, Push). Tagesjob `system:history-cleanup` löscht Zeilen älter als 90 Tage. Tests: Zeile bei Wechsel auf beiden Wegen, keine ohne Wechsel und keine bei übersprungenem Lauf, Wechsel ohne Alarmregel und in der Wartung, Aufbewahrung, Upgrade mit Übernahme und Downgrade (Postgres).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_log.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_models_timestamps.py tests/test_execute_check.py tests/test_agent_report.py tests/test_scheduler.py tests/test_retention.py
Doku: → T9
Abhängt von: T1

### T3 — Verlaufsmarken aus dem Statuswechsel-Log (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/history.py, apps/monitoring/tests/test_status_history.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @cf486269e 2026-11-19T15:05:38+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T3.verdict.json)
Änderung: `server_events` (`history.py:230`) liest die Check-Zeilen (`object_key IS NULL`) von `monitor_status_log` statt `MonitorAlertLog`; Antwortform, `EVENT_LIMIT` und `_SAME_EVENT` bleiben, ein Erstergebnis `ok`/`info` aus `pending` ist kein Ereignis. Die Ereignis-Tests legen ihre Zeilen künftig im Log an (Quelle gewechselt, Erwartungen gleich); neu: ein Wechsel ohne Alarmregel und einer in der Wartung erscheinen, übernommene Alarm-Log-Zeilen mehrerer Regeln zählen einmal.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_status_history.py tests/test_status_log.py
Doku: → T9
Abhängt von: T2

### T4 — Objektzustand: Tabelle, Objektergebnis, `apply_objects`, Rückfall-Objekt, Verschwundenes (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/models.py, apps/monitoring/alembic/versions/e3a5c7e9f1b2_object_state.py, apps/monitoring/app/objects.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/app/scheduler.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/tests/test_migrations_smoke.py, apps/monitoring/tests/test_check_engine_concurrency.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_checker_messages.py, apps/monitoring/tests/test_template_overrides.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a57b189f3 2026-11-19T15:34:20+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T4.verdict.json)
Änderung: Modell `MonitorObjectState` (`monitor_object_state`, Spalten nach Spec) und Revision nach T2. Neues Modul `app/objects.py` (SPDX): liest und kappt `_objects` (`{"complete", "items"}`), bildet `<server>/<kind>/<id>` (zentral ohne Server, über 200 Zeichen Hash-Suffix), `apply_objects` nach Variante C (ein Lesezugriff, nur geänderte Zeilen), Dämpfung je Objekt mit `next_fail_count`/`effective_status` (`fail_count` gedeckelt, `not_collected` gesund), `since`, `bad_since`, `gone_at` nur bei vollständigem Ergebnis, Log-Zeile je Objektwechsel; ohne `_objects` ein Rückfall-Objekt `<server>/check/<check_id>` mit dem gedämpften Check-Status (ohne eigene Log-Zeile). Aufruf in `apply_result`; Scheduler und Push-Weg (`routers/agent.py`) nehmen `_objects` wie `_details` aus den Metriken, nie zu VictoriaMetrics. Der Tagesjob aus T2 löscht verschwundene Objekte nach 30 Tagen. Zwölf Dateien: Migration, Engine, beide Aufrufer und Aufräumen sind ein Lebenszyklus und nur gemeinsam prüfbar. Tests: Schreiben nur bei Änderung, Dämpfung, `bad_since` über warning↔critical, verschwunden und zurück, unvollständiges Ergebnis, Rückfall-Objekt, übersprungener Lauf, `MonitorStateOut` nie `not_collected`, Aufräumen, Upgrade/Downgrade und parallele Ergebnisse desselben Checks (Postgres).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_object_state.py tests/test_status_log.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_models_timestamps.py tests/test_check_engine.py tests/test_check_engine_concurrency.py tests/test_execute_check.py tests/test_agent_report.py tests/test_victoria.py tests/test_checker_messages.py tests/test_template_overrides.py tests/test_architecture_transitions.py
Doku: → T9
Abhängt von: T2

### T5 — Speicher-Objekte: `disk` aus smart_health, `pool` aus zfs_health (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_smart_checker.py, apps/monitoring/tests/test_plugin_checkers.py, apps/monitoring/app/objects.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_check_engine_concurrency.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @17326a879 2026-11-19T15:52:32+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T5.verdict.json)
Änderung: `SmartHealthChecker.evaluate` (`smart.py:255`) liefert je Platte ein Objekt `disk` (Schlüssel Modell + Seriennummer, ohne Seriennummer der Gerätepfad mit `stable = false`; WWN, sobald der Agent sie sendet), Status aus der Kategorie, Grund aus dem ersten Befund; vollständig. Eine schlafende Platte meldet weder Modell noch Seriennummer (R-1569): mit früherer Messung fehlt sie im Ergebnis, das dann unvollständig ist (ihr Objekt behält den letzten Stand wie `_details`), ohne frühere Messung ist sie `not_collected` unter dem Gerätepfad (`stable = false`). `ZfsHealthChecker.evaluate` (`plugins.py:281`) je Pool ein Objekt `pool`; vollständig. Ohne Datenblock unvollständig und leer. `_details` bleibt unverändert (bestehende Tests), neue Tests je Zustand.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_plugin_checkers.py tests/test_object_state.py tests/test_check_engine.py tests/test_check_engine_concurrency.py
Doku: → T9
Abhängt von: T4

### T6 — Container- und Backup-Objekte: docker_health, proxmox_backup (R-1559, Objekt-Teil von R-1534)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/app/checkers/smart.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @425f0a4df 2026-11-19T16:00:27+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T6.verdict.json)
Änderung: `DockerHealthChecker.evaluate` (`plugins.py:499`) je Container ein Objekt `container` (Schlüssel Compose-Projekt/Dienst/Nummer, solange der Agent keine Nummer sendet der Containername mit `stable = false`); vollständig. `ProxmoxBackupChecker.evaluate` (`plugins.py:106`) je VM ein Objekt `guest-backup` (VMID, `stable = false` bis zur Cluster-ID, R-0519); eine gestoppte VM unter `exclude_stopped` erscheint als `not_collected` mit Grund statt zu fehlen, `exclude_vmids` bleibt außen vor (P1b); vollständig. `_details` unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py tests/test_smart_checker.py
Doku: → T9
Abhängt von: T5

### T7 — Host-Objekte: cpu, memory, mount, sensor aus agent_resources; reboot, updates, clock aus system_state (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/app/checkers/system.py, apps/monitoring/tests/test_agent_resources_checker.py, apps/monitoring/tests/test_system_state_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b7ebdc834 2026-11-19T16:19:52+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T7.verdict.json)
Änderung: `AgentResourcesChecker.evaluate` (`agent.py:620`) liefert `cpu`, `memory`, je Mount `mount` (Pfad, `ignore_mounts` außen vor) und je Sensor `sensor` (Chip/Label) mit dem Status aus dem `_Grader`; vollständig. `SystemStateChecker.evaluate` (`system.py:100`) liefert `reboot`, `updates`, `clock`; ohne Systemzustand im Report unvollständig und leer. `_details` unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_resources_checker.py tests/test_system_state_checker.py
Doku: → T9
Abhängt von: T4

### T8 — Dienst-Objekte aus service_process (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_process_checker.py, apps/monitoring/app/objects.py, apps/monitoring/tests/test_object_state.py, docs/features/arch-monitoring-neu-p1.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @6f44870df 2026-11-19T16:42:27+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T8.verdict.json)
Änderung: `ServiceProcessChecker.evaluate` (`agent.py:685`) je Dienst ein Objekt `service` (voller Unit-Name; Windows kleingeschrieben, FreeBSD rc-Name); im Auto-Modus kennt der Report nur die fehlgeschlagenen Units, das Ergebnis ist unvollständig, im Listen-Modus vollständig; `ignore` bleibt außen vor (P1b). `_details` unverändert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py tests/test_object_state.py
Doku: → T9
Abhängt von: T7

### T9 — Objekt-API `GET /objects`, Proxy-Präfix `objects`, Doku DE+EN (R-1559)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/objects.py, apps/monitoring/app/routers/__init__.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_objects_api.py, apps/monitoring/tests/openapi.snapshot.json, apps/server/app/modules/monitoring_proxy/router.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1.md, apps/server/tests/test_monitoring_proxy_allowlist.py, apps/monitoring/tests/test_status_log.py
Evidenz: run.sh[quick] monitoring server: 5 passed, 0 failed, 13 skipped @1d4d44eaa 2026-11-19T18:42:13+01:00
Review: approve (.ah-out/review/arch-monitoring-neu-p1/T9.verdict.json)
Änderung: Neuer Router `routers/objects.py` (SPDX) mit `GET /objects` (Filter `server_id`, `check_id`, `kind`, `include_gone`; `limit`/`offset`, `X-Total-Count`; schlechteste zuerst, dann Name; `lastCheck` aus `MonitorState`), Schema `MonitorObjectOut`, Eintrag in `all_routers`, OpenAPI-Snapshot. Das Präfix `objects` kommt in `_ALLOWED_PATH_PREFIXES` (`monitoring_proxy/router.py:78`): der Server-Test `test_monitoring_proxy_allowlist.py` liest die Monitoring-Router und die vier Präfix-Listen der Entwickler-Doku, deshalb landen Route, Freigabe und Doku in einem Commit, und das Verify fährt beide Suiten. Dazu die übrige Doku: Statuswechsel-Log, Objektzustand und Objektergebnis, Tagesjob und Quelle der Verlaufsmarken (developer/monitoring DE+EN), `GET /objects` (api-reference DE+EN), Verlaufsmarken (admin/monitoring DE+EN), Changelog-Fragment. 13 Dateien: Route und Freigabe müssen zusammen landen, die Doku nennt beide.
Verify: bash scripts/dev/verify.sh monitoring server --strict
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-neu-p1.md
Abhängt von: T3, T4

### T10 — Statuswechsel-Log: Objekt-Zeilen je Check und Tag begrenzen (R-1559)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/objects.py, apps/monitoring/app/models.py, apps/monitoring/alembic/versions/d2f4a6c8e0b1_status_change_log.py, apps/monitoring/tests/test_object_state.py, apps/monitoring/tests/test_status_log.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-neu-p1.md
Änderung: Aus der Abschlussprüfung (`security`, Branch): `apply_objects` schreibt je Check und UTC-Tag höchstens `OBJECT_LOG_PER_DAY` (= `MAX_ROWS`) Objekt-Zeilen ins Statuswechsel-Log. Darüber ändert sich der Objektzustand weiter, nur die Log-Zeile entfällt; eine WARNING von `monitor.objects` nennt es einmal am Tag. Check-Zeilen (`object_key` NULL, höchstens eine je Ergebnis) zählen nicht mit. Teilindex `ix_status_log_object_at` (`check_id, at`, nur `object_key IS NOT NULL`) in Modell und Revision `d2f4a6c8e0b1` (nur auf diesem Branch), damit das Zählen keine Check-Zeilen liest.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_object_state.py tests/test_status_log.py tests/test_migrations_smoke.py
Doku: docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-neu-p1.md
Abhängt von: T4, T9

## Entscheidungen
- 2026-11-19 Plan: Schnitt P1a „Verlauf + Objekte“, P1b–P1e eigene Zeilen, vier Punkte nach P2, „nicht erhoben“ nur in der Objekt-API, verschwundene Objekte 30 Tage — Kevin 2026-11-19 (AskUserQuestion).
- 2026-11-19 Plan: die Log-Revision übernimmt `monitor_alert_log` einmal (`origin = alert_log`) — sonst wäre der Verlauf nach dem Update bis zu 90 Tage lückenhaft (ADR §13: jede Phase besser als vorher).
- 2026-11-19 Plan: „schlecht“ für `bad_since` = `warning`, `critical`, `unknown`; `not_collected` dämpft wie `ok` — ADR §3, „nicht erhoben“ ist kein Fehler.
- 2026-11-19 Plan: Objektschlüssel über 200 Zeichen werden mit Hash-Suffix gekürzt — die PK-Spalte ist `String(200)` (ADR §5), ein Abschneiden ohne Hash ließe zwei Objekte kollidieren.
- 2026-11-19 Plan: Route, Proxy-Präfix und Doku in einer Task (T9) — `test_monitoring_proxy_allowlist.py` liest Monitoring-Router und Präfixlisten der Doku, jede Teilmenge allein ist rot.
- 2026-11-19 Plan: Aufbewahrung als Konstanten (90 Tage Log, 30 Tage verschwunden), keine neuen Umgebungsvariablen — YAGNI, ADR §5.
- 2026-11-19 T4: Dämpfung je Objekt als `check_engine.damp_object` — `test_architecture_transitions` hält die Pipeline-Helfer in `check_engine.py`; `objects.py` importiert sie oben, `apply_result` importiert `apply_objects` erst im Aufruf (Kreisimport).
- 2026-11-19 T4: Rückfall-Objekt `<server>/check/<check_id>` steht für den Check, solange er kein eigenes nicht verschwundenes Objekt hat; es spiegelt `MonitorState.since`, schreibt keine Log-Zeile (die Wechsel sind die Check-Zeilen) und wird gelöscht, wenn sich der Schlüssel ändert (Check auf anderen Server).
- 2026-11-19 T4: `fail_count` je Objekt ist bei `consecutive_fails` gedeckelt — ein Objekt, das tagelang rot steht, zählt nicht ohne Ende hoch, und eine spätere Senkung der Schwelle greift sofort.
- 2026-11-19 T4: Ein neues Objekt schreibt `pending → <Status>` ins Log, das Verschwinden schreibt keine Zeile (`gone_at` ist kein Status).
- 2026-11-19 T4: Zwei Einträge unter einem Schlüssel: der schlechtere gilt (Reihenfolge `SEVERITY`); `MAX_OBJECTS = 1000` je Ergebnis, ein gekapptes Ergebnis zählt als unvollständig (markiert nichts verschwunden).
- 2026-11-19 T4: Ein Check-Ergebnis `not_collected` wird als `ok` gespeichert — `MonitorStateOut` behält sein altes Vokabular (Kevin 2026-11-19).
- 2026-11-19 T4: Kein Index auf `gone_at` — der Tagesjob liest eine Tabelle in der Größe der Objektzahl einmal täglich.
- 2026-11-19 T4: `test_template_overrides` kennt den Job `history_cleanup` (Nachtrag zu T2: `main.py` plant ihn seit T2, das Fixture stubbte ihn nicht).
- 2026-11-19 T4 (für T5–T8): ok-Objekte tragen einen festen Grund, sonst kostet jeder Lauf ein UPDATE je Objekt (Variante C).
- 2026-11-19 T4 (Bedingung für T5, security-Urteil T4 `wichtig`): bevor Objekt-IDs aus Agent-Daten kommen, liest `apply_objects` nur nicht verschwundene Zeilen und die Schlüssel des Ergebnisses und legt je Check höchstens eine feste Zahl Zeilen an (darüber unvollständig) — sonst ließe ein Agent mit wechselnden IDs Tabelle und Lesekosten je Report wachsen; ein Eintrag der Art `check` wird abgewiesen. Gebaut in T5 (`objects.py`), zusammen mit dem Grund des Rückfall-Objekts (nur bei schlechtem Status, Review-Nit T4).
- 2026-11-19 T5: Bedingung aus T4 gebaut: `apply_objects` liest je Ergebnis nur nicht verschwundene Zeilen und die Schlüssel des Ergebnisses; neue Zeilen nur bis `MAX_ROWS` (2 × `MAX_OBJECTS`) je Check, darüber unvollständig und ein Log-Warnhinweis. Hingenommen: am Deckel bleibt auch echter Wechsel stehen, bis der Tagesjob 30 Tage verschwundene Zeilen löscht.
- 2026-11-19 T5: `read_objects` nimmt nur Einträge mit `kind` als Text (1–40 Zeichen, nicht `check`), bekanntem Status und `id` als Text oder ohne; alles andere fällt weg und macht das Ergebnis unvollständig. Das Rückfall-Objekt trägt den Grund nur bei schlechtem Status (Review-Nit T4: Ping/HTTP nennen ihre Latenz in der Meldung).
- 2026-11-19 T5: Platte = WWN, sonst `<Modell>/<Seriennummer>`, sonst Gerätepfad mit `stable = false`; Name `"<Gerät> (<Modell>)"`, Grund der erste Befund ohne Präfix, ok `SMART OK`, unknown `SMART not readable`. Eine schlafende Platte mit früherer Messung (`smart_passed` im letzten Stand) fehlt und macht das Ergebnis unvollständig; ein Stand ohne Messung (Platte schlief seit dem ersten Bericht) ist keine Messung, sie bleibt `not_collected` unter dem Gerätepfad. Hingenommen: solange eine gemessene Platte schläft, wird eine ausgebaute nicht als verschwunden markiert.
- 2026-11-19 T5: `smart_absent` und fehlende oder ausgefallene ZFS-Daten liefern kein `_objects`: Platten und Pools behalten ihren Stand (der Grund kann ein gescheiterter Scan sein). Pool = `_pool_name` (ohne Namen `?`), Grund der erste Befund ohne Präfix, ok der Health-Text (fest).
- 2026-11-19 T5: `whole_list` (`checkers/agent.py`, für T5–T8): vollständig nur, wenn `capped_objects` jeden Eintrag behält (Liste, ≤ `MAX_REPORT_ENTRIES`, nur Objekte). Der Agent sendet `pools` immer als Liste (`parseZpoolList`), eine leere ist vollständig.
- 2026-11-19 T5: Schlechte Platten und Pools tragen Messwerte im Grund (Temperatur, Füllstand): ein UPDATE je Wertwechsel, nur solange das Objekt schlecht ist.
- 2026-11-19 T5: Gegenproben: zwölf Mutationen (Lesefilter, Deckel, Art `check`, Rückfall-Grund, Schlaf-, Schlüssel-, Grund- und Vollständigkeitslogik) je mit dem erwarteten roten Test; Lock-Probe auf Postgres mit der Verzögerung in `_apply_item`: ohne Lock und Autoflush rot, ohne Lock allein fängt der Autoflush ab (wie T4).
- 2026-11-19 T6: Container = Containername mit `stable = false` (Rückfall nach ADR §4: der Agent sendet keine Compose-Nummer, §12.6, P1e), leerer Name `?`. Status wie die Bewertung des Checks; ein von Hand gestoppter oder nie gestarteter Container ist ok (ADR §6.3) mit Grund `Stopped` bzw. `Not started`, ein laufender `Running`; ein schlechter trägt den Text der Meldung ohne Namen (`_problem_reason`, von `_problem_text` abgespalten). Ignorierte Container bleiben außen vor, das Ergebnis bleibt vollständig.
- 2026-11-19 T6: Gast-Backup = VMID als Text mit `stable = false` (R-0519), Name das Label der Meldung (`VM 100 (web)`); ok `Backup up to date`, ohne Backup critical `No backup`, veraltet warning `<n>h old` (ein UPDATE je Stunde, nur solange veraltet). Ein Gast, den `exclude_stopped` nicht bewertet, wird `not_collected` mit `Not running, backup not rated`; `_details`, Zählwerte und Meldung bleiben unverändert, `exclude_vmids` bleibt außen vor. Ein Gast ohne lesbare VMID wird wie bisher bewertet, hat aber keinen Schlüssel: kein Objekt, das Ergebnis ist unvollständig.
- 2026-11-19 T6: Ausfall oder fehlender Block bei Docker und Proxmox liefern kein `_objects` (wie T5); eine leere Liste ist vollständig, ein Wert, der keine Liste ist, nicht.
- 2026-11-19 T6: `NOT_COLLECTED` zieht von `smart.py` nach `checkers/agent.py` (zweiter Nutzer; der Import aus `app.check_engine` schlösse den Zyklus wie in T5). Die Tests vergleichen gegen `app.check_engine.NOT_COLLECTED`, eine Abweichung wird rot. Verify um `tests/test_smart_checker.py` ergänzt.
- 2026-11-19 T6: Gegenproben: zwölf Mutationen in `plugins.py` (gestoppter Gast fehlt, `exclude_vmids` benannt, Gast ohne VMID vollständig, Grund mit Label, Gast stabil, leere VM-Liste immer vollständig, gestoppter Container mit eigenem Status, Container stabil, Container-Liste immer vollständig, leerer Name, ignorierter Container benannt, Grund mit Namen) je mit dem erwarteten roten Test; ohne Mutation 417 passed, Datei hash-identisch.
- 2026-11-19 T7: Host-Objekte von `agent_resources`: `cpu` mit der Last (im Container nicht bewertet, also ok), `memory` mit dem Swap, `mount` je bewertetem Pfad mit Platz und Inodes (ID = Name = Mount-Pfad), `sensor` je Sensorname (ID = Name). Status = schlechteste Überschreitung des Graders samt Hysterese; Grund ok fest `Within limits` (ein ok-Objekt kostet kein Schreiben), bei Problem die Grader-Texte mit `; ` (Wert und Grenze).
- 2026-11-19 T7: `_Grader.problem_marks` neben `problem_levels`: das hält je Schlüssel nur die letzte Stufe, zwei Sensoren gleichen Namens wären sonst so gut wie der letzte. Lastabwurf ist nie ein Objekt (ADR §2); `_grade_load_shed` geht nicht über `grade()`.
- 2026-11-19 T7: Platte oder Sensor ohne Namen steht unter dem Namen, unter dem sie bewertet werden (`NO_MOUNT` bzw. `?`), statt ohne Schlüssel das Ergebnis unvollständig zu machen: `ignore_mounts: ["?"]` und die Overrides benutzen genau diesen Namen.
- 2026-11-19 T7: Vollständig nur mit CPU, RAM und ganzer Plattenliste: fehlt `disks` oder ist sie kaputt (Partitions-Fehler), wird kein Mount gone. Fehlende Temperaturen oder ein Wert, der keine Liste ist, sind vollständig (VMs haben keine Sensoren); eine gekappte Liste oder Nicht-Objekte darin nicht. Ein Mount, dessen Usage scheitert, oder ein kurzer Sensor-Lesefehler ist bis zur Rückkehr gone. `ignore_mounts` und ausgeschlossene Dateisysteme bleiben draußen, das Ergebnis bleibt vollständig. Ohne Ressourcendaten kein `_objects`.
- 2026-11-19 T7: `system_state`: `reboot`, `updates`, `clock` (ID leer) nur, wenn gelesen; Status aus der `problems`-Liste der Bewertung (keine zweite Logik), abgeschaltet `not_collected` mit `Not rated, turned off in the check`. Gründe fest: `No reboot required`, `No security updates pending`, `Synchronized`, in der Gnadenfrist `Not synchronized yet after boot`; Probleme `Reboot required`, `<n> security updates pending` (ein UPDATE je Zahlwechsel, nur solange schlecht), `Clock not synchronized`. Kein OOM-Objekt (Ereignis). Vollständig nur mit allen dreien (Windows/FreeBSD nie: sichere Richtung); ohne Block oder unbrauchbarer Block `{"complete": false, "items": []}`, die Objekte bleiben.
- 2026-11-19 T7: Gegenproben: 22 Mutationen in `agent.py`/`system.py` (Marks statt Levels, CPU ohne Last, RAM ohne Swap, Mount ohne Inodes, ignorierter Mount benannt, unbenannter Mount schlüssellos, ok-Grund, Schlimmstes nicht critical, Lastabwurf-Objekt, Vollständigkeit ohne Platten/RAM/CPU, gekappte Sensoren vollständig, keine Sensoren unvollständig, kein `_objects`, Abschaltung ok, System immer vollständig, ohne Block vollständig, Gnadenfrist-Grund, Uhr in der Frist schlecht, Update-Grund ohne Zahl, fehlendes Feld benannt) alle rot (die erste Lastabwurf-Variante, `load_shed` unter den CPU-Schlüsseln, war äquivalent, weil Lastabwurf nie in `problem_marks` steht; ersetzt durch ein Lastabwurf-Objekt); unmutiert 489 passed, Dateien hash-identisch.
- 2026-11-19 T8: Dienst-Objekte von `service_process` (Art `service`, auch für Timer/Mount: die ADR-Tabelle kennt eine Art je Checker). Auto-Modus: je gestörter Unit ein Objekt, bewertet wie die Meldung (failed Dienst critical, andere Unit warning, `Failed (<Grund>)`; enabled-inaktiv warning `Inactive (autostart)`), unvollständig, da der Agent keine gesunde Unit nennt; ignorierte Units sind kein Objekt (P1b), ein leerer Name (den `_details` behält) hat keinen Schlüssel.
- 2026-11-19 T8: Erholung im Auto-Modus über den Engine-Merker `others_ok` statt `complete = True` (setzte eine erholte Unit gone, ohne Statuswechsel im Verlauf, `bad_since` bliebe) oder Erholung aus `prev_details` (hängt am gespeicherten Stand): ein unvollständiges Ergebnis, dessen Einträge alle übernommen wurden, setzt die nicht genannten, nicht verschwundenen Objekte über `_apply_item` gedämpft auf ok (Verlaufszeile; kein Schreiben, wenn schon ok mit gleichem Grund). Der Auto-Modus setzt ihn nur mit beiden Listen ganz (Liste, ≤ 500) und ohne `error`, wie seine Meldung `All services OK`; ein Eintrag, der kein Name ist, steht für keine Unit und bricht die Ganzheit nicht. Eine Unit, die erst ignoriert wird, wird so ok.
- 2026-11-19 T8: Schlüssel = voller Unit-Name (ADR §4); Windows der Dienstname klein (der SCM vergleicht ohne Groß/klein), FreeBSD der rc-Name ohne `.service`; das OS aus `host.os` (seit R-0421), ohne Host-Block Linux. Listen-Modus: der konfigurierte Name über `_unit_name`, Alias nicht aufgelöst: das Inventar mit `alias_of` kommt gedrosselt, ein Schlüssel, der damit wechselte, machte das Objekt gone. Abweichung von ADR §4 („Alias aufgelöst“), Kevin im Abschluss melden; die Checker-Umstellung ist P2. Beide Modi geben derselben Unit denselben Schlüssel (Test).
- 2026-11-19 T8: Listen-Modus vollständig: running ok `Running`, down critical `Not active (<Grund>)`, ohne Daten `not_collected` (Kevin 2026-10-16: nodata ist nicht down) mit `Services not queryable: …` bzw. `No data from the agent`. `No services configured` liefert ein leeres vollständiges Ergebnis, damit abgewählte Dienste gone werden.
- 2026-11-19 T8: Vorbefund: der Linux-Agent verschluckt einen gescheiterten `list-units --state=failed` (kein `error`), Meldung und `others_ok` sagen dann ok; wird vor dem PR eine `neu`-Zeile.
- 2026-11-19 T8: Gegenproben: 26 Mutationen in `objects.py`/`agent.py` (others_ok übergangen, im vollständigen Ergebnis, ohne Ganzheit, jeder wahre Wert, Grund ungekappt, `stable` zurückgesetzt, verschwundene Zeilen gelesen; Auto-Modus ohne Objekte, ignorierte benannt, others_ok trotz Fehler/Kappung, Deckel um eins, Nicht-Liste ganz, jede Unit critical, Grund verloren, leerer Name, Windows-Groß/klein, FreeBSD-Suffix, OS übergangen, Name ungekappt; Listen-Modus nodata down, Fehler- und Down-Grund verloren, unvollständig, keine Dienste ohne Ergebnis, Alias aufgelöst) alle rot; unmutiert 193 passed, Dateien hash-identisch.
- 2026-11-19 T9: `GET /objects` ordnet nach `SEVERITY` per `CASE` (unbekannter Status = schlechtester, wie `_rank`), dann Name, Check, Schlüssel; `server_id` filtert den Server des Checks (ein zentraler Check hat keinen), `lastCheck` per Outer Join aus `MonitorState` (kein Schreiben je Lauf). Ohne `limit` die ganze Liste wie die übrigen Monitoring-Listen.
- 2026-11-19 T9: Nachtrag zu T7: `test_status_log.py::test_push_path_logs_each_change_of_the_damped_status` (T2) war seit T7 rot (das Verify von T7 fuhr ihn nicht): der Push-Pfad von `agent_resources` schreibt nun auch die Zeilen des CPU-Objekts. Die Erwartung nennt sie jetzt (strenger, nicht gefiltert); erst das volle Verify von T9 fand es. Gefixt in T9 (Datei per `set-files`).
- 2026-11-19 T9: R-1644 (`neu`) für den verschluckten `list-units --state=failed` (Vorbefund T8).
- 2026-11-19 T10: Abschlussprüfung `security` (Branch) `request_changes`, Einzelheiten nur in `tasks/private/`; die Objekt-Zeilen des Statuswechsel-Logs bekommen ein Tagesbudget je Check (`OBJECT_LOG_PER_DAY` = `MAX_ROWS`: ein Check mit `MAX_OBJECTS` Objekten kann anlaufen und jedes einmal wechseln). Statt eines Budgets je Ergebnis oder je Objekt: die Tagessumme ist die Größe, die das Log begrenzen soll. Hingenommen: an einem Tag über dem Budget fehlen die weiteren Objektwechsel im Verlauf, der Objektzustand und die Check-Zeilen bleiben richtig. Index als Teilindex in derselben Revision, weil `d2f4a6c8e0b1` nur auf diesem Branch liegt.
