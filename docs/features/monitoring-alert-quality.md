<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Alert-Qualität — Haltezeit, Glocken-Cooldown, Severity-Deckel, Host-Ping, Sammelmeldung

Roadmap R-0424 (FEAT) · Entscheidungen Kevin 2026-10-19 (Haltezeit, Glocke, Severity, Host-down, Sammelmeldung).
Zeilenangaben gelten für `main@5481b316`; die Bau-Session greppt sie beim Start neu.

## Problem / Motivation

- **Recovery beim ersten ok.** `next_fail_count` setzt bei `ok` sofort auf 0 (`apps/monitoring/app/check_engine.py:73-86`),
  `effective_status` dämpft nur Fehlschläge, nie ein `ok` (`:95-115`). Ein Check, der zwischen `critical` und `ok`
  pendelt, meldet jedes Mal Alarm und Entwarnung; `consecutive_fails` wirkt nur in eine Richtung.
- **Die Glocke hat keinen Cooldown.** Alert-Regeln haben `cooldown_minutes` je Regel und Check
  (`alerter.py:290-303`), der Hub-Emit läuft dagegen bei jeder gemeldeten Abweichung (`alerter.py:204-206`,
  `docs/admin/monitoring.html:289`: „Die Glocke … kennt keinen Cooldown“).
- **`severity` begrenzt nichts.** Der Hub-Schweregrad ist der schlimmere der beiden Zustände (`_hub_severity`,
  `alerter.py:230-233`); `check.severity` wirkt nur im Regel-Filter (`:283`) und als Textzeile (`:351`). Der Check
  „Disk Forecast“ (Template-Severity `warning`, `builtin_templates.py:82-91`) meldet `critical`, sobald der
  Checker `critical` liefert, und löst damit den Hook `alert.triggered` aus
  (`apps/server/app/modules/notifications/router.py:190-208`).
- **Host-down nur mit Agent.** Die Unterdrückung kennt nur `agent_ping` (`_host_is_down`, `alerter.py:209-227`); ein
  Host ohne Agent hat kein Host-down-Signal, und kein mitgeliefertes Template nutzt den `ping`-Check.
- **Ein Ausfall vieler Agents = viele Meldungen.** Jeder `agent_ping` ist ein eigener APScheduler-Job
  (`scheduler.py:82-88`) und meldet einzeln; fällt die Verbindung zu zehn Servern weg, gehen zehn Mails, zehn
  Webhooks und zehn Glocken-Einträge raus.

## Ziel & Nicht-Ziele

**Ziel** (Kevin 2026-10-19):

1. **Haltezeit:** Ein Check kehrt erst nach `consecutive_oks` (neu, Default 2) `ok`-Ergebnissen in Folge von
   `warning`/`critical` nach `ok` zurück. Neues Feld je Check und je Template-Definition, gleich für Scheduler- und
   Push-Pfad, auch für den Heartbeat (`agent_ping`). Bestehende Checks bekommen per Migration 2.
2. **Glocken-Cooldown:** Der Monitoring-Dienst schickt je Check höchstens eine Problem-Meldung in 30 Minuten an die
   Glocke. Recovery und Eskalation `warning → critical` gehen immer durch. Was der Cooldown schluckt, wird nicht
   nachgeholt.
3. **Severity deckelt überall:** Glocke, Mail-/Webhook-Betreff und `alert.triggered` tragen
   `min(Status, severity)`. `info` geht wie heute nicht an die Glocke.
4. **Host-down ohne Agent:** neues mitgeliefertes Template **„Host Ping“** (`ping {{hostname}}`, 3 Fehlschläge),
   nicht Teil von „Linux Server — Standard“/„Windows Server — Standard“. Ein `critical` Host-Ping unterdrückt die
   übrigen Alarme seines Servers wie heute der Heartbeat.
5. **Sammelmeldung:** Werden binnen 5 Minuten mindestens 3 Agents stumm, bekommt jeder Kanal eine Sammelmeldung statt
   Einzelmeldungen; ihre Rückkehr ebenso. Darunter bleibt es bei Einzelmeldungen.
6. **Desktop:** das Feld im Check-Editor und im Template-Editor (inkl. Update-Vergleich der Standard-Templates).

**Nicht-Ziele (YAGNI):**
- Kein konfigurierbarer Glocken-Cooldown, keine konfigurierbare Sammel-Schwelle oder -Fenster (Konstanten).
- Keine Haltezeit in Minuten, kein `ok_since`.
- Keine Änderung am Regel-Cooldown (`cooldown_minutes`), an `_send_webhook`/`_send_email` (`alerter.py:378-469`)
  und an den Checkern.
- Keine Sammelmeldung für andere Check-Typen als `agent_ping` (Host-Ping: Offene Frage 4).
- Kein Web-Frontend (Monitoring-Checks bearbeitet nur der Desktop), keine Agent-Änderung.
- Der Servername fehlt heute im Betreff einer Einzelmeldung (`_build_message`, `alerter.py:336-352`); das bleibt so.
  Nur die Sammelmeldung nennt Server.

## Betroffene Komponenten & Dateien

| Komponente | Datei | Änderung |
|---|---|---|
| monitoring | `alembic/versions/<rev>_alert_quality.py` (neu) | vier Spalten, Backfill (unten) |
| monitoring | `app/models.py` | `MonitorCheck.consecutive_oks` (neben `:37`), `to_dict` `consecutiveOks` (`:58`); `MonitorState.ok_count`, `hub_status`, `hub_sent_at` (neben `:79`, `:85`) |
| monitoring | `app/check_engine.py` | `next_ok_count`, `holds_recovery` neben `next_fail_count`/`effective_status` (`:73-115`); `apply_result` (`:136-226`) hält die Recovery; `execute_check` reicht `agent_ping` nicht mehr selbst an den Alert-Pool (`:314-315`) |
| monitoring | `app/schemas.py` | `consecutive_oks` in `CheckCreate` (`:19-36`), `CheckUpdate` (`:39-48`), `TemplateCheckDef` (`:71-112`) |
| monitoring | `app/routers/checks.py` | Anlegen (`:156-167`), Feldliste des Updates (`:240-249`) |
| monitoring | `app/template_sync.py` | `TEMPLATE_CHECK_FIELDS` (`:101-110`), `_template_check_values` (`:113-126`), Sync-Werte (`:449-458`); Reset (`routers/checks.py:305-332`) folgt daraus |
| monitoring | `app/alerter.py` | `_hub_severity` (`:230-233`) mit Deckel, Betreff (`:345-346`), Glocken-Entscheidung vor `_emit_to_hub` (`:204-206`, `:236-278`), POST als eigene Funktion, `_host_is_down` (`:209-227`) mit Host-Ping und Rangfolge, Stummschalt-Prüfung als Funktion (`:129-145`) |
| monitoring | `app/builtin_templates.py` | sechster Eintrag `host-ping` in `BUILTIN_TEMPLATES` (`:104-194`) |
| monitoring | `app/alert_bundle.py` (neu) | Sammelmeldung: Kandidaten, 5-Minuten-Fenster, Claim, Versand je Kanal |
| monitoring | `app/scheduler.py`, `app/main.py` | System-Job `system:agent-alert-bundle` (Muster `schedule_tag_sync`, `scheduler.py:178-208`; Start `main.py:77-79`) |
| server | `app/modules/notifications/schemas.py` | `IncomingEvent.source_ids` (`:20-34`) |
| server | `app/modules/notifications/service.py` | Empfänger je Nutzer für `source_ids` (`resolve_recipients :120-157`, `ingest_event :160-210`) |
| server | `app/modules/notifications/router.py` | `alert.triggered` je Server einer Sammelmeldung (`:190-208`) |
| desktop-ui | `src/lib/api/types.ts` (`:386-414`, `:550-558`), `src/lib/models/monitorCheck.ts` (`:40-91`), `src/lib/models/monitorTemplate.ts` (`:28-37`) | Feld in Typen und Formularen |
| desktop-ui | `src/components/monitoring/MonitorCheckModal.svelte` (`:153-161`), `MonitoringTemplateModal.svelte` (`:243-251`), `BuiltinUpdateModal.svelte` (`:43-50`, `:60-73`), `section/MonCheckLine.svelte` (`:31-40`), `src/lib/i18n/dictionaries.ts` (`:546`, `:1238`) | Eingabefeld, Feldnamen, Texte |

## Datenmodell / API / Migrationen

### Alembic (Monitoring-Dienst)

Head auf `main@5481b316`: `b9d1f3a5c7e9` (`alembic/versions/b9d1f3a5c7e9_host_facts_suggestions.py`). Neue Revision
`<rev>_alert_quality.py`, `down_revision` = Head beim Baustart (frisch prüfen: ein Parallel-Vorhaben mit eigener
Revision auf demselben Head ergäbe zwei Heads).

| Tabelle | Spalte | Typ | Default / Backfill |
|---|---|---|---|
| `monitor_checks` | `consecutive_oks` | Integer NOT NULL | `server_default '2'` — jeder bestehende Check bekommt 2 |
| `monitor_states` | `ok_count` | Integer NOT NULL | `server_default '0'` |
| `monitor_states` | `hub_status` | String NULL | Backfill `= notified_status` für `warning`/`critical`, sonst NULL — sonst würde die Glocke die Entwarnung eines vor dem Update gemeldeten Problems verschlucken |
| `monitor_states` | `hub_sent_at` | DateTime NULL | NULL (kein Cooldown aktiv) |

Downgrade entfernt die vier Spalten. Das Modell spiegelt die Defaults (`default=` und `server_default=`), damit
`test_migration_chain_matches_models` passt.

### Haltezeit (Zustandsmaschine, eine Stelle für beide Pfade)

`apply_result` ist die einzige Pipeline (Wächter `tests/test_architecture_transitions.py:76-97`); die Haltezeit
kommt nur dorthin.

- `next_ok_count(result, prev)`: `ok` → `prev + 1`, sonst 0 (Gegenstück zu `next_fail_count`).
- `holds_recovery(result, new_ok_count, consecutive_oks, old_status, notified_status)`: wahr, wenn `result == "ok"`,
  `new_ok_count < consecutive_oks` und der Check ein **gemeldetes** Problem trägt (Kevin 2026-10-20):
  `notified_status ∈ {warning, critical}` und `old_status ∈ {warning, critical, unknown}` (ein gemeldetes Problem, das
  über `unknown` zurückkommt, soll nicht am Hold vorbei entwarnen). Ein nie gemeldetes Problem (`notified_status`
  `ok`/NULL, etwa während Wartung oder Host-down stumm) hält nicht: Der erste `ok` entwarnt sofort und still wie vor
  der Haltezeit; gehalten würde es nach dem Ende der Stummschaltung als neuer Alarm nachgemeldet. `pending → ok` und
  `ok → ok` halten nie.
- Hält die Recovery, gilt `eff_status = notified_status` (Kevin 2026-10-20): der zuletzt gemeldete Status, nicht ein
  schlimmerer, der nie gemeldet wurde — gemeldet `warning`, stumm `critical`, dann `ok` hält `warning` statt eine
  Eskalation `warning → critical` nachzumelden. Damit meldet der Hold nie etwas (`resolve_notification` → `skip`).
  Die Meldung bekommt den Zusatz `(recovery n/m)` (wie `(failure n/m)`, `:179-180`); `state.ok_count` wird
  gespeichert. Ein Fehlschlag während des Holds setzt `ok_count` auf 0; `fail_count` war beim ersten `ok` schon 0, ein
  erneuter Fehlschlag bleibt über die bestehende Dämpfung auf dem gehaltenen Status — der Check bleibt also beim
  Problem. Ein Check, der flattert oder abwechselnd `ok` und `unknown` liefert, entwarnt erst nach
  `consecutive_oks` `ok` in Folge.
- `consecutive_oks = 1` ist das heutige Verhalten.
- Folgen: Die Host-down-Unterdrückung (`_host_is_down`, Status `critical`) bleibt während des Holds eines gemeldeten
  Heartbeat-Ausfalls bestehen; das Dashboard zeigt den gemeldeten Status mit der `ok`-Meldung plus Zusatz.

### API (Monitoring, OpenAPI-Snapshot `apps/monitoring/tests/openapi.snapshot.json`)

- `consecutive_oks: Annotated[IntColumn, Field(ge=1, le=100)] = 2` in `CheckCreate` und `TemplateCheckDef`,
  `… | None = None` in `CheckUpdate` (Muster `cooldown_minutes`, `schemas.py:57`; die Grenzen je Feld im Schema
  prüfen: ein `IntColumn = Field(…)` verliert die Grenze still). Antwort `consecutiveOks` in `MonitorCheck.to_dict`.
- Template-Definitionen: Der Default 2 ist Schema-Default, `_without_defaults` (`builtin_templates.py:197-207`)
  lässt ihn aus dem Hash: **die Hashes der fünf mitgelieferten Templates bleiben gleich** (bis T17; T17 ändert Disk Forecast und hebt `linux-base`/`windows-base` auf Version 2) — der bestehende Test
  `test_shipped_definitions_change_only_with_a_new_version` (`tests/test_seed.py:209-225`) ist der Beweis und bleibt
  unverändert. Eine Definition ohne Schlüssel gilt als 2 (`_template_check_values`).
- `consecutive_oks` wird Template-Feld (`TEMPLATE_CHECK_FIELDS`, ans Ende): eine Änderung am Check gilt als
  „angepasst“, der Sync überschreibt sie nicht, „Auf Template zurücksetzen“ setzt sie zurück. Die einmalige
  Override-Baseline (`record_override_baseline`) läuft in bestehenden Installationen nicht erneut; das ist richtig,
  weil vor dem Update niemand das Feld ändern konnte.
- `ok_count`, `hub_status`, `hub_sent_at` erscheinen in keiner Antwort.

### Severity-Deckel

- Stufen: `info` 0, `warning` 1, `critical` 2 (vorhandene Tabelle `_STATUS_LEVEL`, `alerter.py:54`).
- Hub: `_hub_severity(old, new, severity) = min(max(Stufe old, Stufe new), Stufe severity)`; Stufe 0 → kein Emit
  (`:249-250`), also nie für `severity: info`.
- Betreff (Mail und Webhook, `msg["subject"]`, auch Titel in der Glocke): Etikett `INFO`/`WARNING`/`CRITICAL` aus
  `min(Stufe new, Stufe severity)`; `RECOVERY` bleibt. Der Text behält den echten Übergang (`Status: ok → critical`)
  und die Zeile `Severity: <severity>` — wer die Mail liest, sieht beides.
- **Server: keine Änderung nötig.** Der Hook feuert nur bei `event.severity == "critical"` und
  `new_status == "critical"` (`router.py:190-197`); mit gedeckelter Severity feuert er für einen Check mit
  `severity: warning` nicht mehr — genau `min(Status, Severity)`. Ebenso filtert das Abo (`min_severity`) auf die
  gedeckelte Stufe.

### Glocken-Cooldown

Reine Funktion `hub_decision(hub_status, hub_sent_at, new_status, severity, now) -> "emit" | "skip"` in `alerter.py`,
Konstante `HUB_COOLDOWN = 30 min`:

- gedeckelte Stufe 0 → `skip` (wie heute);
- Recovery (`new_status == "ok"`): `emit` genau dann, wenn `hub_status ∈ {warning, critical}` — die Glocke entwarnt
  nur, was sie gezeigt hat;
- Eskalation (gedeckelt `hub_status == warning` → `critical`): `emit`;
- sonst: `skip`, wenn `hub_sent_at` jünger als 30 Minuten ist, sonst `emit`.

Nach einem erfolgreichen POST (HTTP < 300): `hub_status = new_status`; bei einer Problem-Meldung zusätzlich
`hub_sent_at = now`. Ein gescheiterter POST ändert nichts. Geschluckt heißt verworfen: `notified_status` ist mit dem
Claim schon gesetzt (`alerter.py:162-164`), es gibt keine Nachmeldung. Der POST wird als
`_post_hub_event(payload, label) -> bool` aus `_emit_to_hub` gelöst, damit Einzel- und Sammelmeldung ihn teilen.

### Host-Ping und Host-down

- Template (sechster Eintrag in `BUILTIN_TEMPLATES`, seedet wie jedes Standard-Template einmal, in bestehenden
  Installationen beim nächsten Start; wird nicht vorgeschlagen, `template_suggestions.py:36-42`):

  ```
  slug "host-ping", version 1, name "Host Ping",
  description "Alerts when the host stops answering ping, also without an agent."
  check: def_id "host-ping", name "Host Ping", check_type "ping",
         config {"target": "{{hostname}}", "timeout": 3}, interval "1m",
         severity "critical", consecutive_fails 3
  ```
  Intervall 1 Minute, damit 3 Fehlschläge ≈ 3 Minuten sind; `timeout` 3 s hält den Worker-Pool (30 Threads,
  `scheduler.py:36-44`) auch dann frei, wenn viele Hosts gleichzeitig ausfallen.
- Unterdrückung (Rangfolge, damit sich zwei `critical` Signale nicht gegenseitig stummschalten):

  | Check | wird unterdrückt, wenn auf demselben Server `critical` steht … |
  |---|---|
  | Host-Ping | nie |
  | `agent_ping` | ein Host-Ping |
  | alle anderen | ein `agent_ping` oder ein Host-Ping |

  „Host-Ping“ = ein eingeschalteter `ping`-Check mit `template_def_id == "host-ping"` (Empfehlung, Offene Frage 2).
  Heute unterdrückt ein `critical` Heartbeat auch einen `ping`-Check; das entfällt für Host-Ping.
- Maintenance- und Host-down-Prüfung (`alerter.py:129-145`) werden eine Funktion `muted_reason(db, check, now)`,
  die `process_alert` und die Sammelmeldung teilen.

### Sammelmeldung (stumme Agents)

**Der Puffer ist der Sent-State.** Eine noch nicht gemeldete Abweichung steht schon heute dauerhaft in
`monitor_states` (`notified_status ≠ status`, mit `since` = Zeitpunkt des Statuswechsels); ein Neustart verliert
nichts, eine eigene Tabelle oder ein Speicher-Puffer ist unnötig.

- `execute_check` reicht eine `notify`-Entscheidung für `agent_ping` nicht mehr an den Alert-Pool
  (`check_engine.py:314-315`); die Abweichung bleibt offen. (`agent_ping` läuft nur über `execute_check`, auch
  „Jetzt ausführen“, `routers/checks.py:335-356`; der Push-Pfad wertet ihn nie aus.)
- System-Job `system:agent-alert-bundle` alle 30 s (`flush_agent_alerts`, eigene Session über
  `database.SessionLocal`):
  1. Kandidaten: eingeschaltete `agent_ping`-Checks mit `resolve_notification(notified_status, status) == "notify"`.
     Stummgeschaltete (`muted_reason`: Wartung, Host-Ping) bleiben offen wie heute.
  2. Getrennt nach Art: **stumm** (`status == critical`) und **zurück** (`status == ok`).
  3. Je Art: **≥ 3 Kandidaten → Sammelmeldung** über alle; sonst wird jeder Kandidat, dessen `since` mindestens
     min(5 Minuten, Prüfintervall des Checks − 1 Minute) zurückliegt (nie negativ), einzeln über den bestehenden
     Weg gemeldet (`_dispatch_alert_bg` → `process_alert`). Das Fenster ist kürzer als der Prüftakt (Kevin
     2026-10-20 nach dem security-Review von T13): sonst wäre ein Agent, der eine Prüfung lang stumm war, beim
     nächsten Lauf wieder ok, bevor er gemeldet ist, und ein Ausfall von bis zu ~20 Minuten bliebe ungemeldet.
     Jüngere warten auf den nächsten Lauf. Damit gilt: drei Agents binnen 5 Minuten → eine Meldung, sobald der
     dritte da ist; einer oder zwei → je eine Meldung nach 5 Minuten. Nachmeldungen nach einem Wartungsfenster sind
     „alt“ und gehen sofort (ab drei gesammelt).
  4. Sammelmeldung: Claim wie `process_alert` (je State `FOR UPDATE` in `check_id`-Reihenfolge, Entscheidung neu
     prüfen, `notified_status = status`, Commit vor jeder Kanal-I/O; was sich inzwischen geändert hat, fällt heraus).
- Versand **je Kanal** (`send_bundle` in `alert_bundle.py`):
  - **Regel** (Webhook/Mail): Mitglieder = die Kandidaten, auf die `_rule_matches` passt, ohne die im
    Regel-Cooldown (nur bei „stumm“; die Rückkehr umgeht den Cooldown wie heute). ≥ 3 → eine Nachricht über
    `_dispatch` (bekommt den ersten Mitglieds-Check als Log-Bezug, damit `_send_webhook`/`_send_email` unverändert
    bleiben) und **je Mitglied eine Zeile im Alert-Log** (der Regel-Cooldown je Check bleibt stimmig); 1–2 → je
    Mitglied die normale Einzelnachricht. Eine Regel mit `match_server_id` trifft höchstens die Agents eines Servers
    und meldet deshalb einzeln.
  - **Glocke:** Mitglieder = die Kandidaten, für die `hub_decision` `emit` sagt, getrennt nach ihrer gedeckelten
    Severity (bei der Rückkehr nach `hub_status`; Kevin 2026-10-20). Je Stufe: ≥ 3 → **ein** Event mit `source_ids`
    (Server-Vertrag unten) und dieser Severity; 1–2 → je Mitglied `_emit_to_hub`. So feuert `alert.triggered` nur
    für Server, deren Check selbst critical ist, und `min_severity` greift je Server; bei gemischten Stufen kommen
    bis zu zwei Glocken-Einträge. `hub_status`/`hub_sent_at` je Mitglied.
- Nachricht (englisch wie alle Alarmtexte):
  - Betreff `[AdminHelper Monitor] CRITICAL: <n> agents not reporting` bzw.
    `[AdminHelper Monitor] RECOVERY: <n> agents reporting again`; Etikett = gedeckelte Stufe, das höchste der
    Mitglieder.
  - Text: je Mitglied `- <Server>: <state.message>`, höchstens 50 Zeilen, dann `… and <k> more`. Server =
    `server_name` einer Template-Zuweisung des Servers, sonst die `server_id`.
  - Webhook-Payload wie bisher (`{"alert_rule", **msg}`), dazu `members`: Liste aus `check_id`, `check_name`,
    `server_id`, `server_name`, `old_status`, `new_status`, `message`; `server_id` der Nachricht ist `null`.
- Konstanten in `alert_bundle.py`: `BUNDLE_MIN = 3`, `BUNDLE_WINDOW = 5 min`, Job-Takt 30 s.

### Vertrag Monitoring → Server (`POST /api/internal/events`)

Die Glocke routet der Server je Nutzer nach Server-Zuordnung und Abo (`service.py:62-84`). Ein Event ohne
`source_id` geht nur an Admins (`_user_can_see`, `:62-69`); ein Sammel-Event ohne Server-Bezug würde also Nutzer
verlieren, denen nur einzelne der Server zugeordnet sind. Deshalb **ändert sich der Server**:

- `IncomingEvent.source_ids: list[str] | None` (höchstens 500 Einträge, je höchstens 256 Zeichen, mindestens einer;
  nicht zusammen mit `source_id` → 422). Additiv: alte Sender ändern nichts.
- `resolve_recipients`/`ingest_event`: mit `source_ids` lädt der Server die Server-Zeilen in einer Abfrage und
  sammelt je Nutzer die Server, die er sehen darf und auf die eines seiner Abos passt (Sichtbarkeit, Scope,
  `min_severity`, Kategorie wie bisher; unbekannte IDs nur für Admins). Ein Nutzer mit mindestens einem Treffer
  bekommt **eine** Zeile: Titel `<title> (<n>)`, Text = `body` plus eine Zeile je sichtbarem Server (Name, sonst
  ID); `source_id` NULL; Outbox wie bisher. Kein Nutzer sieht Namen oder Anzahl fremder Server.
- `alert.triggered`: bei `severity == critical` und `new_status == critical` einmal **je ID** aus `source_ids`
  (`server_id` = ID, sonst gleiche Payload). Hook-Verbraucher sehen weiter einen Server je Aufruf.
- OpenAPI-Snapshot des Servers (`apps/server/tests/openapi.snapshot.json`) ändert sich mit. Web und Desktop lesen
  `IncomingEvent` nicht; Feed-Zeilen behalten ihre Form.
- Verträglichkeit: Monitoring und Server kommen im selben Release. Ein älterer Server ignoriert `source_ids`
  (pydantic `extra` ignoriert) und gäbe das Sammel-Event nur Admins.

### Desktop

- `MonitorCheck.consecutiveOks?`, `MonitorCheckInput.consecutive_oks`, `TemplateCheckDef.consecutive_oks?`;
  `CheckForm.consecutiveOks` (Default 2, `?? 2`, `|| 2` wie `consecutiveFails`).
- Check-Editor und Template-Editor: Zahlenfeld neben „Fehlversuche bis Alarm“, `min="1"`, `max="100"`. Text:
  DE „OKs bis Entwarnung“, EN „Consecutive OKs before recovery“ (`monitoring.checkEdit.consecutiveOks`).
- `MonCheckLine` (Badge „angepasst“) und `BuiltinUpdateModal` (Feldname, `CHECK_DEFAULTS.consecutive_oks = 2`)
  kennen das Feld.

## Externe Integrationen

Keine neuen. `ping` (iputils) liegt im Monitoring-Container (`apps/monitoring/Dockerfile:9`) und wird schon vom
`ping`-Check genutzt; die Moncheck-Etappe des Multibox-Laufs belegt ICMP aus dem Container. SMTP, Webhook und
VictoriaMetrics bleiben unverändert.

## Trade-offs & Alternativen

1. **Haltezeit im Status oder nur in der Meldung.** Nur die Recovery-Meldung zu verzögern, ließe Dashboard und
   Glocke auseinanderlaufen und die Host-down-Unterdrückung beim ersten `ok` fallen. **Empfehlung: im Status**
   (`apply_result`) — eine Wahrheit, Kosten: der Check steht ein Intervall länger rot, mit `(recovery 1/2)`.
2. **Wo der Glocken-Cooldown lebt.** In-Memory-Map (verliert sich beim Neustart), Alert-Log (`alert_rule_id` ist
   NOT NULL, `models.py:151-153`) oder Spalten am State. **Empfehlung: Spalten** `hub_status`/`hub_sent_at`;
   `hub_status` verhindert Entwarnungen in der Glocke für Probleme, die sie wegen des Cooldowns nie gezeigt hat.
3. **Puffer der Sammelmeldung.** Speicher-Puffer (verliert Alarme beim Neustart), eigene Tabelle (zweite Wahrheit
   neben dem Sent-State) oder der Sent-State selbst. **Empfehlung: Sent-State** plus System-Job — nichts Neues zu
   speichern, neustartfest, Wartung und Host-down wirken unverändert.
4. **Einzelmeldung unter der Schwelle.** (a) bis zu 5 Minuten warten, ob es mehr werden, oder (b) sofort senden und
   erst ab dem dritten bündeln (dann bis zu zwei Einzelmeldungen plus eine Sammelmeldung). **Empfehlung (a)**, weil
   Kevins Entscheidung „statt Einzelmeldungen“ sagt und der Heartbeat ohnehin erst nach 15 Minuten Stille anschlägt;
   Kosten: ein einzelner stummer Agent meldet bis zu 5½ Minuten später, ein kurzer Aussetzer, der vorher endet, gar
   nicht. → Offene Frage 1.
5. **Sammelmeldung in der Glocke.** Ein Admin-Event (verliert zugeordnete Nicht-Admins), die Glocke nicht bündeln
   (verfehlt das Ziel) oder Empfänger je Nutzer im Server. **Empfehlung: Server-Vertrag `source_ids`** — die
   Zuordnung Nutzer ↔ Server kennt nur der Server.
6. **Welcher Ping hemmt.** Jeder `ping`-Check des Servers (Kevins Wortlaut, aber ein von Hand angelegter Ping auf ein
   anderes Ziel, etwa ein Gateway, schaltet dann alle Alarme des Servers stumm) oder nur Checks aus „Host Ping“.
   **Empfehlung: nur Host-Ping** — eine Fehlkonfiguration bleibt laut statt still. → Offene Frage 2.
7. **Deckel im Text.** Auch die Statuszeile im Text zu deckeln, verschwiege den echten Checker-Status.
   **Empfehlung: nur Betreff, Glocke, Hook.**

## Risiken & Rollback

- **Verhaltensänderung für alle bestehenden Checks:** Die Migration setzt `consecutive_oks = 2`; jede Entwarnung kommt
  ein Intervall später, bei einem `1h`-Check (Disk Forecast) eine Stunde, bei `24h` einen Tag. Wer das nicht will,
  setzt 1 am Check. → Offene Frage 6, CHANGELOG „Changed“.
- **Host-Ping auf Hosts ohne ICMP** (nur über FRP erreichbar, ICMP gefiltert): Der Host-Ping steht `critical` und
  **unterdrückt alle übrigen Alarme dieses Servers**. Gemildert: Template ist opt-in, der Host-Ping selbst meldet,
  Doku warnt. Ein IPv6-Literal als Hostname lehnt der `ping`-Check ab (`[a-zA-Z0-9._-]`, `checkers/ping.py:10`):
  Der Host-Ping steht dann `unknown`, meldet keinen Ausfall und unterdrückt nichts (korrigiert nach T7).
- **Sammelmeldung verzögert Einzelalarme** der Heartbeats um bis zu 5½ Minuten (Trade-off 4).
- **Server und Monitoring müssen zusammen ausgerollt werden** (Vertrag `source_ids`); Sammelmeldungen gingen sonst
  nur an Admins.
- **Zwei Alembic-Heads**, falls ein Parallel-Vorhaben ebenfalls eine Monitoring-Revision auf `b9d1f3a5c7e9` setzt:
  wer zuletzt merged, hängt seine Revision um.
- **Überschneidung mit Parallel-Vorhaben** (Dateien und Hunks):
  - `monitoring-hardening` berührt in `alerter.py` die Versandfunktionen (`_send_webhook`/`_send_email`,
    `:378-469`) und den Ausnahmezweig der Regel-Schleife (`:181-187`); dieses Vorhaben lässt beide unverändert und
    ändert `process_alert` nur vor dem Hub-Emit (`:204-206`) und an der Stummschalt-Prüfung (`:129-145`), dazu
    `_host_is_down`, `_hub_severity`, `_emit_to_hub`, `_build_message`. Möglich in `check_engine.py` (Meldungslänge,
    `:36-41`, `:176-178`) und `schemas.py`; hier: `check_engine.py:73-115`, `:136-226`, `:314-315`;
    `schemas.py:19-48`, `:71-80`. `check_configs.py` ändert dieses Vorhaben nicht.
  - `monitoring-linux-base-v2` ändert `builtin_templates.py` (linux-base/windows-base/proxmox-host, eingefrorene
    v1-Hashes in `reconcile_builtin_templates`, `:358-363`), `tests/test_seed.py` (gepinnte Hashes `:215-221`,
    Zahl der Templates `:51`, `:74`, `:76`), möglicherweise `template_sync.py` und die Desktop-Dateien `types.ts`,
    `dictionaries.ts`, `CheckConfigFields.svelte`. Hier: neuer Eintrag am Ende von `BUILTIN_TEMPLATES`, ein
    weiterer gepinnter Hash und Zahl 6 in `test_seed.py`, `TEMPLATE_CHECK_FIELDS`/`_template_check_values`/Sync-Werte
    in `template_sync.py`, in `types.ts` die Monitoring-Typen `:386-414`/`:550-558`, in `dictionaries.ts` je eine
    Zeile neben `:546`/`:1238`.
  - Alle drei: `docs/admin/monitoring.html` (+EN), `docs/developer/monitoring.html` (+EN), `CHANGELOG.md`.
- **Rollback:** Code zurück und `alembic downgrade` um eine Revision (entfernt die vier Spalten; `consecutive_oks`
  ist dann wieder implizit 1). Der Server-Vertrag ist additiv.

Hingenommenes Restrisiko (Kevin 2026-10-20): Laufen zwei Meldungen desselben Checks binnen Sekunden und scheitert nur der Hub-Versand der ersten, kann die Glocke die zweite Alarmmeldung auslassen (sie fiel in den Cooldown der reservierten ersten); E-Mail und Webhook der Regeln melden weiter.

## Doku-Impact

Sichtbares Verhalten, DE + EN im selben Commit wie der Code: `docs/admin/monitoring.html` (Check anlegen `:119`,
Dämpfung `:124`, Alert-Verhalten und Host-down `:139-145`, angepasste Template-Felder `:217`, Standard-Templates
`:231-243`, Cooldown/Recovery/Hook `:289-291`, Notification-Hub `:318`, neuer Abschnitt Sammelmeldung),
`docs/developer/monitoring.html` (`:90`, `:184`, Alert-Pipeline `:216-225`), Server: `docs/developer/server.html`
(`:187-188`), `docs/developer/api-reference.html` (`:208-209`), `docs/developer/hooks.html` (`:58`); `CHANGELOG.md`
(Added: Host-Ping, Sammelmeldung, Feld; Changed: Haltezeit-Default, Severity-Deckel, Glocken-Cooldown).

## Offene Fragen

1. **Einzelmeldung unter 3 Agents:** bis 5 Minuten zurückhalten (Empfehlung, Trade-off 4) oder sofort senden und erst
   ab dem dritten bündeln?
2. **Welche Pings hemmen:** nur Checks aus dem Template „Host Ping“ (Empfehlung) oder jeder `ping`-Check des Servers?
3. **Rangfolge bestätigen:** Host-Ping unterdrückt auch den Heartbeat; ein `critical` Heartbeat unterdrückt den
   Host-Ping nicht mehr (sonst schalten sich beide stumm, wenn der Host weg ist).
4. **Host-Ping in die Sammelmeldung?** Fällt die Uplink-Verbindung, meldet jeder Host-Ping einzeln. Empfehlung: nicht
   in diesem Vorhaben, eigene Roadmap-Zeile, weil der Aufschub von bis zu 5 Minuten den schnellen Ping-Weg bremst.
5. **Template „Host Ping“:** als sechstes mitgeliefertes Template (opt-in, nicht vorgeschlagen, nicht Teil der beiden
   „— Standard“-Templates) mit `1m`, 3 Fehlschlägen, `timeout` 3 s — so gemeint?
6. **Default 2 auch für bestehende Checks mit langem Intervall** (Disk Forecast `1h`: Entwarnung nach 2 h) — so
   lassen?

## Entscheidungen am Gate

Entscheidungen am Gate (Kevin 2026-10-19): `consecutive_oks` Default 2; die mitgelieferten Templates setzen bei Checks mit Intervall ab 1 h (SMART, Prognose) 1, einstellbar je Check. Server-Vertrag `POST /api/internal/events` bekommt `source_ids` (Empfänger je Nutzer, `alert.triggered` je Server; Events ohne das Feld wie heute an die Admins). Host-Ping als sechstes Template (1 min, 3 Fehlschläge, 3 s Timeout); Host-down lösen nur Pings aus diesem Template aus; Host-Ping unterdrückt den Heartbeat, nicht umgekehrt; Host-Ping nicht in der Sammelmeldung; ein einzelner stummer Agent wird bis zu 5 min zurückgehalten. Gebaut wird nach dem Merge von monitoring-hardening (`alerter.py`: deren Logzeilen und der except-Zweig der Regelschleife bleiben dort). Korrektur Kevin 2026-10-20: nur Disk Forecast (Intervall 1 h) bekommt 1, SMART (5 min) bleibt bei 2; umgesetzt in T17, das `linux-base` und `windows-base` auf Version 2 hebt.
