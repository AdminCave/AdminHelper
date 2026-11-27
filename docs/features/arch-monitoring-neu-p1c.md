<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Neuordnung P1c: Schalter und Ignorierlisten werden Ausnahmen

Roadmap R-1637 (FEAT, mit R-1521) und R-1793 (BUG) · Zug `tasks/arch-monitoring-neu-p1c.md` · ADR 0004 §4, §7, §10,
§12.2 · Stand `origin/main@9704ac3f3`

## Problem / Motivation

P1b (R-1636) hat das Ausnahme-Modell gebaut (`monitor_exceptions`, Geltung Check, Check-Typ, Server und alle). Es
kennt bisher nur die Wirkung „nicht melden“ (`no_notify`). Zwei Dinge, die der Nutzer heute ausnimmt, stehen noch
außerhalb des Modells. Die Spur aus ADR 0004 §7 (wer, wann, Grund) fehlt ihnen deshalb, und mancher Fehler lässt
sich dort nicht beheben:

- **`enabled` als Nutzerschalter.** `POST /checks/{id}/toggle` (`apps/monitoring/app/routers/checks.py:682`) und
  `PUT` mit `enabled` kippen die Spalte `MonitorCheck.enabled`. Dieselbe Spalte setzt auch das System:
  - der Modul-Sync für eine verschwundene Instanz (`apps/monitoring/app/module_sync.py:596`);
  - der Vorlagen-Sync mit dem Wert der Vorlage (`apps/monitoring/app/template_sync.py:144`).

  Wer abgeschaltet hat, wann und warum, steht nirgends. Damit ein späterer Sync das Abschalten des Nutzers nicht
  zurückdreht, braucht es heute zwei Hilfsmarken in `overridden_fields` (`mark_overrides`, `template_sync.py:190`,
  und R-1573, `mark_module_overrides`, `module_sync.py:153`).
- **Die fünf Ignorierlisten:**
  - `ignore_mounts` (`apps/monitoring/app/checkers/agent.py:445`);
  - `ignore` der Dienste (`agent.py:999`, fnmatch);
  - `ignore_devices` (`apps/monitoring/app/checkers/smart.py:289`);
  - `exclude_vmids` (`apps/monitoring/app/checkers/plugins.py:170`);
  - `ignore_containers` (`plugins.py:643`).

  Sie stehen im Feld `config` des Checks. Sie haben drei Fehler:
  - **Vorlagen-Schwellen kommen nicht mehr an.** Wer einen Eintrag ignoriert, markiert die ganze `config` als
    überschrieben, und neue Schwellen der Vorlage erreichen den Check danach nie mehr (ADR 0004 §10,
    Migrationsgefahren).
  - **Dienstnamen werden als Muster gelesen.** Die Desktop-Karte „Dienste“ schreibt den Namen roh in `ignore`
    (`apps/desktop/ui/src/lib/stores/monitoring.ts:489`), der Checker liest jeden Eintrag aber als fnmatch-Muster.
    Ein Name mit `[`, `*` oder `?` trifft sich dann nicht oder blendet mehr aus (R-1521).
  - **Keine Spur.** Wer einen Eintrag wann und warum gesetzt hat, steht nirgends.
- **R-1793.** Eine per `ignore_devices` ausgenommene Platte im Standby liefert kein Objekt (`smart.py:307`). Das
  Ergebnis gilt trotzdem als vollständig (`complete`, `smart.py:303`), und `apply_objects`
  (`apps/monitoring/app/objects.py:163`) setzt die Platte in `GET /objects` auf verschwunden (`gone_at`). Wacht sie
  auf, ist sie wieder da: Sie flackert mit jedem Standby. Quelle und Beweis: reviewer arch-monitoring-neu-p1b T5
  2026-11-25, `feature/arch-monitoring-neu-p1b@4208ad2bd` `apps/monitoring/app/checkers/smart.py:310`.

## Ziel & Nicht-Ziele

**Ziel** (ADR 0004 §10, Zeilen „`enabled`“ und „Ignorierlisten“; Kevins Entscheidungen 2026-11-27):

1. **Zwei neue Wirkungen und eine neue Geltung** im Ausnahme-Modell:
   - **Wirkungen:**
     - `skip` („nicht prüfen“): nur mit Geltung `check`, nur dauerhaft.
     - `no_rating` („prüfen, nicht bewerten“): nur mit der neuen Geltung `object`, nur dauerhaft.
   - **Geltung `object`:** der Check, die Objektart (`mount`, `disk`, `container`, `guest-backup`, `service`) und
     ein Muster (fnmatch, case-sensitiv).
   - Andere Kombinationen antworten 422. Weitere Dauern kommen mit dem Ausnahme-Dialog in P2; die Erweiterung ist
     additiv.
2. **Abschalten ist eine Ausnahme.**
   - `POST /checks/{id}/toggle` und `PUT /checks/{id}` mit `enabled` legen eine `skip`-Ausnahme an oder beenden sie,
     mit dem Akteur aus den Proxy-Headern (`X-AH-Actor-*`, P1b).
   - Die Spalte `enabled` bleibt der Schalter des Systems (Modul- und Vorlagen-Sync).
   - Ein Check läuft genau dann, wenn die Spalte an ist **und** keine `skip`-Ausnahme gilt. Alle Leser, die heute
     die Spalte fragen, fragen das (Liste unten).
   - `MonitorCheckOut.enabled` meldet diesen Wert: Alte Desktops schalten unverändert weiter (ADR §10, Rückweg-Spalte).
3. **Ignorierlisten werden Objekt-Ausnahmen `no_rating`, Einträge als Muster** (Kevin 2026-11-27,
   „Muster-Ausnahme“).
   - Jeder Eintrag der fünf Listen wird eine Ausnahme mit Geltung `object`.
   - Exakte Listen (Mounts, Geräte, Container, VMIDs) werden maskiert: `[` → `[[]`, `*` → `[*]`, `?` → `[?]`. Das
     Muster trifft dann nur den Eintrag selbst, auch einen Gerätenamen wie `/dev/bus/0 [megaraid_disk_00]`
     (`docs/developer/agent.html`, `smartDiskID`).
   - Die Einträge der Dienste bleiben Muster, so wie der Checker sie heute liest.
   - Die Engine gibt dem Checker die geltenden Muster mit ihrer Quelle. Die Checker vergleichen per `fnmatchcase`, und
     die Marke `excluded` des Objekts nennt die Ausnahme (ihre ID) statt der Einstellung.
4. **Die Listen bleiben als API-Feld** (ADR §10, Rückweg „der Server übersetzt“).
   - **Lesen:** `GET /checks` setzt die Listen aus der gespeicherten `config` und den geltenden Ausnahmen zusammen
     (maskierte Muster wieder als Klartext).
   - **Schreiben:** `PUT` oder `POST` mit einer Liste übersetzt der Server in Anlegen und Beenden von Ausnahmen
     (`origin = api`, Akteur aus den Headern).
   - **Gespeichert** bleibt in `config` nur, was die Vorlage des Checks vorgibt. Eigene Einträge machen die `config`
     damit nicht mehr zur Überschreibung.
5. **Datenmigration**, idempotent je Quelleintrag, mit Trockenlauf.
   - **Abgeschaltete Checks:** Hat der Nutzer abgeschaltet, wird daraus eine `skip`-Ausnahme, und die Spalte geht an.
     Das gilt für:
     - einen manuellen Check mit `enabled = false`;
     - einen Vorlagen- oder Modul-Check mit `enabled = false` und der Marke `enabled` in `overridden_fields`.

     Die Marke fällt weg. Hat das System abgeschaltet, bleibt die Spalte aus: eine verschwundene Modul-Instanz oder
     eine Vorlage mit `enabled: false`.
   - **Listen:** Jeder eigene Listeneintrag wird eine `no_rating`-Ausnahme mit `origin = migration`, ohne Akteur
     („unbekannt (migriert)“, ADR §10). `disk` und `container` tragen die Marke „instabil“ (Schlüssel nach
     Gerätepfad bzw. Containername, ADR §4, §10). Die `config` behält nur, was die Vorlage vorgibt.
   - **Schwellen-Rückfall** (Kevin 2026-11-27, „Rückfall auf Vorlage“): Unterscheidet sich die `config` eines
     Vorlagen-Checks danach nicht mehr von der Vorlage, fällt die Marke `config` aus `overridden_fields`. Der
     Vorlagen-Sync gleich danach bringt die Schwellen der Vorlage.
   - **Ablauf:** Die Migration läuft einmal beim Start nach `alembic upgrade`, vor dem ersten Vorlagen-Sync (Marke in
     `monitor_seed_state` wie `OVERRIDE_BASELINE_KEY`, `template_sync.py:216`).
   - **Trockenlauf:** `python -m app.exception_migration --dry-run` fährt Schema-Upgrade und Migration in einer
     Transaktion und rollt sie zurück. Er gibt den Diff-Bericht aus: je Check die neuen Ausnahmen, die Änderung an
     Spalte, `config` und Marken, beim Schwellen-Rückfall alte und neue Werte.
   - **Grenzen:** Unassign und Tag-Entzug ergeben keine Ausnahmen; die Migration liest nur bestehende Checks (ADR
     §10).
6. **Objekt-API.**
   - `GET /objects` meldet am Objekt die engste Ausnahme. Ein per Objekt-Ausnahme ausgenommenes Objekt trägt
     `exception = {source: exception, effect: no_rating, scopeKind: object, id, reason, unstable}`.
   - Ein Check mit geltender `skip`-Ausnahme zeigt seine Objekte als „nicht erhoben“ (`not_collected`) mit der
     Ausnahme (§12.2), nicht den eingefrorenen Status.
7. **Abschalten und Wiedereinschalten wie heute.**
   - Abschalten mit Alarm in der Glocke sendet die Entwarnung (`_all_clear_disabled`, `checks.py:657`).
   - Endet die `skip`-Ausnahme, startet der Check frisch (R-1571), und die nächste Bewertung entscheidet (ADR §7,
     „Ende“; §12.2).
   - Löschen eines Checks löscht seine Ausnahmen (FK `ON DELETE CASCADE`, P1b).
8. **R-1793** (Kevin 2026-11-27, „Ergebnis unvollständig“): Schläft eine ausgenommene Platte, setzt der
   SMART-Checker `complete = False`. Nichts wird `gone`, und die Platte behält ihren letzten Stand.
9. **R-1521:** `ignoreService` im Desktop maskiert den Dienstnamen, bevor es ihn in `ignore` schreibt. Dazu Tests
   für einen gescheiterten `PUT` und dafür, dass die Antwort den Check ersetzt.
10. **Abnahme** (Kevin 2026-11-27, „Vor der nächsten Beta“):
    - **Vor dem Merge:** synthetisch auf einer Pool-VM. `scripts/tests/upgrade_path_test.sh` legt auf dem letzten
      Release alle fünf Listen und abgeschaltete Checks an (manuell, Vorlage). Danach fährt es den Trockenlauf
      (Datenbank unverändert), das Update auf den Checkout (Migration, Listen und Schalter über die API unverändert
      sichtbar) und den Rückweg über `restore.sh` mit den Images des Releases (Datenbank wie vorher).
    - **An Kevins Daten:** Dafür gibt es eine neue `blockiert`-Zeile für Kevin: ein Backup seiner Instanz
      (`backup.sh`) bereitstellen. Die Session fährt damit auf einer Pool-VM Trockenlauf, Migration und Rückweg und
      legt den Diff-Bericht unter `tasks/private/` vor, bevor die nächste Beta getaggt wird.

**Nicht-Ziele (YAGNI):**
- Keine Bedienung (Ausnahme-Dialog, Liste „Ausgeblendet“, Vorlage zur Prüfung): P2.
- Keine Geltung Regel, Tag oder Cluster und keine Wirkung `mute_me`: kommen mit P2/P3.
- Kein Neuschlüsseln instabiler Objekte (Agent-Lücken, ADR §11).
- Keine Kennzahlen für ausgenommene Objekte. Der Checker wertet einen ausgenommenen Eintrag wie heute nicht aus;
  das Objekt bleibt `not_collected` mit Marke, so wie in P1b. „Prüfen, nicht bewerten“ mit sichtbaren Werten zeigt
  erst P2.
- `silent` und die übrigen Einstellungen aus ADR §10 bleiben, wie sie sind: `exclude_stopped`,
  `alert_on_unavailable`, `disk_overrides`, `temp_overrides`, `unless`, `if_absent` (P1d bzw. P4).
- Listen in der `config` einer Vorlage bleiben Teil der Vorlage. Profile an Tags sind P4.
- Keine Änderung an `scripts/update.sh` oder `restore.sh`: `update.sh` legt vor jedem Update schon ein Backup an
  (`scripts/update.sh:725`).

## Betroffene Komponenten & Dateien

**Monitoring (`apps/monitoring/`)**
- `app/models.py`
  - `MonitorException` (`:592`): Spalten `object_kind` und `object_pattern`.
  - `MonitorCheck`: „läuft“ als Ausdruck (Spalte AND NOT EXISTS geltende `skip`).
  - `to_dict` (`:157`): `enabled` meldet den effektiven Wert.
- `alembic/versions/<neu>_object_exceptions.py` (neu, SPDX): `down_revision = "b6d8f0a2c4e6"`.
- `app/exception_scope.py`
  - Rang `object` (enger als `check`); `covers` und `narrowest` für Objekte.
  - Maskieren und Klartext.
  - Laden der geltenden `skip`- und `no_rating`-Ausnahmen; „läuft“-Filter.
  - `load_no_notify` (`:86`) bleibt.
- `app/schemas.py` (`ExceptionInput` `:375`, Konstanten `:370`–`:372`): Geltung `object` mit `object_kind` und
  `object_pattern`, Wirkungen `skip` und `no_rating`, Prüfung der Kombinationen.
- `app/routers/exceptions.py`
  - `_apply` (`:29`): Objektfelder; der Check-Typ muss zur Objektart passen.
  - `skip` anlegen oder beenden plant den Check aus bzw. ein, mit Entwarnung und frischem Start (gemeinsam mit
    `toggle_check`).
- `app/routers/checks.py`: `toggle_check` (`:682`), `update_check` (`:422`), `create_check` (`:356`), `_schedule`
  (`:115`), `run_check_now` (`:764`) und die Summary (`:965`). Dazu die Übersetzung der Listen in beiden
  Richtungen.
- Die Leser von `enabled` stellen auf „läuft“ um:
  - `app/scheduler.py:142`;
  - `app/check_engine.py:406`, `:444`, `:526`;
  - `app/routers/agent.py:423`;
  - `app/main.py:187`;
  - `app/alerter.py:445`, `:476`;
  - `app/alert_bundle.py:164`, `:219`;
  - `app/bell_catch_up.py:88`, `:143`;
  - `app/history.py:200`;
  - `app/discovery.py:682`;
  - `app/module_plan.py:66`;
  - `app/template_sync.py:504`, `:515`, `:627` (Planer-Aktionen).

  Die Schreiber in `module_sync.py` (`:596`–`:653`) und `template_sync.py` bleiben auf der Spalte.
- Engine und Checker:
  - `app/check_engine.py`: `_load_run` (`:521`) und `_load_disk_rules` (`:433`, Liste `:452`–`:469`) geben die Muster mit
    Quelle weiter.
  - `app/checkers/agent.py`: Mounts `:445`, `:591`; Dienste `_is_ignored` `:850`; `excluded_object` `:153`.
  - `app/checkers/smart.py`: `:160`, `:289`, `:307`.
  - `app/checkers/plugins.py`: `:170`, `:194`, `:643`, `:671`.
  - `app/checkers/forecast.py:93` und `app/checkers/context.py:40`.
- `app/routers/objects.py`: `_exception` (`:38`) und `list_objects` (`:75`, `:115`).
- `app/main.py` (`lifespan` `:39`): Startschritt der Migration nach `record_override_baseline`, vor
  `reconcile_builtin_templates`.
- `app/exception_migration.py` (neu, SPDX): Plan, Anwenden, Diff-Bericht, `__main__` mit `--dry-run`.
- Tests unter `apps/monitoring/tests/`:
  - `test_exception_scope.py`, `test_exceptions_api.py`, `test_migrations_smoke.py`;
  - `test_checks_crud.py`, `test_template_sync.py`, `test_module_sync.py`;
  - `test_smart_checker.py`, `test_agent_resources_checker.py`, `test_service_process_checker.py`,
    `test_plugin_checkers.py`, `test_checker_forecast.py`;
  - `test_check_engine.py`, `test_check_engine_context.py`, `test_objects_api.py`;
  - `test_scheduler.py`, `test_alerter.py`, `test_alert_bundle.py`, `test_bell_catch_up.py`,
    `test_status_history.py`;
  - `test_openapi_snapshot.py` mit `openapi.snapshot.json`;
  - neu (SPDX): `test_exception_migration.py`.

**Desktop-UI:** `apps/desktop/ui/src/lib/stores/monitoring.ts` (`ignoreService` `:489`) und `monitoring.test.ts`.

**Skripte:** `scripts/tests/upgrade_path_test.sh` (Seeds, Trockenlauf, Prüfung nach dem Update, Rückweg).

**Unverändert:**
- Server und Proxy: Präfix `exceptions` und Akteur-Header sind seit P1b frei (`monitoring_proxy/router.py:224`).
- Web, Agent, Gateway, VictoriaMetrics.
- `MonitorStateOut`.
- `scripts/update.sh`, `restore.sh`, `backup.sh`.

## Datenmodell / API / Migrationen

**Revision `<neu>_object_exceptions`** (nach `b6d8f0a2c4e6`):
- `monitor_exceptions.object_kind` String(20) NULL und `object_pattern` String(255) NULL.
- Ein Teilindex auf `(check_id, object_kind, object_pattern)` für nicht beendete Zeilen.
- Keine Datenänderung im Upgrade: Die Datenmigration ist der Startschritt (unten), weil sie die Vorlage eines Checks
  auflösen muss (`resolve_template_check`, `template_sync.py:152`). Das kann eine eingefrorene Revision nicht.
- **Downgrade** schreibt zurück, dann entfernt er Index, Zeilen und Spalten:
  - eine geltende `skip` → Spalte `enabled = false` und Marke `enabled`;
  - eine geltende `no_rating` → Klartext-Eintrag in die Liste der `config`.

  Rückweg nach einer echten Migration bleibt `restore.sh` (ADR §10).

**Ausnahme-API (additiv, `ExceptionInput`, `MonitorException.to_dict`):**
- Neue Eingabefelder: `scope_kind = "object"` mit `scope_value = <check-id>`, `object_kind`, `object_pattern`
  (1–255 Zeichen).
- Neue Wirkungen: `effect = "skip" | "no_rating"`.
- Regeln (sonst 422):
  - `skip` nur mit `check` und `permanent`;
  - `no_rating` nur mit `object` und `permanent`;
  - die Objektart muss zum Typ des Checks passen: `mount` → `agent_resources`, `disk` → `smart_health`,
    `container` → `docker_health`, `guest-backup` → `proxmox_backup`, `service` → `service_process`;
  - höchstens eine geltende `skip` je Check (409).
- Die Ausgabe ergänzt `objectKind`, `objectPattern` und `unstable` (`disk`, `container`).

**Checks-API:**
- `MonitorCheckOut` behält seine Form. `enabled` ist der effektive Wert, die Listen im `config` die zusammengesetzten
  (Ziel 4).
- `toggle` und `PUT enabled` antworten wie heute.
- Route-Docstrings sind OpenAPI-Beschreibungen. Ein geänderter Docstring zieht `openapi.snapshot.json` nach, im
  Verify der Task.

**Objekt-API:**
- `exception.source` hat neu den Wert `exception` auch für Objekt-Ausnahmen.
- Neu sind `effect` `no_rating` und `skip` sowie `scopeKind` `object`.
- Die Sortierung bleibt (ausgenommene zuletzt).

**Engine:**
- Je Lauf lädt sie die geltenden `no_rating`-Ausnahmen des Checks.
- Sie gibt dem Checker eine Liste `(muster, quelle)`. Die Quelle ist der Name der Einstellung für Einträge, die die
  Vorlage in der `config` vorgibt (maskiert), sonst die ID der Ausnahme.
- `excluded` (String(40)) trägt die Quelle; eine UUID passt.
- `DiskRules.ignore_mounts` (`context.py:40`) wird eine Musterliste.

**Startschritt und Trockenlauf:** `app/exception_migration.py`.
- `plan(db)` liefert die Änderungen.
- `apply(db, plan)` schreibt sie:
  - IDs per `uuid5` aus Check, Art und Muster bzw. aus Check und `skip`, damit ein zweiter Lauf nichts doppelt
    anlegt;
  - eine Marke in `monitor_seed_state`.
- `--dry-run` fährt `alembic upgrade head`, `plan` und `apply` in einer Transaktion. Danach gibt er den Bericht aus
  (Text, mit `--json` als JSON) und rollt zurück.

## Externe Integrationen

Keine. fnmatch ist Python-Standard (`fnmatch.fnmatchcase`; `[` öffnet eine Zeichenklasse, `[[]` trifft ein
wörtliches `[`, https://docs.python.org/3/library/fnmatch.html). Für Postgres gilt transaktionales DDL für
`CREATE TABLE`, `ALTER TABLE` und `CREATE INDEX` (ohne `CONCURRENTLY`); darauf baut der Trockenlauf. Vor T11 in der
Doku nachlesen: https://www.postgresql.org/docs/current/sql-begin.html (nicht verifiziert).

## Trade-offs & Alternativen

- **Ignorier-Globs** (Kevin 2026-11-27):
  - **Gewählt: Muster-Ausnahme.** Ein Abgleich für alle fünf Listen, Dienst-Muster bleiben gültig.
  - Verworfen: exakte Werte als Ausnahme und Dienst-Globs als Config-Filter. Das hätte zwei Wege ergeben, und die
    Globs hätten keine Spur.
- **Schwellen** (Kevin 2026-11-27):
  - **Gewählt: Rückfall auf die Vorlage**, mit allen Fällen im Diff-Bericht.
  - Verworfen: die Marke behalten. Die Vorlagen-Schwellen kämen dann nie an, und genau diese Gefahr nennt das ADR.
- **„Läuft“ als Ausdruck statt gespiegelter Spalte:**
  - **Gewählt: der Ausdruck.** Rund 20 Leser wechseln einmal auf einen Ausdruck. Danach haben System und Nutzer
    getrennte Quellen, und kein Sync dreht das Abschalten des Nutzers zurück.
  - Verworfen: die Spalte aus der Ausnahme spiegeln. Dafür müsste beim Ende der Ausnahme der Systemwert bekannt
    sein, und den kennt nur der jeweilige Sync.
- **Migration als Startschritt statt in der Revision:**
  - **Gewählt: der Startschritt.** Die Übersetzung braucht die aufgelöste Vorlage, also Anwendungscode. Ein
    Startschritt mit Marke läuft genau einmal. Der Trockenlauf fährt denselben Code.
  - Verworfen: SQL in der Revision. Das hätte die Vorlagen-Auflösung doppelt gebaut.
- **Vorlagen-Einträge bleiben in der `config`:**
  - Eine Vorlage ist ein Profil, kein Objekt (P4). Ihre Einträge erscheinen am Objekt mit der Quelle „Einstellung“
    wie in P1b.
  - Würden sie zu Ausnahmen, müsste jeder Sync Ausnahmen anlegen und beenden.

## Risiken & Rollback

- **Datenverlust beim Update.**
  - Abhilfe: `update.sh` legt vorher ein Backup an; der Rückweg ist `restore.sh` mit den Images des Releases.
  - Prüfung: Die Migration ist idempotent und je Quelleintrag getestet; `upgrade_path_test.sh` prüft sie auf einer
    VM vor dem Merge und Kevins Datenkopie vor der Beta.
- **Ein Leser fragt weiter die Spalte, und ein abgeschalteter Check läuft weiter oder alarmiert.**
  - Abhilfe: ein gemeinsamer Ausdruck, alle Leser in einer Task, je Leser-Gruppe ein Test mit `skip`.
  - Prüfung: Ein `grep` auf `MonitorCheck.enabled` im Branch-Review findet nur noch die Schreiber.
- **Muster blendet mehr aus als gewollt.**
  - Abhilfe: Exakte Listen werden maskiert; Tests mit `[`, `*` und `?` in Mount, Gerät, Container und Dienst.
- **Alte Desktops schreiben Listen.**
  - Abhilfe: Der Server übersetzt; ein Test schickt einen `PUT` mit einer Liste und liest dieselbe Liste zurück.
- **Schwellen springen nach dem Update auf Vorlagenwerte.**
  - Kevin hat das gewollt. Der Diff-Bericht nennt jeden Fall mit alten und neuen Werten, und der CHANGELOG-Eintrag
    sagt es.
- **Parallel-Arbeit an `schemas.py`, `checks.py` und den Checkern.**
  - Abhilfe: Vor jedem Push `origin/main` hereinmergen und `scripts/dev/overlap.sh` fahren. Wer als Zweiter merged,
    hängt seine Revision um und fährt die ganze Monitoring-Suite.
  - Bekannt am Gate: R-1825 (`feature/arch-monitoring-aio-status`) ändert die Push-Schleife in
    `routers/agent.py`, `_PROBE_MEASURE` in `routers/checks.py` und die Monitoring-Doku. Hier sind es nur Leserzeilen
    (T3) und Doku-Abschnitte (T14), und keiner der beiden hat eine weitere Migration.

## Doku-Impact

- `docs/developer/monitoring.html` + EN: Ausnahme-Modell mit Geltung Objekt und Wirkungen „nicht prüfen“ und
  „prüfen, nicht bewerten“; „läuft“; Übersetzung der Listen; Startschritt und Trockenlauf.
- `docs/developer/api-reference.html` + EN: `ExceptionInput`, Objekt-API, `enabled` effektiv.
- `docs/admin/monitoring.html` + EN: Abschalten und Ignorieren sind Ausnahmen mit Spur; Muster;
  Schwellen-Rückfall.
- `docs/admin/betrieb.html` + `docs/en/admin/operations.html`: der Trockenlauf vor dem Update.
- `changelog.d/arch-monitoring-neu-p1c.md`.

## Offene Fragen

Keine. Kevins vier Antworten vom 2026-11-27 (Muster-Ausnahme, Rückfall auf Vorlage, Datenkopie vor der nächsten
Beta, Ergebnis unvollständig) stehen in den Zielen.
