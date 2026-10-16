<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Templates: Anpassungen erhalten, Standard-Templates aktualisieren

Roadmap R-0420 (FEAT) · Kevin, Monitoring-Analyse und Lab nach der Installation v0.45.0, 2026-10-16.
Stand des Codes: `origin/main@af4498a7`. Alle `datei:zeile` beziehen sich auf diesen Stand.

Dieses Vorhaben ist Phase A von R-0420. Der Discovery-Vorschlag (Phase B) ist ein eigenes Vorhaben:
`docs/features/monitoring-discovery.md` (Kevin 2026-10-16: zwei Vorhaben).

## Problem / Motivation

1. **Ein neuer Server wird nicht überwacht.** Im Lab hatte ein frisch provisionierter Server nach dem ersten
   Push `0` Checks und keine Template-Zuweisung. Zuweisung ist reines Opt-in (Dropdown im Server-Dialog mit
   Vorauswahl „keins“, Monitoring-Tab, Tag-Bindung); Provisionierung und API weisen nichts zu. Die Entscheidung
   „keine Auto-Zuweisung nach OS-Typ“ steht in `docs/features/monitoring-overhaul.md:50` und `:262` und gilt weiter
   (Kevin 2026-10-16). Gelöst wird das mit dem Vorschlag im Vorhaben monitoring-discovery; dieses Vorhaben schafft
   die Voraussetzung, dass Template-Inhalte bestehende Installationen überhaupt erreichen.
2. **Der Template-Sync überschreibt eigene Anpassungen.** `_sync_checks_for_server`
   (`apps/monitoring/app/template_sync.py:198-249`) setzt bei jeder Template-Änderung Name, Typ, Config,
   Intervall, Severity, `consecutive_fails`, `enabled` und Beschreibung jedes erzeugten Checks auf die
   Template-Werte zurück (`:219-227`). Ein im Check deaktivierter Check wird wieder eingeschaltet (`:226`).
   Ein gelöschter, vom Template erzeugter Check entsteht beim nächsten Sync neu (`:234-239`).
   Der Check-Editor zeigt nicht, dass ein Check aus einem Template stammt.
3. **Standard-Templates bekommen nie neue Inhalte.** `seed_builtin_templates`
   (`apps/monitoring/app/builtin_templates.py:181-207`) legt jeden Slug genau einmal an (`:187-191`).
   Eine verbesserte Definition in einem späteren Release erreicht bestehende Installationen nie, auch dort
   nicht, wo niemand das Template angefasst hat. Das ist dieselbe Lücke wie bei Zabbix („templates are not
   upgraded automatically“, https://www.zabbix.com/documentation/current/en/manual/config/templates_out_of_the_box).
4. **Ein neuer Hostname oder Servername erreicht bestehende Zuweisungen nie.** Die Variablen
   `{{hostname}}`/`{{server_name}}` kommen aus den Spalten der Zuweisung (`template_sync.py:76-82`), die nur beim
   Anlegen gesetzt werden. Der Server meldet Umbenennungen schon an den Monitoring-Dienst
   (`apps/server/app/modules/servers/router.py:172-177`), aber `sync_tag_assignments` überspringt bestehende
   Zuweisungen (`apps/monitoring/app/tag_sync.py:82-84`).

## Ziel & Nicht-Ziele

Reine Monitoring-Dienst- und Desktop-UI-Arbeit; Agent und Server bleiben unverändert.

**Ziele**
- Ändert der Nutzer an einem vom Template erzeugten Check ein Feld, merkt sich der Check dieses Feld als
  **angepasst** (`overridden_fields`). Der Sync überschreibt angepasste Felder nicht mehr, alle anderen weiter.
  Ein Feld, das wieder auf den Template-Wert gesetzt wird, gilt nicht mehr als angepasst.
- Der Check zeigt in der Desktop-UI ein Badge „angepasst“ (mit den Feldern als Tooltip) und eine Aktion
  **„Auf Template zurücksetzen“**.
- Ein gelöschter, vom Template erzeugter Check bekommt einen **Tombstone**; der Sync legt ihn nicht wieder an.
  Im Monitoring-Tab des Servers steht je Zuweisung „N gelöschte Template-Checks wiederherstellen“.
- Standard-Templates bekommen eine **Version** und einen **Inhalts-Hash**. Beim Start gilt: Ein unverändertes
  Standard-Template wird auf die neue Version gehoben und synchronisiert; ein angepasstes bleibt, wie es ist,
  und zeigt **„Update verfügbar“** mit einem Vergleich und „Übernehmen“. Ein gelöschtes bleibt gelöscht
  (Tombstone in `monitor_seed_state` wie heute).
- Ein neuer Hostname oder Servername erreicht alle Zuweisungen (manuell und per Tag) und ihre Checks, ohne
  angepasste Felder zu überschreiben.

**Nicht-Ziele (YAGNI)**
- Discovery-Vorschlag (Agent meldet `host`-Block, „Zuweisen/Ignorieren“): eigenes Vorhaben monitoring-discovery.
- Keine Auto-Zuweisung bei Provisionierung oder Server-Anlage (`monitoring-overhaul.md:50`, bestätigt
  2026-10-16).
- Keine Template-Vererbung; Tags plus Anpassungen je Check reichen.
- Keine Anpassungen an Alert-Definitionen (`MonitorAlertRule`) — Built-ins haben heute keine
  (`builtin_templates.py:115`, `:122` …); eigene Templates mit Alert-Defs behalten das heutige Sync-Verhalten.
- Linux-Basis v2 (Swap, Inodes, Zeit-Sync, Reboot nötig …) und Alert-Qualität (Haltezeit, Cooldown, Host-down
  ohne Agent): eigene Folgezeilen (Notiz an R-0420). Erst nach diesem Vorhaben erreichen neue Template-Inhalte auch
  bestehende Installationen; Linux-Basis v2 setzt also hierauf auf.
- Keine Erkennung früherer Handanpassungen in der Migration selbst; das übernimmt einmal der erste Start (T13, siehe
  Risiken; Kevin 2026-10-16).

## Betroffene Komponenten & Dateien

**Monitoring-Dienst (`apps/monitoring`)**
- `app/models.py` — `MonitorCheck` (`:24-40`, `to_dict` `:42-60`), `MonitorTemplate` (`:167-200`),
  `MonitorTemplateAssignment` (`:203-232`); neues Modell siehe unten.
- `alembic/versions/` — eine neue Revision nach dem heutigen Kopf `c1d3e5f7a9b1` (`c1d3e5f7a9b1_notified_status.py`).
- `app/template_sync.py` — `_build_variables` `:76-82`, `_create_check` `:85-107`, `_sync_checks_for_server`
  `:188-249`, `apply_template` `:309-365`, `remove_template` `:373-413`, `cleanup_server` `:421-455`.
- `app/routers/checks.py` — `update_check` `:180-253` (Feldschleife `:232-241`), `delete_check` `:255-268`,
  `toggle_check` `:271-287`.
- `app/routers/templates.py` — `GET /templates/assignments/{server_id}` `:80`, `update_template` `:157-193`,
  `assign_template` `:223-249`.
- `app/builtin_templates.py` — `BUILTIN_TEMPLATES` `:93-178`, `seed_builtin_templates` `:181-207`;
  Aufruf im Lifespan `app/main.py:56`.
- `app/tag_sync.py` — `sync_tag_assignments` `:57-124`.
- Tests: `tests/test_template_sync.py`, `tests/test_seed.py`, `tests/test_templates_router.py`,
  `tests/test_tag_sync.py`, `tests/test_checks_crud.py`, `tests/openapi.snapshot.json`; neu
  `tests/test_template_overrides.py`.

**Desktop-UI (`apps/desktop/ui`)**
- `src/lib/api/types.ts` — `TemplateAssignment` `:50`, `MonitorCheck` `:363`, `MonitoringTemplateFull` `:556`.
- `src/lib/api/monitoring.ts` — Template-Aufrufe `:109-184`.
- `src/components/monitoring/section/MonCheckLine.svelte` (Aktionen `:84-103`),
  `src/components/monitoring/MonitorCheckModal.svelte`.
- `src/components/infra/tabs/MonitoringTab.svelte` (Template-Abschnitt `:171-206`).
- `src/components/monitoring/MonitoringTemplates.svelte`, `MonitoringTemplateModal.svelte`.
- `src/lib/i18n/dictionaries.ts` (DE + EN).

**Server (`apps/server`): keine Änderung.** Der Proxy lässt nur bekannte Präfixe durch
(`apps/server/app/modules/monitoring_proxy/router.py:59-66`: `checks`, `alerts`, `status`, `templates`,
`maintenance`, `agent`). Alle neuen Routen liegen unter `checks/…` bzw. `templates/…`; der Allowlist-Test
(`apps/server/tests/test_monitoring_proxy_allowlist.py`) bleibt grün.

**Agent: keine Änderung.**

## Datenmodell / API / Migrationen

Migration und neue Routen sind von Kevin freigegeben (2026-10-16).

**Eine Revision `…_template_overrides_versions` (down_revision `c1d3e5f7a9b1`)**
- `monitor_checks.overridden_fields` — `Text`, `NOT NULL`, `server_default '[]'`: JSON-Liste der angepassten
  Felder aus `{name, description, check_type, config, enabled, interval, severity, consecutive_fails}`.
  Bestandschecks bekommen `[]`; der erste Start markiert einmal, was vom Template abweicht (T13).
- `monitor_templates.builtin_version` — `Integer NULL`; `monitor_templates.builtin_hash` — `String NULL`
  (sha256 der zuletzt ausgerollten mitgelieferten Definitionen).
- Neue Tabelle `monitor_check_tombstones`: `id String PK`, `template_id String FK monitor_templates.id ON DELETE
  CASCADE`, `server_id String NOT NULL` (Index), `def_id String NOT NULL`, `created_at DateTime` (UTC-naiv wie
  der Rest, `utc_now_sql()`), `UniqueConstraint(template_id, server_id, def_id)`.
- Downgrade entfernt Spalten und Tabelle.

**Antwortfelder (additiv, keine Feldumbenennung)**
- Check (`MonitorCheck.to_dict`): `templateDefId`, `overriddenFields: string[]`.
- Zuweisungen (`GET /templates/assignments/{server_id}`): je Eintrag `removedChecks: number` (Tombstones).
- Template (`MonitorTemplate.to_dict`): `builtinVersion`, `builtinEdited: bool`, `builtinUpdateAvailable: bool`.

**Neue Routen (alle `require_internal`, nur über den Admin-Proxy erreichbar)**
| Methode | Pfad | Zweck | Fehler |
|---|---|---|---|
| POST | `/checks/{check_id}/reset` | Anpassungen verwerfen, Template-Werte setzen | 404 unbekannt; 409 kein Template-Check bzw. Definition nicht mehr im Template |
| POST | `/templates/{template_id}/assign/{server_id}/restore` | Tombstones der Zuweisung löschen, Server neu synchronisieren → `{"restored": n}` | 404 Zuweisung fehlt |
| GET | `/templates/{template_id}/builtin-update` | `{currentVersion, shippedVersion, current: {checkDefinitions, alertDefinitions}, shipped: {…}}` | 404 kein Standard-Template |
| POST | `/templates/{template_id}/builtin-update` | mitgelieferte Definitionen übernehmen, Version/Hash setzen, synchronisieren | 404; 409 kein Update verfügbar |

Der OpenAPI-Snapshot des Monitoring-Dienstes (`apps/monitoring/tests/openapi.snapshot.json`) wächst um die
neuen Pfade; bestehende Pfade bleiben (ihre Antworten sind untypisiert `{}`).

**Regeln im Detail**
- *Angepasst markieren* (`update_check`, `toggle_check`): nur für Checks mit `template_id` und
  `template_def_id`, deren Definition noch im Template steht. Für jedes gesendete Feld aus der Liste oben wird
  mit dem **aufgelösten Template-Wert** verglichen (Variablen substituiert): anders → in `overridden_fields`,
  gleich → heraus. Ein Wechsel von `check_type` markiert `check_type` und `config`. Manuelle Checks bleiben
  unberührt.
- *Sync*: angepasste Felder werden nicht geschrieben, alle anderen wie heute. Ist `config` angepasst, schreibt
  der Sync auch `check_type` nicht (Gegenstück zum Typwechsel oben): Ein neuer Template-Typ neben der Config des
  Nutzers wäre ein ungeprüftes Paar (Session 2026-10-16). Steht eine Definition nicht mehr im Template, wird ihr
  Check weiterhin gelöscht — auch wenn er angepasst ist (das Template ist Eigentümer).
- *Tombstone*: `DELETE /checks/{id}` auf einem Template-Check mit bestehender Zuweisung legt einen Tombstone an.
  `remove_template`, `cleanup_server` und das Löschen des Templates (Cascade) räumen die Tombstones mit ab;
  ein erneutes Zuweisen legt also wieder alles an.
- *Built-in-Hash*: sha256 über das kanonische JSON (`sort_keys=True`, `separators=(",", ":")`) von
  `[check_definitions, alert_definitions]`. Name und Beschreibung zählen nicht — ein umbenanntes Standard-Template
  bleibt „unverändert“ und bekommt Updates, ohne dass sein Name überschrieben wird.
- *Bestand*: Eine Template-Zeile mit `builtin_slug`, aber ohne `builtin_hash` (vor der Migration angelegt), bekommt
  beim ersten Start `builtin_version = 1` und den Hash der heute mitgelieferten Definitionen. Weichen ihre
  Definitionen davon ab, gilt sie damit als angepasst.
- *Auto-Update*: `version(mitgeliefert) > builtin_version` und Hash der aktuellen Definitionen = `builtin_hash`
  → Definitionen ersetzen, Version und Hash setzen, `sync_template`. Sonst nur `builtinUpdateAvailable`.
- *Umbenennung*: `sync_tag_assignments` vergleicht für **jede** Zuweisung `server_hostname`/`server_name` mit dem
  Inventar und synchronisiert bei Abweichung genau dieses (Template, Server)-Paar neu.

## Externe Integrationen

Keine Wire-Protokolle. Vorbild, nur als Begründung: Zabbix aktualisiert mitgelieferte Templates nicht automatisch
(Link oben); hier wird ein unverändertes Standard-Template automatisch, ein angepasstes nur auf Klick aktualisiert.

## Trade-offs & Alternativen

1. **Anpassungen je Feld vs. „Check vom Template lösen“.** Lösen (Check wird manuell) ist einfacher, verliert aber
   jede spätere Template-Verbesserung für diesen Check. Je Feld ist etwas mehr Code und erhält beides.
   **Gewählt: je Feld.**
2. **Tombstone-Tabelle vs. Flag `deleted` am Check.** Ein Flag hielte unsichtbare Checks im Scheduler-Pfad und in
   jeder Abfrage. Eine eigene Tabelle ist sauber getrennt. **Gewählt: Tabelle.**
3. **Built-in-Update automatisch vs. immer fragen.** Immer fragen ist sicherer, lässt aber unberührte
   Installationen auf altem Stand — genau das Problem. Automatisch nur bei unveränderten Templates, sonst fragen.
   **Gewählt: so.**
4. **Ein oder zwei Vorhaben.** Zwei (Kevin 2026-10-16): dieses Vorhaben braucht keinen Agent und keine
   Vertragsdatei `report.go`; der Vorschlag folgt als monitoring-discovery.

## Risiken & Rollback

- **Bestandsdaten:** Die Migration ändert keine bestehenden Werte (`overridden_fields` = `[]`). Weil seit T7 auch
  ein Namensabgleich (und das Wiederherstellen) ein Paar neu synchronisiert, gingen ungemerkte Anpassungen von vor
  dem Update sonst schon beim ersten Tag-Sync verloren. Deshalb erkennt T13 sie einmal beim ersten Start: Vergleich
  mit dem Template, aufgelöst mit den gespeicherten Namen der Zuweisung; abweichende Felder gelten als angepasst
  (Kevin, 2026-10-16). Restrisiko: Ein Template, dessen Änderung vor dem Update nie auf einen Check synchronisiert
  wurde, erscheint dort als angepasst.
- **Auto-Update eines Built-ins** ändert Checks auf vielen Servern auf einmal. Begrenzung: nur unveränderte
  Templates, nur nicht angepasste Felder; Logzeile mit Anzahl. In diesem Vorhaben gibt es keine neue
  mitgelieferte Version (alle bleiben `1`), der Pfad ist nur per Test belegt; ausgelöst wird er erst von
  „Linux-Basis v2“.
- **Rollback:** Revert des Merge-Commits plus `alembic downgrade` um die neue Revision; Spalten und Tabelle
  tragen nur Metadaten, ihr Verlust stellt das heutige Verhalten wieder her.

## Doku-Impact

Sichtbare Änderung, DE + EN: `docs/admin/monitoring.html` und `docs/en/admin/monitoring.html` (Abschnitt Templates
`:139-181`: Anpassungen, Badge, Zurücksetzen, Wiederherstellen, Updates der Standard-Templates, Umbenennung,
Hinweis zu Anpassungen vor dem Update), `docs/developer/monitoring.html` und EN (Templates `:155`), `CHANGELOG.md`.

## Offene Fragen

Keine. Entschieden von Kevin am 2026-10-16:

1. **Ein oder zwei Vorhaben:** zwei — dieses (Phase A) jetzt, der Discovery-Vorschlag als monitoring-discovery
   nach R-0417, R-0418 und R-0419.
2. **Migration und Routen** wie oben: freigegeben.
3. **Anpassungen von vor dem Update** sind danach nicht als „angepasst“ erkennbar: hingenommen, in CHANGELOG und
   Doku genannt.
