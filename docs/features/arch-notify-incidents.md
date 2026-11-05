<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-notify-incidents — Vorfälle statt loser Glocken-Einträge

Roadmap: R-1079 (FEAT, Kevin 2026-11-02, Architektur-Session). Baut auf R-1078 (kern-notify-1: Glocke, Panel,
Benachrichtigungs-Center nach Mockup) auf. Vorlage: `AdminCave/DesignSystem@244e890`
(`ui_kits/adminhelper/notifications.jsx`: `Detail`, `NotificationsView`). Stand `origin/main@a3645c00`.
Verwandt: R-1080 (kern-notify-2: Kanäle ntfy/Telegram/Webhook, Matrix, Test-Knopf) und R-1081 (kern-notify-3: Ruhezeiten,
zeitgesteuerte Eskalation unbestätigter Vorfälle, Digest, Ton). Beide bauen auf diesem Vorhaben auf und sind hier
Nicht-Ziel.

## Problem / Motivation

Die Glocke kennt heute nur „gelesen/ungelesen“. Jede Meldung ist eine lose Zeile (`apps/server/app/modules/notifications/models.py:82`
`Notification`), ohne Zustand, ohne Zusammenhang mit der Meldung davor und ohne Verlauf. Das Mockup verlangt Vorfälle:

- **Zustände:** offen → bestätigt (mit wer) → behoben; „Wieder öffnen“. `isOpen` = warning/critical, Zustand offen, nicht
  stumm. Der Desktop behilft sich bis hierher mit „ungelesen und warning/critical“
  (`apps/desktop/ui/src/lib/models/notifications.ts:18`, Kommentar „until R-1079“).
- **Bündeln gleicher Ereignisse (×n):** ein wiederholtes Ereignis desselben Checks zählt hoch, statt eine neue Zeile
  zu schreiben.
- **Verlauf:** Ausgelöst (Regel) → Benachrichtigt (Kanäle) → Eskaliert/Bestätigt/Notiz/Behoben („automatisch — Check
  wieder grün“); **Notizen** fürs Team; **Stummschalten** (1 Stunde, bis morgen 07:00, Server für 24 h) samt
  Postfach „Stumm“; Postfächer Posteingang/Offen/Bestätigt/Behoben/Stumm/Alle; Sammelaktionen Gelesen/Bestätigen/
  Ausblenden; im Detail Zeitpunkt, Regel, Kanäle („nur Glocke“), ID.
- **Glocke und Alert-Regeln laufen nebeneinander:** Das Monitoring schickt eine Transition über seine Regeln
  (`apps/monitoring/app/alerter.py:129` `send_to_rule`: Webhook/E-Mail, `MonitorAlertRule`
  `apps/monitoring/app/models.py:193`) und getrennt davon an die Glocke (`alerter.py:303` `_notify_bell` →
  `emit_to_hub`, `alerter.py:483`). Die Glocke weiß nicht, welche Regel gefeuert hat und ob der Versand gelang; das
  Mockup zeigt beides am Vorfall.
- **Der Glocken-Cooldown lässt den Zustand lügen:** `hub_decision` (`alerter.py:450`) verwirft im Monitoring jede
  weitere Problem-Meldung eines Checks innerhalb von `HUB_COOLDOWN` (30 min, `alerter.py:67`). Bisher harmlos, weil
  jede Meldung eine Zeile war. Mit Vorfällen wird es falsch: critical → ok → critical binnen 30 min lässt den Vorfall
  „behoben“ stehen, während der Check rot ist, und das ×n kann nicht zählen, was nie ankommt.
- **Kategorien:** die Erzeuger des Servers schreiben `lifecycle` (`main.py:232`, `frp/supervisor_watch.py:179`,
  `enrollment/expiry.py:146`, `notifications/event_bridge.py:61` und `:75`). Das Mockup kennt Monitoring, Sicherheit,
  Tunnel, Backups, Ansible, Agent & Updates, Sitzungen.

## Ziel & Nicht-Ziele

**Ziel**
1. Ein **Vorfall** (`notification_incident`) ist die Team-Wahrheit über ein Problem: Zustand, Schweregrad, Zähler,
   Regel und Kanäle, Verlauf, Notizen. Jede:r Empfänger:in hat genau eine Feed-Zeile je Vorfall (`notification`
   mit `incident_id`), die gelesen/ungelesen, stumm und ausgeblendet trägt.
2. Der **Hub faltet**: ein Ereignis mit Schlüssel (`incident_key`, Monitoring: `check:<check_id>`) landet im offenen
   Vorfall dieses Schlüssels, öffnet einen kürzlich behobenen still wieder oder legt einen neuen an. Eine Erholung
   behebt den Vorfall automatisch.
3. **Kevins Glocken-Regel bleibt wörtlich** (2026-10-19, `docs/features/monitoring-alert-quality.md`): „je Check
   höchstens eine Problem-Meldung in 30 Minuten an die Glocke; Recovery und Eskalation warning → critical gehen immer
   durch; was der Cooldown schluckt, wird nicht nachgeholt.“ Sie wandert nur vom Monitoring in den Hub: das Monitoring
   meldet jede Transition, der Hub entscheidet, ob sie **anpingt** (ungelesen, Outbox, Toast) oder **still faltet**.
4. **Glocke und Alert-Regeln zusammenführen:** das Monitoring meldet mit jedem Ereignis die gefeuerten Regeln und ihr
   Ergebnis (`rules: [{name, channel, ok}]`); der Vorfall zeigt „Regel“ und „Kanäle“, der Verlauf „Benachrichtigt“.
   Die Regel-Engine (Match, Regel-Cooldown, Versand, `MonitorAlertLog`) bleibt im Monitoring.
5. **Aktionen:** bestätigen (einzeln und als Sammelaktion), als behoben markieren, wieder öffnen, Notiz; je Person:
   stumm bis (Vorfall), Server stumm bis, ausblenden, als ungelesen markieren. Jede Aktion stupst die
   Mitempfänger:innen per SSE an.
6. **Kategorien nach Mockup** in allen Erzeugern des Servers, Altzeilen und Abos per Datenmigration.
7. **Desktop:** echtes `isOpen`, Postfächer, Detail mit Aktionen, Verlauf, Notizen, Stumm-Menü, „Regel bearbeiten“
   (öffnet die Monitoring-Alerts), Sammelaktionen, Schnell-„Bestätigen“ im Glocken-Panel; Toast bei jedem Anpingen,
   nicht nur bei neuer Zeile.

**Nicht-Ziele (YAGNI)**
- Neue Kanäle, Kanal-Matrix, Test-Knopf (R-1080); Ruhezeiten, zeitgesteuerte Eskalation, Digest, Ton (R-1081).
  „Eskaliert“ heißt hier nur: Schweregrad warning → critical.
- Kein Web-Frontend (`apps/web` nutzt `/api/notifications` nicht). Keine Zuweisung an Personen, kein SLA.
- Keine Vorfälle für `info`- und `ok`-Ereignisse ohne Schlüssel: sie bleiben einfache Zeilen ohne Zustand.
- Keine Monitoring-Migration: `hub_status`/`hub_sent_at` bleiben und werden weiter geschrieben.
- Backups/Ansible/Sitzungen sind nur Vokabular: kein Erzeuger schreibt sie in diesem Vorhaben.
- Stummschalten wirkt nur auf den Desktop-Kanal und die Outbox der Person, nicht auf die Alert-Regeln des Monitorings
  (die sind Team-Konfiguration; dafür „Regel bearbeiten“).

## Betroffene Komponenten & Dateien

| Komponente | Dateien | Änderung |
|---|---|---|
| server | `app/modules/notifications/models.py` | neue Tabellen, neue Spalten an `Notification`, `to_dict` |
| server | `app/modules/notifications/schemas.py` (`IncomingEvent` :20) | `incident_key`, `incident_keys`, `rules`; Aktions-Schemas |
| server | `app/modules/notifications/service.py` (`ingest_event` :205, `notify_users` :263, `cleanup_old_notifications` :296) | Falten über ein neues Modul |
| server | `app/modules/notifications/incidents.py` (neu) | Falten, Zustandsübergänge, Verlauf, Detail |
| server | `app/modules/notifications/router.py` (Feed :54, Ingress :200) | Feed-Felder, Sortierung, Aktionen, `alert.triggered` nur beim Anpingen |
| server | `main.py:232`, `frp/supervisor_watch.py:179`, `enrollment/expiry.py:146`, `notifications/event_bridge.py:61/:75` | Kategorien |
| server | `alembic/versions/` (Kopf `b4d6f8a0c2e1`) | zwei Migrationen: Kategorien (Daten), Vorfälle (Schema + Backfill) |
| server | `tests/openapi.snapshot.json` | neue Routen und Felder |
| monitoring | `app/alerter.py` (`send_to_rule` :129, `process_alert` :165, `hub_decision` :450, `emit_to_hub` :483) | Cooldown raus, Schlüssel und Regel-Ergebnisse ins Ereignis |
| monitoring | `app/alert_bundle.py` (`_send_rules` :339, `_send_bell` :411, `_bundle_payload` :464) | dasselbe für Bündel |
| desktop-ui | `src/lib/api/types.ts:609`, `src/lib/api/notifications.ts`, `src/lib/models/notifications.ts`, `src/lib/stores/notifications.ts` (Toast-Erkennung :46–69) | Vertrag, Modell, Store |
| desktop-ui | `src/pages/Notifications.svelte`, `src/components/NotificationBell.svelte`, neu `src/components/NotificationDetail.svelte`, `src/lib/i18n/dictionaries.ts` | Oberfläche |
| desktop-e2e | `apps/desktop/e2e/test/specs/notification-push.live.js`, `apps/desktop/e2e/test/lib/live.js` | Vorfall-Journey |
| docs | `docs/developer/server.html`, `docs/developer/api-reference.html`, `docs/developer/monitoring.html`, `docs/developer/hooks.html`, `docs/developer/desktop.html`, `docs/admin/monitoring.html` (+ `docs/en/…`) | siehe Doku-Impact |

Kein Rust-Code: der Desktop ruft die neuen Routen über den generischen `api_proxy` (`apiRequest`), der keine
Pfad-Allowlist führt; der SSE-Client sendet weiter nur den Anstoß `notification`.

## Datenmodell / API / Migrationen

### Tabellen (Server, Alembic)

`notification_incident`
| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` | BigInteger PK | Vorfall-ID (im Detail „ID“) |
| `key` | String, nullable, Index | `check:<id>` für Einzel-Vorfälle; NULL für Bündel und schlüssellose Ereignisse |
| `state` | String | `open` · `acked` · `resolved` |
| `severity` | String | aktueller Schweregrad (warning/critical) |
| `notified_severity` | String, nullable | was die Glocke zuletzt gezeigt hat: warning/critical nach einem Problem-Ping, `ok` nach einem Erholungs-Ping, NULL nie gepingt (Gegenstück zu `MonitorState.hub_status`) |
| `last_notified_at` | DateTime, nullable | letzter Problem-Ping (Gegenstück zu `hub_sent_at`) |
| `category`, `event_type`, `title`, `body`, `source_type`, `source_id` | wie `Notification` | Stand des letzten Ereignisses, Team-Fassung |
| `rules` | Text (JSON), nullable | Regel-Ergebnisse des letzten Problem-Ereignisses |
| `event_count` | Integer | ×n: Problem-Ereignisse dieses Vorfalls |
| `first_at`, `last_at` | DateTime | erstes/letztes Ereignis |
| `acked_by`, `acked_at`, `resolved_by`, `resolved_at` | FK users (SET NULL) / DateTime | `resolved_by` NULL = automatisch |

`notification_incident_member` (nur Bündel): `incident_id` (FK CASCADE), `key` (Index), `server_id`, `recovered_at`.

`notification_incident_event` (Verlauf): `id`, `incident_id` (FK CASCADE, Index), `at`, `kind`
(`triggered` · `notified` · `escalated` · `acked` · `resolved` · `reopened` · `note`), `actor_id` (FK users SET NULL,
NULL = automatisch), `text` (≤ 2000), `severity`, `server_id` (nullable: Eintrag gilt nur einem Bündel-Mitglied).
Je Vorfall höchstens 200 Einträge; beim Schreiben fallen die ältesten automatischen Einträge, nie Notizen,
Bestätigungen oder manuelle Übergänge.

`notification_server_mute`: `user_id` (FK CASCADE), `server_id`, `until`; eindeutig je (user, server).

`notification` neue Spalten: `incident_id` (FK CASCADE, nullable, Index), `notified_at` (Backfill = `created_at`,
danach NOT NULL), `muted_until` (nullable), `hidden_at` (nullable); eindeutig je (`user_id`, `incident_id`), wo
`incident_id` gesetzt ist.

Altzeilen bleiben ohne Vorfall (Zustand „—“ im Desktop, `isOpen` falsch). Retention: Zeilen ohne Vorfall nach
`notified_at`; Vorfälle, die behoben sind und deren `last_at` älter als die Retention ist, samt Zeilen, Mitgliedern
und Verlauf. Ein offener Vorfall wird nie gelöscht.

### Falten im Hub (`incidents.py`, aufgerufen aus `ingest_event` und `notify_users`)

`REOPEN_WINDOW = 30 min` (dieselbe Zahl wie `HUB_COOLDOWN`). Ein **Ping** schreibt je Empfänger:in (neu aufgelöst
über `resolve_recipients`, Least-Privilege wie heute) die Zeile neu: `read_at`/`hidden_at` NULL, `notified_at` = jetzt,
Titel/Text der Person (`_bundle_text` bei Bündeln), Outbox-Zeilen; neue Empfänger:innen bekommen eine neue Zeile.
Ist die Zeile stumm (`muted_until` > jetzt oder Server-Stumm für ein Einzel-Server-Ereignis), bleibt sie gelesen,
ohne Outbox. Ein **stilles Falten** ändert nur den Vorfall und seinen Verlauf.

Problem-Ereignis (warning/critical) mit Schlüssel:
1. Ein aktiver Vorfall (`open`/`acked`) trägt den Schlüssel (als `key` oder als Mitglied) → falten, `event_count` + 1.
2. Sonst ein behobener Vorfall mit dem Schlüssel und `last_notified_at` in `REOPEN_WINDOW` → still wieder öffnen
   (`reopened`, automatisch), `event_count` + 1.
3. Sonst → neuer Vorfall (`triggered`).
Ob gepingt wird, entscheidet dieselbe Regel wie heute `hub_decision`: Ping, wenn der Vorfall neu ist, wenn
`notified_severity` warning ist und das Ereignis critical (`escalated`; ein bestätigter Vorfall geht dabei zurück auf
`open`), oder wenn `last_notified_at` älter als `REOPEN_WINDOW` ist. Sonst still. Ein Ping schreibt `notified`
(Kanäle) in den Verlauf.

Erholung (`new_status` ok) mit Schlüssel: aktiver Vorfall → `resolved` (automatisch, „Check wieder grün“); Ping
genau dann, wenn `notified_severity` warning/critical ist (danach `ok`), wie heute „die Glocke räumt nur, was sie
gezeigt hat“. Bei einem Bündel setzt sie `recovered_at` des Mitglieds (stiller Verlaufseintrag mit `server_id`);
behoben ist es, wenn alle Mitglieder erholt sind. Ohne aktiven Vorfall: ein stiller Verlaufseintrag am letzten
Vorfall des Schlüssels, sonst nichts.

Bündel (`source_ids` mit `incident_keys` gleicher Länge und Reihenfolge): je Schlüssel dieselben Schritte; alle
Schlüssel aus Schritt 3 bilden zusammen **einen** neuen Bündel-Vorfall mit Mitgliedern (feste Mitgliedschaft).

Schlüssellose Ereignisse (cert-expiry, frps, frp_config, event_bridge): warning/critical → je Ereignis ein eigener
Vorfall, aber nur mit mindestens einer Empfänger:in (sonst entstünden bei `notify_expiring`, das ohne Zeile jeden
Lauf neu versucht, verwaiste Vorfälle); keine automatische Erholung. `info` → Zeile ohne Vorfall wie heute. Die
Dedup der Erzeuger über `source_type`/`source_id` der Zeilen bleibt unberührt.

`alert.triggered` (`router.py:219–245`) feuert nur noch für die Server eines **critical-Pings** (neuer Vorfall oder
Eskalation), nicht beim stillen Falten: genau die Fälle, in denen er heute feuert.

### API (eigener Scope `/api/notifications`, angemeldete Person)

Feed (`GET ""`) bekommt je Zeile: `incidentId`, `state`, `count`, `ackedBy`, `resolvedBy` (Benutzername oder NULL =
automatisch), `notifiedAt`, `muted`, `mutedUntil`, `muteSource` (`incident`/`server`). Sortierung `notified_at desc,
id desc`; ausgeblendete Zeilen fehlen. `unread-count` zählt ohne stumme und ausgeblendete.

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| GET | `/incidents/{id}` | — | Detail: Vorfall, sichtbare Server/Mitglieder, Regeln, Kanäle, Verlauf (gefiltert nach Server-Sichtbarkeit), `canAct` |
| POST | `/incidents/ack` | `{ids}` (≤ 500) | `{updated, skipped}` |
| POST | `/incidents/{id}/resolve` | — | Detail |
| POST | `/incidents/{id}/reopen` | — | Detail |
| POST | `/incidents/{id}/notes` | `{text}` (1–2000) | Detail |
| PUT / DELETE | `/incidents/{id}/mute` | `{until}` (ISO, > jetzt, ≤ jetzt + 7 d) | Feed-Zeile |
| GET | `/server-mutes` | — | Liste |
| PUT / DELETE | `/server-mutes/{server_id}` | `{until}` (wie oben) | Eintrag |
| POST | `/hide` | `{ids}` | `{updated}` |
| POST | `/unread` | `{ids}` | `{updated}` |

Zugriff: Detail und persönliche Aktionen verlangen die eigene Zeile zum Vorfall (sonst 404, kein Orakel).
Team-Aktionen (ack, resolve, reopen, note) verlangen zusätzlich, dass die Person **jeden** Server des Vorfalls jetzt
sieht (`_user_can_see`, Admins immer); sonst 403 bzw. `skipped`. Ungültiger Übergang → 409. Nach jeder Team-Aktion
ein SSE-Anstoß an alle Zeilen-Inhaber:innen. „Bis morgen 07:00“ rechnet der Desktop in Ortszeit, der Server prüft nur
die Grenzen. Stummschalten steht nicht im Verlauf (persönlich).

Ingress (`POST /api/internal/events`, `IncomingEvent`): neue optionale Felder `incident_key` (≤ 200, nur mit
`source_id` oder ohne Quelle), `incident_keys` (nur mit `source_ids`, gleiche Länge), `rules` (≤ 50 Einträge
`{name ≤ 200, channel, ok}`). Ältere Sender ohne diese Felder: schlüssellos (siehe oben). OpenAPI-Snapshot wird
nachgezogen.

### Kategorien

Abbildung: `lifecycle.frp.*`, `frp_config`, `frps` → `tunnel`; Zertifikatsablauf → `security`;
`lifecycle.server.deleted` → `agent`; `monitoring` und `security` bleiben. `category` bleibt ein freier String.
Datenmigration: `notification.category = 'lifecycle'` nach `event_type`-Präfix (`lifecycle.frp.%` → tunnel,
`lifecycle.certificate.%` → security, sonst → agent); Abos mit `lifecycle` in `categories` → `tunnel`, `security`,
`agent` (Dubletten entfernt). Downgrade bildet zurück auf `lifecycle`; für Abos verlustbehaftet (wer nach dem Upgrade
nur `tunnel` wählt, hat nach dem Downgrade `lifecycle`), dokumentiert im Migrationskopf.

### Monitoring

- `hub_decision` verliert den Cooldown-Zweig: jede Problem-Transition mit gekapptem Level ≥ warning geht an den Hub,
  Erholungen wie heute nur, wenn `hub_status` warning/critical ist. `hub_status`/`hub_sent_at` werden weiter
  geschrieben (keine Migration; `HUB_COOLDOWN` fällt weg).
- `send_to_rule` gibt `(name, channel, ok)` zurück; `process_alert` sammelt sie und gibt sie `emit_to_hub` mit, dazu
  `incident_key = check:<check.id>`. `alert_bundle` setzt `incident_keys` parallel zu `source_ids` und die Regeln des
  Bündel-Versands.
- Wartungsfenster/Host-down bleiben, wie sie sind (`_claim_transition`): sie halten `notified_status` fest, die
  Erholung kommt beim Nachholen an und behebt den Vorfall.

## Externe Integrationen

Keine neue. Tauri-IPC unverändert (generischer `api_proxy`, Ereignis `notification` ohne Nutzlast). SSE über den
bestehenden `stream_hub` (Redis-Fan-out). Kein FRP, kein VictoriaMetrics.

## Trade-offs & Alternativen

1. **Wo lebt der Cooldown?** (a) im Hub (Empfehlung, gewählt): der Zustand stimmt immer, ×n zählt alles, Ping-Semantik
   bleibt wörtlich. (b) im Monitoring lassen: der Vorfall bleibt nach critical → ok → critical „behoben“ und ×n
   zählt nicht, beides gegen die Zeile. Kosten von (a): mehr Ereignisse über die interne Strecke (eins je
   Transition statt eins je 30 min), vernachlässigbar.
2. **Eine Zeile je (Person, Vorfall)** (gewählt) statt einer Zeile je Ping: ×n und Zustand an einer Stelle, der Feed
   wächst nicht mit dem Flattern. Kosten: der Feed sortiert nach `notified_at`, die Toast-Erkennung im Desktop
   wechselt von „neue ID“ auf „`notifiedAt` vorgerückt“.
3. **Regeln bleiben im Monitoring** (gewählt) statt die Alert-Regeln in den Hub zu ziehen: R-1080 baut die Kanäle neu;
   ein Umzug jetzt hieße Regel-Cooldown, `MonitorAlertLog` und Wartungsfenster doppelt anzufassen. Zusammengeführt wird
   die Sicht (Regel und Kanäle am Vorfall), nicht die Engine.
4. **Stummschalten je Person** (gewählt) statt fürs Team: das Mockup legt es neben „Stumm aufheben“ und ein Postfach
   „Stumm“; ein Team-Stumm wäre ein Wartungsfenster, und das gibt es schon im Monitoring.
5. **Team-Aktionen nur mit Sicht auf alle Server** (gewählt): sonst könnte jemand einen Vorfall für Server schließen,
   die er nicht sieht. Kosten: Nicht-Admins können ein gemischtes Bündel nicht bestätigen (Admins schon).
6. **Eskalation öffnet einen bestätigten Vorfall wieder** (gewählt): eine Bestätigung galt der Warnung; critical
   braucht neue Aufmerksamkeit, und die zeitgesteuerte Eskalation von R-1081 sieht nur unbestätigte Vorfälle.

## Risiken & Rollback

- **Least-Privilege:** Detail, Verlauf und Bündel-Text dürfen keinen Server nennen, den die Person nicht sieht (auch
  nicht als Zahl). Tests je Weg (Feed, Detail, Verlauf mit `server_id`, Aktionen), `security`-Prüfer je Server-Task.
- **Ping-Semantik:** die heutigen Fälle aus `test_alerter_hub.py` (Cooldown, Eskalation, Erholung nur nach gezeigtem
  Problem, nichts nachholen) wandern als Hub-Tests mit und müssen dieselben Pings ergeben.
- **Migration:** Backfill `notified_at` auf großen Tabellen in einem Schritt (`UPDATE … SET notified_at =
  created_at`); Downgrade entfernt Tabellen und Spalten, die Kategorien-Migration bildet zurück. Migrationstest nach
  dem Muster von `test_outbox_expiry_migration.py`.
- **Reihenfolge Server ↔ Monitoring:** `RequestModel` (`app/core/bounds.py:86`) ignoriert unbekannte Felder; ein
  neues Monitoring gegen einen alten Server ergäbe ohne den Monitoring-Cooldown eine Zeile je Transition. Beide liegen
  im selben Stack und Release; auf dem Branch kommt der Server zuerst (T3 vor T5), ein Test sichert, dass ein Ereignis
  mit Schlüssel ohne Hub-Falten nicht still verloren geht.
- **Rollback:** Revert des Merges plus `alembic downgrade` um zwei Revisionen; das Monitoring fällt dann auf den
  alten Cooldown zurück.

## Doku-Impact

DE + EN: `developer/server.html` (Notification-Hub: Vorfälle, Falten, Tabellen), `developer/api-reference.html` (neue
Routen, Felder, Ingress-Felder), `developer/monitoring.html` (Glocke ohne eigenen Cooldown, Schlüssel und
Regel-Ergebnisse), `developer/hooks.html` (`alert.triggered` nur beim critical-Ping), `developer/desktop.html`
(Benachrichtigungs-Center: Postfächer, Detail), `admin/monitoring.html` (Glocken-Cooldown-Absatz, Persönliche
Benachrichtigungen: Zustände, Stummschalten, Kategorien). `changelog.d/arch-notify-incidents.md`.

## Offene Fragen

Keine offene Frage aus Kevins Bereich: Zustände, Aktionen, Bündeln, Verlauf, Stumm-Varianten, Zusammenführen und
Kategorien stehen in der Zeile R-1079 und im Mockup; Kevins Glocken-Regel von 2026-10-19 bleibt wörtlich. Die
Entscheidungen der Session (Trade-offs 1–6, Kategorien-Abbildung, `REOPEN_WINDOW`) stehen im Ledger unter
`## Entscheidungen` und gehen ans Gate.
