<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Neuordnung, Phase 1b: Ausnahme-Modell

Roadmap R-1636, Grundlage `docs/adr/0004-monitoring-neuordnung.md` (§7 Ausnahmen, §10 Migrationsplan), Vorgänger P1a
(R-1559, `docs/features/arch-monitoring-neu-p1.md`). Stand `origin/main@201914265`.

## Problem / Motivation

- **Drei Arten, „hier nicht“ zu sagen, und keine davon ist eine Ausnahme.** Wartungsfenster stehen in
  `monitor_maintenance` (`apps/monitoring/app/models.py:537`), ein ausgeschalteter Check in `enabled`, ausgenommene
  Einträge in den Ignorierlisten der Check-Konfiguration. Keine trägt Grund, „wer“ oder „seit wann“, keine erscheint
  in einer gemeinsamen Liste, und das ADR (§7) baut Problem, Abdeckung und die Oberfläche von P2 auf genau einem
  Ausnahme-Modell auf.
- **Ausgenommene Objekte verschwinden.** Die Checker überspringen, was eine Einstellung ausnimmt:
  `exclude_vmids` (`apps/monitoring/app/checkers/plugins.py:169`, `:188`), `ignore_containers` (`plugins.py:641`),
  `ignore_devices` (`apps/monitoring/app/checkers/smart.py:288`), `ignore_mounts`
  (`apps/monitoring/app/checkers/agent.py:435`, `:580`) und die Dienst-Globs (`agent.py:981`). In der Objekt-API von
  P1a (`GET /objects`) fehlen diese Objekte ganz; das ADR (§3) will sie grau am Ende, mit Grund. R-1534 (ausgenommene
  VMs) und R-1538 brauchen das.
- **Wer eine Wartung angelegt oder gelöscht hat, weiß niemand.** Der Server-Proxy schreibt je Schreibzugriff eine
  Audit-Zeile ohne Inhalt (`apps/server/app/modules/monitoring_proxy/router.py:99`); das Monitoring kennt den Akteur
  nicht, und `DELETE /maintenance/{id}` löscht die Zeile hart (`apps/monitoring/app/routers/maintenance.py:86`).

## Ziel & Nicht-Ziele

Kevin hat P1 am 2026-11-19 in fünf Schritte geteilt; dies ist **P1b „Ausnahme-Modell“**. Entscheidungen Kevins vom
2026-11-25 (Fragenblock der Planung): Kombinationen, die noch nicht wirken, lehnt die API mit 422 ab; Wartungsfenster
werden 1:1 migriert und per Äquivalenztest abgenommen, die Abnahme an einer Kopie echter Daten fährt P1c; Löschen
beendet eine Ausnahme, beendete bleiben 90 Tage; per Einstellung ausgenommene Objekte erscheinen als „nicht erhoben“
mit Ausnahme-Feld.

Ziel:
1. **Eine Ausnahme-Tabelle** `monitor_exceptions`: Geltung × Wirkung × Dauer, Grund, Herkunft, und für Anlegen,
   Ändern und Beenden je Zeitpunkt, Name und ID des Akteurs (ADR §7 „Spur“).
2. **`/exceptions`** (Liste, Anlegen, Ändern, Beenden) hinter dem Admin-Proxy. In P1b wirkt nur „nicht melden“
   (`no_notify`) mit der Geltung Check, Check-Typ, Server oder alle; jede andere Kombination ist 422.
3. **Wartung als Fassade:** jedes Wartungsfenster wird per Alembic 1:1 mit gleicher ID zur Ausnahme (Server bzw.
   alle, `no_notify`, einmalig oder wöchentlich mit Zeitzone). `/maintenance` liest und schreibt danach nur noch
   Ausnahmen in Wartungsform; `MaintenanceInput`/`MaintenanceOut` (`apps/monitoring/app/schemas.py:225`, `:489`)
   bleiben unverändert, der alte Desktop merkt nichts.
4. **Alle Leser der Wartung lesen Ausnahmen:** Stummschalten (`muted_reason`/`muted_reasons`), die Bündel-Prüfung
   (`_awaits_check`), die Wartungsbänder im Verlauf und das Aufräumen eines gelöschten Servers.
5. **Akteur vom Proxy:** der Server-Proxy reicht den angemeldeten Admin als vertrauenswürdige Header weiter; das
   Monitoring speichert ihn an der Ausnahme.
6. **Ausgenommene Objekte sichtbar:** die fünf Checker melden per Einstellung ausgenommene Einträge als Objekt mit
   Status `not_collected` und Marke `excluded`, statt sie wegzulassen; `GET /objects` sortiert sie ans Ende und
   trägt je Objekt das Feld `exception` (die engste greifende Ausnahme oder die Einstellung).

Nicht-Ziele (ADR §13, Kevins Schnitt):
- **„Nicht prüfen“ (`skip`) und „prüfen, nicht bewerten“ (`no_rating`)** samt Migration von `enabled` und den
  Ignorierlisten ins Modell: P1c (R-1637). Beides braucht die Umstellung der Check-Engine (`apply_result`,
  `_load_run`, `execute_check`), des Schedulers und des Push-Pfads; käme nur das Modell, gäbe es ein Release lang
  zwei Abschalter mit verschiedener Bedeutung (`enabled` und `skip`). Die Ignorierlisten bleiben in P1b die Quelle;
  die Objekt-API zeigt sie nur.
- Geltung **Regel**: P1d (R-1638). Geltung **Objekt** wirkt erst mit Objekt-Wirkungen (P1c) und der Meldung je Objekt
  (P3). **Tag, Cluster, „nur für mich“**, wertgebundene und bedingte Ausnahmen, Rückfrage und die Liste
  „Ausgeblendet“ in der Oberfläche: P2 (R-1560).
- Keine Oberfläche: Desktop und Web bleiben unverändert (der Desktop spricht weiter `/maintenance`).
- Kein Drop von `monitor_maintenance`: die Tabelle bleibt bis zum Abschluss von P1 stehen (ADR §10).

## Betroffene Komponenten & Dateien

Monitoring (`apps/monitoring/`):
- `app/models.py` — neues Modell `MonitorException` (Ausnahme im Sinn von ADR §7, keine Python-Exception); Spalte
  `excluded` an `MonitorObjectState` (`:327`); `MonitorMaintenance` (`:537`) bleibt eingefroren, mit `synonym`
  `duration_kind` → `kind` und `reason` → `note`, damit der Auswerter beide Zeilenarten liest.
- `alembic/versions/<rev>_exceptions.py` (neu, SPDX) — `down_revision = "e3a5c7e9f1b2"` (Kopf heute:
  `e3a5c7e9f1b2_object_state.py`).
- `app/maintenance.py` — `maintenance_intervals` (`:84`) und `is_in_maintenance` (`:119`) lesen `duration_kind` und
  `reason`; die Zeitlogik (`_once_active`, `_weekly_active`, DST, Mitternacht) bleibt.
- `app/exception_scope.py` (neu, SPDX) — wann eine Ausnahme gilt (aktiv, nicht beendet, Dauer läuft) und welche
  einen Check deckt; die engste gewinnt (Check > Check-Typ > Server > alle).
- `app/alerter.py` — `muted_reason` (`:371`), `muted_reasons` (`:441`).
- `app/alert_bundle.py` — `_awaits_check` (`:191`).
- `app/history.py` — `server_maintenance` (`:274`).
- `app/server_cleanup.py` — `known_server_ids` (`:43`), `cleanup_server` (`:104`).
- `app/routers/maintenance.py` — Fassade über `monitor_exceptions`.
- `app/routers/exceptions.py` (neu, SPDX), `app/routers/__init__.py`, `app/schemas.py` (Ein-/Ausgabe der Ausnahme,
  `MonitorObjectOut` `:321` um `exception`, Kommentar zu `mutedReason` `:365`).
- `app/core/actor.py` (neu, SPDX) — Akteur aus den Proxy-Headern.
- `app/scheduler.py` — Tagesjob `_run_history_cleanup` (`:216`) löscht seit über 90 Tagen beendete Ausnahmen.
- `app/objects.py` — Helfer für ein ausgenommenes Objekt, `_entry` (`:111`) und `_apply_item` (`:237`) tragen
  `excluded`.
- `app/checkers/plugins.py`, `app/checkers/smart.py`, `app/checkers/agent.py` — je Ignorierliste eine Stelle.
- `app/routers/objects.py` — Sortierung und Feld `exception` (`list_objects` `:39`).
- Tests: neu `tests/test_exception_scope.py`, `tests/test_exceptions_api.py`; geändert
  `tests/test_migrations_smoke.py`, `tests/test_maintenance_router.py` (Beenden statt Löschen, Akteur),
  `tests/test_objects_api.py`, die Checker-Tests der fünf Listen, `tests/openapi.snapshot.json`; die Tests, die
  Wartungsfenster direkt in `monitor_maintenance` anlegen (`tests/_helpers.py`, `test_alerter.py`,
  `test_alerter_sent_state.py`, `test_alert_bundle.py`, `test_status_history.py`, `test_status_log.py`,
  `test_bell_catch_up.py`, `test_status_page_api.py`, `test_template_sync.py`, `test_response_shapes.py`), legen sie
  über einen Helfer als Ausnahme in Wartungsform an; ihre Erwartungen bleiben.

Server (`apps/server/`):
- `app/modules/monitoring_proxy/router.py` — Präfix `exceptions` in `_ALLOWED_PATH_PREFIXES` (`:82`); Akteur-Header
  in `proxy_to_monitoring` (`:189`, Header-Block `:227`).
- `tests/test_monitoring_proxy_allowlist.py` (Präfix-Gleichheit Router ↔ Liste ↔ Doku), Proxy-Test für die Header.

Unverändert: `check_engine.py`, `scheduler.load_all_checks`, der Push-Pfad (`routers/agent.py`), `module_plan`,
VictoriaMetrics, `MonitorCheckOut`, `MonitorStateOut`, Desktop, Web, Agent.

## Datenmodell / API / Migrationen

### Tabelle `monitor_exceptions`

| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` | String PK | UUID; migrierte Wartungsfenster behalten ihre ID |
| `scope_kind` | String | `check`, `check_type`, `server`, `all` (später `object`, `rule`, `tag`, `cluster`) |
| `server_id` | String NULL, Index | Geltung `server`: der Server; Geltung `check`: der Server des Checks (für Aufräumen und Liste) |
| `check_id` | String NULL, FK `monitor_checks.id` ON DELETE CASCADE | Geltung `check` |
| `check_type` | String NULL | Geltung `check_type`, für alle Server (die Einschränkung auf einen Tag folgt in P2) |
| `effect` | String | `no_notify` (später `skip`, `no_rating`, `mute_me`) |
| `duration_kind` | String | `permanent`, `once`, `weekly` |
| `starts_at`, `ends_at` | DateTime NULL | `once`, naive UTC wie bei der Wartung |
| `weekdays`, `start_time`, `duration_minutes`, `timezone` | wie `monitor_maintenance` | `weekly`; Zeitzone IANA, Standard `UTC` |
| `reason` | String NULL | Grund, optional (ADR §7) |
| `enabled` | Boolean | der Schalter, den der Desktop an Wartungsfenstern umlegt |
| `origin` | String | `api` (über `/exceptions`), `maintenance` (über die Fassade), `migration` (aus `monitor_maintenance`) |
| `created_at`, `created_by`, `created_by_id` | | Anlegen: Zeit, Anzeigename, `<typ>:<id>` des Akteurs |
| `updated_at`, `updated_by`, `updated_by_id` | NULL | letzte Änderung |
| `ended_at`, `ended_by`, `ended_by_id` | NULL | Beenden; gesetzt heißt: wirkt nicht mehr |

Geltung je Art als eigene Spalte statt eines freien Werts: der Fremdschlüssel räumt Check-Ausnahmen mit dem Check
weg wie `monitor_object_state`, und P1d/P2 fügen `object_key`, `rule_key`, `tag` additiv an. Die Prüfung, welche
Spalten zu welcher Art gehören, macht die API (Validierung an der Grenze), nicht die Datenbank.

**Gilt** heißt: `enabled`, nicht beendet, und die Dauer läuft (`permanent` immer, `once` mit
`starts_at <= jetzt < ends_at`, `weekly` mit der Zeitlogik von `app/maintenance.py`). **Deckt** einen Check:
`check` über `check_id`, `check_type` über den Typ, `server` über `server_id`, `all` immer. Greifen mehrere, gewinnt
die engste (ADR §7: Check > Check-Typ > Server; `all` ist die weiteste, das globale Wartungsfenster).

**Wartungsform** = Geltung `server` oder `all`, Wirkung `no_notify`, Dauer `once` oder `weekly`, nicht beendet. Genau
diese Zeilen sieht die Fassade, gleich welcher Herkunft.

### Migration (eine Revision)

- Legt `monitor_exceptions` an und `monitor_object_state.excluded` (String(40) NULL, der Name der Einstellung).
- Übernimmt jede Zeile aus `monitor_maintenance` mit gleicher ID: `server_id` NULL → Geltung `all`, sonst `server`;
  `kind` → `duration_kind`, die Zeitfelder unverändert, `note` → `reason`, `enabled` (NULL → `false`: der Auswerter
  übersprang solche Zeilen schon), `created_at` bleibt, `created_by` NULL, `origin = 'migration'`. Idempotent
  (`WHERE NOT EXISTS` je ID). `monitor_maintenance` bleibt unverändert stehen.
- **Downgrade:** schreibt den Stand der Fassade zurück (`monitor_maintenance` leeren, jede Ausnahme in Wartungsform
  einfügen; `reason` → `note`), dann `excluded` und die Tabelle weg. Ausnahmen ohne Wartungsform (Check, Check-Typ,
  dauerhaft) gehen dabei verloren; der vollständige Rückweg ist `restore.sh` (ADR §10).
- Abnahme (Kevin 2026-11-25): `tests/test_migrations_smoke.py` auf Postgres legt Wartungsfenster jeder Form an
  (einmalig, wöchentlich über Mitternacht, Zeitzonen mit Sommerzeitwechsel, global, ausgeschaltet, ohne Zeitfelder),
  fährt Upgrade, prüft für jedes Fenster und jeden Server über ein Zeitraster `is_in_maintenance(alt) ==` „eine
  Ausnahme deckt“ (neu), dass `GET /maintenance` dieselbe Antwort gibt wie `to_dict()` der alten Zeilen, dann
  Downgrade → Upgrade (Rückweg und Idempotenz). Die Abnahme an einer Kopie von Kevins Daten fährt P1c (R-1637) für
  beide Schritte.

### API

`/exceptions` (neu, `require_internal`, über den Proxy nur für Admins):
- `GET /exceptions?include_ended=false` → Liste nach `created_at`, Filter `server_id` und `check_id`; beendete nur
  auf Anfrage; ohne Paging (die Liste ist klein, Wartungsfenster heute auch).
- `POST /exceptions` (201), `PUT /exceptions/{id}` (volles Update, 404 unbekannt, 409 beendet),
  `DELETE /exceptions/{id}` (204; setzt `ended_*`, 404 unbekannt, 409 schon beendet). Kein hartes Löschen.
- Eingabe (snake_case wie `MaintenanceInput`): `scope_kind`, `scope_value` (Check-ID, Check-Typ oder Server-ID;
  bei `all` leer), `effect`, `duration_kind`, die Zeitfelder wie bei der Wartung (bei `once` ist `starts_at`
  optional und wird „jetzt“), `reason` (höchstens 500 Zeichen), `enabled`. 422 für jede Kombination außer `no_notify`
  × `check`/`check_type`/`server`/`all`, für einen unbekannten Check oder Check-Typ und für Zeitfelder wie bei
  `MaintenanceInput`.
- Ausgabe (camelCase): `id`, `scopeKind`, `scopeValue`, `serverId`, `effect`, `durationKind`, `startsAt`, `endsAt`,
  `weekdays`, `startTime`, `durationMinutes`, `timezone`, `reason`, `enabled`, `origin`, `createdAt`, `createdBy`,
  `createdById`, `updatedAt`, `updatedBy`, `updatedById`, `endedAt`, `endedBy`, `endedById`. Die API liefert Daten,
  keine Texte: „unbekannt (migriert)“ macht die Oberfläche aus `origin = migration` und leerem `createdBy`.

`/maintenance` (Fassade, Vertrag unverändert): `GET` listet die Ausnahmen in Wartungsform; `POST` legt eine an
(`origin = maintenance`); `PUT` und `DELETE` wirken nur auf Ausnahmen in Wartungsform (sonst 404); `DELETE` beendet
statt zu löschen, das Fenster verschwindet aus der Liste wie bisher. Einzige sichtbare Abweichung: ein Altfenster mit
`enabled` NULL (nur außerhalb der API entstanden) liest sich danach als `false`.

`mutedReason` (Statusrouten, `MonitorCheckOut` unverändert): Reihenfolge bleibt stummer Check > Ausnahme > Host
down. Ist die engste greifende Ausnahme in Wartungsform, bleibt der Wert `"maintenance window"`; sonst neu
`"exception"`. Der alte Desktop zeigt für einen unbekannten Wert keinen Text (`mutedReasonText`,
`apps/desktop/ui/src/lib/models/monitoringText.ts:50`). Endet eine Ausnahme, meldet der bestehende Sent-State-Abgleich
den aktuellen Zustand nach, wie heute am Ende eines Wartungsfensters (ADR §7, Frage 9).

`GET /objects`: ausgenommene Objekte stehen am Ende (Sortierung `excluded` zuletzt, dann schlechteste zuerst, dann
Name). Neues Feld `exception` je Objekt, `null` ohne Ausnahme: `source` (`setting` oder `exception`), `effect`
(`skip` für eine Einstellung, sonst die Wirkung), `setting` (der Name der Einstellung), `id`, `scopeKind`, `reason`.
Die Einstellung gilt als Objekt-Geltung und schlägt jede Ausnahme-Zeile; danach die engste geltende Ausnahme des
Checks. Die Ausnahmen lädt eine Abfrage je Aufruf, die Zuordnung geschieht nach dem Paging. `no_notify` färbt nicht
und sortiert nicht.

### Ausgenommene Objekte

Ein Helfer in `app/objects.py` baut das Objekt: Status `not_collected`, Grund `Excluded by setting <name>`, Marke
`excluded = <name>`. Die Checker rufen ihn an der Stelle, an der sie heute `continue` machen: `exclude_vmids`,
`ignore_containers`, `ignore_devices`, `ignore_mounts`, und bei den Diensten jede Unit, die ein Glob trifft (das Muster
selbst ist kein Objekt). `_details` und Status, Nachricht und Metriken der Checks bleiben unverändert; die bestehenden
Tests der Checker bleiben grün. `not_collected` dämpft nicht (`damp_object`), ein Wechsel nach `not_collected` landet
im Statuswechsel-Log wie jeder andere.

### Akteur

`proxy_to_monitoring` setzt neben `X-Internal-Key` zwei Header aus dem gebundenen Akteur (`actor_from_request`):
`X-AH-Actor-Id` = `<actor_type>:<actor_id>` und `X-AH-Actor-Name` = der Anzeigename, prozentkodiert
(`urllib.parse.quote(name, safe="")`), weil httpx Header-Werte außerhalb ASCII mit einem Fehler ablehnt, den der Proxy
nicht abfängt. Der Proxy baut die Header neu und reicht keinen Client-Header durch; ein Test schickt gefälschte
Akteur-Header durch den Proxy und prüft, dass upstream der eigene Wert ankommt. Das Monitoring dekodiert
(`unquote(errors="replace")`), entfernt Steuerzeichen, kürzt den Namen auf 64 Zeichen und antwortet 400 auf einen
Header über 1024 Zeichen; ohne Header (interne Aufrufer, Tests) bleibt der Akteur leer. Die Header sind Zuschreibung,
keine Berechtigung: `require_internal` entscheidet wie bisher. Die Audit-Zeile des Servers bleibt ohne Inhalt; sie
und die Ausnahme-Zeile passen über Akteur-ID und Zeit zusammen.

### Aufbewahrung

Der Tagesjob löscht Ausnahmen, die seit über 90 Tagen beendet sind (`EXCEPTION_ENDED_RETENTION_DAYS = 90`, neben
`STATUS_LOG_RETENTION_DAYS`, `apps/monitoring/app/scheduler.py:213`). Wird ein Server gelöscht, verschwinden seine
Ausnahmen mit ihm (hart, wie seine übrigen Monitoring-Daten); globale bleiben. Wird ein Check gelöscht, nimmt der
Fremdschlüssel seine Ausnahmen mit.

## Externe Integrationen

Keine neue. httpx (Header-Werte nur ASCII, deshalb Prozentkodierung) ist am Proxy schon im Einsatz; dass httpx 0.28.1
einen Nicht-ASCII-Namen mit `UnicodeEncodeError` ablehnt, ist per Probe belegt. RFC 9110 §5.5 lässt Bytes außerhalb
ASCII in Feldwerten nur als „obs-text“ zu (nicht weiter verifiziert); ASCII per Prozentkodierung umgeht die Frage.

## Trade-offs & Alternativen

- **Schnitt nur `no_notify` (gewählt) vs. alle Wirkungen in P1b.** Alle Wirkungen hießen: Check-Engine, Scheduler und
  Push-Pfad umbauen und `enabled` gleichzeitig migrieren, sonst zwei Abschalter. Das ist P1c, mit der Abnahme an
  Kevins Daten. Empfehlung und Entscheidung der Session: `skip`/`no_rating` nach P1c.
- **Typisierte Geltungs-Spalten (gewählt) vs. ein freier `scope_value`.** Freier Wert spart Spalten, verliert aber den
  Fremdschlüssel (verwaiste Check-Ausnahmen) und braucht je Abfrage eine Fallunterscheidung über Strings.
- **Akteur per Header (gewählt) vs. im Body.** Body-Felder kämen vom Client und wären fälschbar; der Proxy kennt den
  Admin. Signierte Header wären stärker, aber der Kanal ist schon über `X-Internal-Key` gesichert, und die Header
  berechtigen zu nichts.
- **Alttabelle stehen lassen (gewählt) vs. droppen.** Stehen lassen kostet nichts und hält den Rückweg; gedroppt wird
  nach P1c.
- **`MonitorMaintenance` mit `synonym` (gewählt) vs. Auswerter verdoppeln.** Der Auswerter bleibt einer; der
  Äquivalenztest vergleicht so dieselbe Zeitlogik über zwei Zeilenarten und zwei Geltungswege.

## Risiken & Rollback

- **Migration (Risikopfad):** additiv; Übernahme 1:1, idempotent; Downgrade schreibt den Fassadenstand zurück.
  `test_migration_chain_matches_models` hält Modell und Revision gleich; Äquivalenz- und Rückwegtest auf Postgres.
- **Zwei Alembic-Köpfe:** P1d (R-1638) bekommt vermutlich auch eine Revision auf `e3a5c7e9f1b2`. Wer als Zweiter
  merged, hängt seine Revision um (`down_revision`), vor jedem Push `origin/main` hereinmergen.
- **Stummschalten ändert die Quelle:** jeder Leser der Wartung wechselt in einer Task; die Tests, die Fenster anlegen,
  wechseln mit und behalten ihre Erwartungen. `muted_reason` und `muted_reasons` bleiben per Test im Gleichlauf.
- **Proxy (Risikopfad):** neues Präfix und zwei Header; die Freigabeliste bleibt per Test gleich den Routen und der
  Doku; der Akteur ist nie Berechtigung. `security` je Task auf den Risikopfaden.
- **Objekt-API zeigt mehr Zeilen:** gewollt; `MAX_OBJECTS`/`MAX_ROWS` kappen wie bisher.
- **Rollback:** Revert des Merges plus `alembic downgrade e3a5c7e9f1b2`; Wartungsfenster stehen danach wieder in
  `monitor_maintenance`, wie die Fassade sie zuletzt zeigte.

## Doku-Impact

`docs/developer/monitoring.html` + EN (Ausnahme-Modell, Fassade, Leser, Akteur-Header, ausgenommene Objekte,
Aufbewahrung; Präfix `exceptions`), `docs/developer/api-reference.html` + EN (`/exceptions`, `exception` an
`GET /objects`, `mutedReason` `exception`, Löschen beendet), `docs/admin/monitoring.html` + EN (Wartungsfenster:
Löschen beendet, 90 Tage nachvollziehbar; per Einstellung ausgenommene Objekte); `changelog.d/arch-monitoring-neu-p1b.md`.

## Offene Fragen

Keine für Kevin; seine vier Entscheidungen vom 2026-11-25 stehen oben. Die Session entscheidet im Bau: Spaltennamen,
Revisions-ID, Form des Helfers für die Test-Fenster. Für spätere Schritte bleiben: Datenkopie und Migration der
Ignorierlisten (P1c), Geltung Regel (P1d), Tag/Cluster/„nur für mich“ und Oberfläche (P2).
