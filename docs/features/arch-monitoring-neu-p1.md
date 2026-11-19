<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Neuordnung, Phase 1a: Verlauf und Objekte

Roadmap R-1559 (mit R-0805), Grundlage `docs/adr/0004-monitoring-neuordnung.md` (abgenommen 2026-11-19). Stand
`origin/main@39a08c2a7`.

## Problem / Motivation

- **Verlauf hängt an der Benachrichtigung.** Die Verlaufsmarken eines Servers (`GET /status/server/{id}/history`,
  `apps/monitoring/app/routers/checks.py:993`) liest `server_events` (`apps/monitoring/app/history.py:230`) aus
  `MonitorAlertLog`. Diese Zeilen entstehen nur, wenn eine Alarmregel sendet: ein Wechsel ohne passende Regel, in der
  Wartung oder mit `info` fehlt im Verlauf (ADR §5).
- **Ein Check hat genau einen Zustand.** `MonitorState` (`apps/monitoring/app/models.py:181`) trägt Status und „seit“
  für den ganzen Check; welche Platte, welcher Pool oder welcher Dienst ihn trägt und seit wann, steht nur in
  `_details`, das jeder Lauf neu schreibt. „Was ist kaputt und seit wann“ ist je Objekt nicht beantwortbar, und alles,
  was das ADR auf Objekten aufbaut (Ausnahmen, Regeln, Probleme, Objekt-Tabelle), fehlt der Boden.
- **R-0805:** `execute_check` (`apps/monitoring/app/check_engine.py:459`, rund 130 Zeilen) und `HttpChecker.run`
  (`apps/monitoring/app/checkers/http.py:31`) sind über 100 Zeilen gewachsen; diese Phase ändert `execute_check`,
  deshalb kommt die Zerlegung zuerst.

## Ziel & Nicht-Ziele

Kevin hat P1 am 2026-11-19 in fünf Schritte geteilt; dies ist **P1a „Verlauf + Objekte“**.

Ziel:
1. **Statuswechsel-Log** (`monitor_status_log`): jede Änderung des gedämpften Status eines Checks und jedes Objekts,
   90 Tage, unabhängig von Alarmregeln. Die Migration übernimmt die vorhandenen Alarm-Log-Zeilen, damit der Verlauf
   beim Update nicht leer wird.
2. **Verlaufsmarken aus dem Log:** `server_events` liest das neue Log, Antwortform unverändert.
3. **Objektzustand** (`monitor_object_state`, ADR §5): Checker liefern neben `_details` ein Objektergebnis
   `_objects`; geschrieben wird nur bei Änderung (ADR §12.4, Variante C), mit „seit“, „schlecht seit“, Dämpfung je
   Objekt und „verschwunden“. Checks ohne Objektergebnis bekommen ein Rückfall-Objekt.
4. **Typisierte Objekte** für `smart_health` (disk), `zfs_health` (pool), `docker_health` (container),
   `proxmox_backup` (guest-backup), `agent_resources` (cpu, memory, mount, sensor), `service_process` (service),
   `system_state` (reboot, updates, clock), mit Schlüsseln nach ADR §4.
5. **Lese-API** `GET /objects` im Monitoring-Dienst und das Präfix `objects` in der Freigabeliste des Server-Proxys.
6. Der Status **„nicht erhoben“** (`not_collected`) erscheint nur in der Objekt-API (Kevin 2026-11-19);
   `MonitorStateOut` behält das alte Vokabular, alte Desktops sehen nichts Neues.

Nicht-Ziele (Kevin 2026-11-19):
- **P1b** Ausnahme-Modell (Wartung als Fassade), **P1c** Migration von `enabled` und den Ignorierlisten,
  **P1d** Regel-Schicht, **P1e** Agent-Datenlücken: eigene Roadmap-Zeilen. Ignorierte Objekte (`ignore_devices`,
  `ignore_containers`, `ignore_mounts`, `ignore` der Dienste, `exclude_vmids`) bleiben in P1a, wie heute, außen vor.
- **P2** (R-1560): Checker-Umstellung auf Sensor+Regelsatz samt `rises`/`not in`/`unless`-Liste, wertgebundene und
  bedingte Ausnahmen, Geltung Tag/Cluster, VictoriaMetrics-Reihen je Objektschlüssel, jede Oberfläche.
- **P3** (R-1561): Problem-Schlüssel `obj:`, Recovery-Hold je Objekt, „veraltet“ (`stale`), Benachrichtigung je
  Objekt. Objekte melden in P1a nichts; Alerting, Glocke und `notified_status` bleiben beim Check.
- Typisierte Objekte für `ping`, `tcp`, `http`, `probe`, `central`, `agent_ping`: in P1a das Rückfall-Objekt.
- Desktop und Web: keine Änderung (es gibt noch keinen Verbraucher der Objekt-API).

## Betroffene Komponenten & Dateien

Monitoring (`apps/monitoring/`):
- `app/check_engine.py`: `execute_check` :459 (R-0805 in Schritte; `_objects` neben `_details` :530 aus den Metriken
  nehmen, bevor sie zu VictoriaMetrics gehen), `apply_result` :187 (Log-Zeile bei Statuswechsel, `apply_objects`
  unter der schon gesperrten `MonitorState`-Zeile), Dämpfung `next_fail_count` :83 / `effective_status` :105 je Objekt
  wiederverwendet.
- `app/routers/agent.py`: `_evaluate_push_check` (`_details` :466, `apply_result` :477) nimmt `_objects` ebenso.
- `app/checkers/http.py:31` (`HttpChecker.run`, R-0805).
- neu `app/objects.py`: Objektergebnis lesen und kappen, Schlüssel bilden, `apply_objects`.
- `app/models.py`: `MonitorStatusChange` (`monitor_status_log`), `MonitorObjectState` (`monitor_object_state`).
- `alembic/versions/`: zwei Revisionen nach `a7c9e1f3b5d7` (Log samt Übernahme, dann Objektzustand).
- `app/history.py:230` `server_events`.
- `app/scheduler.py`: neuer Tagesjob neben `_run_alert_log_cleanup` :169 / `schedule_alert_log_cleanup` :198;
  Aufruf in `app/main.py:99`.
- Checker: `app/checkers/smart.py` (`evaluate` :255), `app/checkers/plugins.py` (`ProxmoxBackupChecker.evaluate`
  :106, `ZfsHealthChecker.evaluate` :281, `DockerHealthChecker.evaluate` :499), `app/checkers/agent.py`
  (`AgentResourcesChecker.evaluate` :620, `ServiceProcessChecker.evaluate` :685), `app/checkers/system.py`
  (`SystemStateChecker.evaluate` :100).
- neu `app/routers/objects.py`, `app/routers/__init__.py` (`all_routers` :15), `app/schemas.py`,
  `tests/openapi.snapshot.json`.

Server (`apps/server/`): `app/modules/monitoring_proxy/router.py:78` (`_ALLOWED_PATH_PREFIXES`),
`tests/test_monitoring_proxy_allowlist.py`.

Nicht betroffen: Agent (P1e), Desktop, Web, Gateway, CA, Install.

## Datenmodell / API / Migrationen

**`monitor_status_log`** (Revision 1):

| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` | Integer PK | — |
| `check_id` | String FK `monitor_checks.id` `ON DELETE CASCADE` | wie `monitor_alert_log` |
| `object_key` | String(200) NULL | NULL = der Check selbst, sonst der Objektschlüssel |
| `old_status`, `new_status` | String | gedämpfter Status vorher und nachher |
| `at` | DateTime (naive UTC) | Zeitpunkt des Wechsels |
| `origin` | String | `state` (geschrieben) oder `alert_log` (übernommen) |

Indizes `(check_id, at)` und `(at)`. Die Revision übernimmt jede Zeile von `monitor_alert_log` als Check-Zeile
(`origin = alert_log`, `at = sent_at`); `server_events` faltet die Zeilen mehrerer Regeln wie heute über
`_SAME_EVENT` (60 s). Downgrade löscht die Tabelle; `monitor_alert_log` bleibt in beiden Richtungen unberührt.
Geschrieben wird in `apply_result`, wenn der gedämpfte Status wechselt, und in `apply_objects` je Objektwechsel (das
Rückfall-Objekt schreibt keine eigene Zeile, es ist der Check). Aufbewahrung 90 Tage (ADR §5) über einen Tagesjob
`system:history-cleanup`.

**`server_events`** liest Check-Zeilen (`object_key IS NULL`) des Logs statt `MonitorAlertLog`; Antwort
`{at, checkId, checkName, status}`, `EVENT_LIMIT` und `_SAME_EVENT` bleiben. Ein Erstergebnis `ok`/`info` (von
`pending`) ist kein Ereignis, wie heute. Neu sichtbar werden Wechsel ohne sendende Alarmregel, in der Wartung und von
oder nach `info`: das ist der Zweck (ADR §5).

**`monitor_object_state`** (Revision 2, ADR §5):

| Spalte | Typ | Bedeutung |
|---|---|---|
| `check_id` | String FK `ON DELETE CASCADE`, PK | — |
| `object_key` | String(200), PK | `<server>/<art>/<id>`, zentral ohne Server (ADR §4) |
| `kind`, `name` | String | Objektart, Anzeigename |
| `status`, `reason` | String | gedämpfter Objektstatus, ein Satz Grund (gekappt wie `message`) |
| `since` | DateTime | letzter Statuswechsel |
| `bad_since` | DateTime NULL | seit wann `warning`/`critical`/`unknown`, über Wechsel dazwischen hinweg |
| `fail_count` | Integer | Dämpfung je Objekt, gedeckelt auf `consecutive_fails` |
| `stable` | Boolean | `false` = Schlüssel aus dem Rückfall (ADR §4 „instabil“) |
| `gone_at` | DateTime NULL | fehlte in einem vollständigen Ergebnis |

**Objektergebnis** (intern, Checker → Engine): `metrics["_objects"] = {"complete": bool, "items": [{"kind", "id",
"name", "status", "reason", "stable"?}]}`, aus den Metriken genommen wie `_details`, nie an VictoriaMetrics.
`apply_objects` bildet den Schlüssel `<server>/<kind>/<id>` (ohne Server bei zentralen Checks; über 200 Zeichen mit
Hash-Suffix), liest den Bestand des Checks mit einer Abfrage, dämpft je Objekt (`next_fail_count`,
`effective_status`; `not_collected` gilt wie `ok` als gesund) und schreibt nur geänderte Zeilen. Ein vollständiges
Ergebnis setzt `gone_at` für fehlende Objekte und löscht es bei Rückkehr; ein unvollständiges (Auto-Modus der
Dienste, fehlender Block im Report) lässt fehlende Objekte unverändert. Fehlt `_objects`, entsteht ein Rückfall-Objekt
`<server>/check/<check_id>` (Art `check`) mit dem gedämpften Check-Status. Übersprungene Läufe (`RunSkipped`,
Lastabwurf) berühren keine Objekte. Verschwundene Objekte löscht der Tagesjob nach 30 Tagen (Kevin 2026-11-19).

Schlüssel je Art (ADR §4; Lücken schließt P1e):

| Art | Checker | `id` | Rückfall (`stable = false`) |
|---|---|---|---|
| `disk` | smart_health | WWN, sonst Modell + Seriennummer (heute der Normalfall: der Agent sendet keine WWN) | Gerätepfad |
| `pool` | zfs_health | Poolname | — |
| `guest-backup` | proxmox_backup | VMID | immer instabil bis zur Cluster-ID (R-0519) |
| `container` | docker_health | Compose-Projekt/Dienst/Nummer | Containername (heute immer, die Nummer fehlt) |
| `cpu`, `memory` | agent_resources | — (Art allein) | — |
| `mount` | agent_resources | Pfad | — |
| `sensor` | agent_resources | Chip/Label | — |
| `service` | service_process | voller Unit-Name | — |
| `reboot`, `updates`, `clock` | system_state | — (Art allein) | — |

Eine schlafende Platte meldet weder Modell noch Seriennummer (R-1569); mit früherer Messung fehlt sie im Ergebnis, das dann unvollständig ist, und ihr Objekt behält den letzten Stand.

„Nicht erhoben“ liefern in P1a: eine schlafende Platte ohne frühere Messung und eine gestoppte VM, die
`exclude_stopped` nicht bewertet (Regel, keine Ausnahme, ADR §10; der Objekt-Teil von R-1534).

**API** (additiv, ADR §10): `GET /objects` mit `server_id`, `check_id`, `kind`, `include_gone` (Standard `false`),
`limit`/`offset` und `X-Total-Count` wie die übrigen Listen; Einträge `{checkId, checkName, serverId, key, kind, name,
status, reason, since, badSince, stable, goneAt, lastCheck}` (`lastCheck` aus `MonitorState`), schlechteste zuerst
nach ADR §3 (`critical` > `warning` > `unknown` > `info` > `not_collected` > `ok`), dann Name. Über den Proxy
`GET /api/monitoring/objects` (nur Admins, wie jeder Proxy-Pfad). `MonitorStateOut`, `MonitorCheckOut` und `_details`
bleiben unverändert.

## Externe Integrationen

Keine. VictoriaMetrics bekommt weiter den Rohstatus und dieselben Metriken; `_objects` geht nie dorthin.

## Trade-offs & Alternativen

- **Log-Übernahme statt Lesen aus zwei Quellen:** die Revision kopiert `monitor_alert_log` einmal; die Alternative,
  vor einem Stichtag das Alarm-Log zu lesen, braucht einen gespeicherten Stichtag und vermischt Benachrichtigungen
  mit Wechseln. Ohne Übernahme wäre der Verlauf nach dem Update 90 Tage lang lückenhaft (ADR §13: jede Phase besser
  als vorher). Empfehlung und Wahl: Übernahme.
- **Schreiben nur bei Änderung (Variante C)** statt Upsert je Report: ADR §12.4 misst 5 statt 33 ms je Transaktion
  und 240 statt 24 000 Zeilenversionen; kein `last_seen` je Objekt, „zuletzt gesehen“ ist `MonitorState.last_check`.
- **`apply_objects` in `apply_result`:** beide Wege (Scheduler und Push) laufen dort unter der gesperrten
  `MonitorState`-Zeile; eine zweite Sperre oder ein eigener Pfad je Weg entfällt.
- **Rückfall-Objekt** statt Objekt-API nur für typisierte Checks: die API deckt sofort jeden Check ab, P2 kann jede
  Ansicht auf Objekten bauen.
- **Dämpfung je Objekt ohne Recovery-Hold:** der Hold braucht `notified_status` je Objekt, das kommt mit der
  Benachrichtigung je Objekt in P3.
- **Retention als Konstante** (90 bzw. 30 Tage) statt neuer Umgebungsvariablen (YAGNI; ADR §5 nennt 90 Tage).

## Risiken & Rollback

- **Migration:** zwei additive Revisionen; die Übernahme liest `monitor_alert_log` nur. Downgrade löscht die neuen
  Tabellen. Tests: Upgrade/Downgrade je Revision in `tests/test_migrations_smoke.py`, Modell = Migration
  (`test_migration_chain_matches_models`).
- **Last:** je Ergebnis eine Abfrage auf den Bestand des Checks und nur geänderte Zeilen; Objektzahl je Ergebnis
  gekappt (`capped_objects`). Sperren: nur unter der `MonitorState`-Sperre des Checks (Postgres-Test in
  `tests/test_check_engine_concurrency.py`).
- **Alte Desktops:** `_details`, `MonitorStateOut` und die Verlaufsantwort behalten ihre Form; Tests je Checker
  prüfen, dass `_details` unverändert bleibt.
- **Verlauf zeigt mehr Marken** (Wechsel ohne Regel, in der Wartung, `info`): gewollt (ADR §5).
- **Rollback:** Revert des Merges plus `alembic downgrade` auf `a7c9e1f3b5d7`; Alarm-Log, Zustände und Checks bleiben
  unberührt.

## Doku-Impact

`docs/developer/monitoring.html` + EN (Statuswechsel-Log, Objektzustand und Objektergebnis, Tagesjob, Quelle der
Verlaufsmarken), `docs/developer/api-reference.html` + EN (`GET /objects`, Präfix `objects` am Proxy),
`docs/admin/monitoring.html` + EN, wo es die Verlaufsmarken beschreibt; `changelog.d/arch-monitoring-neu-p1.md`.

## Offene Fragen

Keine für Kevin. Entschieden von Kevin 2026-11-19: der Schnitt in P1a–P1e, die Punkte für P2, „nicht erhoben“ nur in
der Objekt-API, 30 Tage für verschwundene Objekte. Die Session entscheidet im Bau: Log-Übernahme (oben), „schlecht“ =
`warning`/`critical`/`unknown`, Hash-Suffix für lange Schlüssel. Offene Punkte des `advisor` für spätere Schritte
(Akteur-Header Proxy → Monitoring, Ignorier-Globs der Dienste, Schwellen-Rückfall bei ignore-only-Override,
Datenkopie für P1c) stellt deren Planung.
