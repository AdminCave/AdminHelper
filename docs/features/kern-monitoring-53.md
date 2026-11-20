# kern-monitoring-53 — Monitoring-Nachlese: Objektzeilen unter Sperre, stabile Schlüssel, Verlauf, Hub im Hintergrund

Roadmap: R-1651, R-1653, R-1650, R-1642, R-1660.

## Problem

- **R-1651:** Das erste Ergebnis eines Checks legt seine Zustandszeilen (`MonitorState`, `monitor_object_state`) an, ohne dass es eine Zeile zu sperren gibt (`check_engine._apply_locked` und `routers/agent.py` sperren nur einen schon vorhandenen `MonitorState`). Zwei gleichzeitige Erstergebnisse desselben Checks sind dadurch nicht serialisiert. Einzelheiten in `tasks/private/`.
- **R-1653:** `_run_history_cleanup` (`apps/monitoring/app/scheduler.py`) löscht Objekte, die seit 30 Tagen verschwunden sind, per Bulk-Delete ohne die `MonitorState`-Sperre ihres Checks. Kehrt ein Objekt genau in diesem Moment zurück, arbeitet `apply_objects` mit einer Zeile, die das Cleanup gleichzeitig löscht.
- **R-1650:** (a) `history.server_events` faltet Ereignisse desselben Objekts innerhalb von 60 s zusammen (`_SAME_EVENT`). Gemeint war das nur für `origin = 'alert_log'`; Zustandswechsel (`origin = 'state'`) werden mitgefaltet. (b) `core/victoria.build_check_result_lines` kennt `not_collected` nicht und schreibt dafür 3 (`unknown`) nach VictoriaMetrics, während `apply_result` denselben Status als `ok` führt.
- **R-1642:** `docker_health` und `proxmox_backup` schlüsseln Container nach Namen und Gast-Backups nach VMID (`stable: false`). Der Agent liefert seit R-1639 (#596) `compose_number` je Container und `cluster_name` im Proxmox-Block. ADR 0004 §4 legt die Schlüssel fest: Container = Host + Compose-Projekt/Dienst/Nummer, Gast-Backup = Cluster + VMID.
- **R-1660:** `toggle_check` und `delete_check` (`routers/checks.py`) schicken die Entwarnung an den Hub synchron im Request. Ist der Hub nicht erreichbar, hängt die Antwort bis zum Timeout von 5 s.

## Ziel & Nicht-Ziele

- R-1651: Das Erstergebnis eines Checks wird genauso serialisiert wie jedes spätere. Ohne `MonitorState` sperrt der Schreiber die `MonitorCheck`-Zeile (`FOR UPDATE`) und liest den Zustand danach neu. Beide Pfade sind betroffen: `check_engine` (Pull) und `routers/agent.py` (Push).
- R-1653: Das Cleanup sperrt je betroffenem Check dessen `MonitorState` (`FOR UPDATE`, in Check-ID-Reihenfolge) und löscht dann dessen verschwundene Objekte. Damit gilt dieselbe Sperrfolge wie bei `apply_objects`.
- R-1650: Die Faltung greift nur noch für `alert_log`-Zeilen. VictoriaMetrics bekommt für `not_collected` den Wert 0, also ok, wie `apply_result`.
- R-1642: Liefert der Agent ein Compose-Projekt, einen Dienst und eine Nummer, ist der Container-Schlüssel `<host>/container/<projekt>/<dienst>/<nummer>` (`stable: true`). Liefert er einen Clusternamen, ist der Gast-Backup-Schlüssel `<host>/guest-backup/<cluster>/<vmid>` (`stable: true`). Ohne diese Angaben bleibt der heutige Rückfall mit `stable: false`. Kein Ziel: Gast-Backups über die Nodes eines Clusters zu einem Objekt ohne Host zusammenführen. Das bräuchte einen zentralen Check, die Prüfung bleibt je Host.
- R-1660: Die Entwarnung geht nach der Antwort an den Hub (FastAPI `BackgroundTasks`) und arbeitet mit einer eigenen DB-Sitzung (`release_hub_slot` bei Fehlschlag). Statuscode, Schema und Felder der Antwort bleiben gleich, denn `hub_status` steht nicht in der Antwort.

## Betroffene Komponenten & Dateien

Nur `apps/monitoring/`:
- `app/check_engine.py`: `_write_state`, `_apply_locked`
- `app/routers/agent.py`: `_locked_state` und Aufrufer
- `app/scheduler.py`: `_run_history_cleanup`
- `app/history.py`: `server_events`
- `app/core/victoria.py`: `build_check_result_lines`
- `app/checkers/plugins.py`: `_guest_object`, `_container_object` und ihre Aufrufer
- `app/routers/checks.py`: `toggle_check`, `delete_check`

Tests liegen unter `apps/monitoring/tests/`. Die Sperrtests für Postgres stehen in `test_check_engine_concurrency.py`.

## Datenmodell / API / Migrationen

Keine Migration und kein Vertragswechsel. Den OpenAPI-Snapshot prüft R-1660 mit, Docstrings bleiben unverändert. Mit R-1642 wechseln die Schlüssel vorhandener Container- und Gast-Backup-Objekte einmalig, sobald ein Agent mit den neuen Feldern meldet: Das alte Objekt wird `gone` (Cleanup nach 30 Tagen), das neue beginnt mit frischem Verlauf. Benachrichtigungen hängen am Check, nicht am Objekt, und ändern sich nicht.

## Externe Integrationen

VictoriaMetrics: Es ändert sich nur der Wert einer bestehenden Reihe (`monitor_check_status`), nicht das Format.

## Trade-offs & Alternativen

- R-1651: Statt der Sperre ließe sich `INSERT … ON CONFLICT DO NOTHING` einsetzen. Das verhindert nur den Fehler, serialisiert aber nicht die Auswertung (fail_count, Benachrichtigung). Empfehlung: Sperre auf `MonitorCheck`.
- R-1653: Statt der Sperre ginge eine Wiederholung in `apply_objects`. Das wäre schwerer zu beweisen. Empfehlung: Sperre in derselben Reihenfolge wie `apply_objects`.
- R-1642: Den Gast-Backup-Schlüssel ohne Host zu bilden (ADR „je Cluster“) wäre ohne zentralen Check sinnlos, weil `MonitorObjectState` je Check schlüsselt. Der Cluster gehört trotzdem in den Schlüssel, damit eine VMID auf einen Node umziehen kann, ohne mit einer gleichen VMID eines anderen Clusters zu kollidieren. Der Host im Schlüssel ist die einzige Abweichung vom ADR und wird dort vermerkt.

## Risiken & Rollback

Sperren können blockieren. Beide neuen Sperren gelten nur kurz und nur in der bestehenden Reihenfolge Check, dann State. Rollback heißt Revert der jeweiligen Task. Eine Schlüssel-Umstellung lässt sich nach einem Revert nicht mehr zurückdrehen: Die neuen Objekte werden dann `gone` und verschwinden nach 30 Tagen.

## Doku-Impact

Entwickler-Doku Monitoring (DE+EN) erhält die Tabelle der Objektschlüssel (container, guest-backup), den Vermerk im ADR 0004 und einen Satz zur Faltung im Verlauf. Die Admin-Doku bekommt zu Container und Gast-Backup je einen Satz, dass der Schlüssel jetzt eine Neuanlage überlebt. Dazu das Fragment `changelog.d/kern-monitoring-53.md`.

## Offene Fragen

Keine aus Kevins Bereich: Kein Vertrag und keine Migration ändern sich. Sichtbar wird nur, dass Container- und Gast-Backup-Objekte nach dem Agent-Update einmal neu erscheinen. Das hat die Roadmap-Zeile so angenommen.
