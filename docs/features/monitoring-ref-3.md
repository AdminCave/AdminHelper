<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Alarm-Protokoll einmal, Typ-Tabellen gepinnt, Scheduler-Job nach dem Commit, Modulgrenzen, lange Funktionen

Stand des Codes: `origin/main@237b450a`. Alle `datei:zeile` beziehen sich auf diesen Stand. Gebaut wird erst nach
dem Merge von **monitoring-io** (`tasks/monitoring-io.md` auf `feature/monitoring-io`) und **smtp-hardening**
(`tasks/smtp-hardening.md` auf `feature/smtp-hardening`); beide ändern Dateien dieses Pakets (`alerter.py`,
`check_engine.py`, `routers/agent.py`, `routers/checks.py`, `checkers/agent.py`, `models.py`,
`routers/templates.py`). Die Beschreibung folgt deren Endstand (beide Branches auf `origin/main` ohne Konflikt
zusammengeführt, `git merge-tree`, Stand `feature/monitoring-io@5eff9de5`, `feature/smtp-hardening@bcc21c8f`); die
Zeilen greppt der builder nach dem Merge neu. Ledger: `tasks/monitoring-ref-3.md`. Roadmap R-0693, R-0694, R-0695,
R-0696, R-0697 und der Monitoring-Teil von R-0728 (Bündel `/feature-plan --bundle monitoring`). Der Slug trägt die 3:
`monitoring-ref` und `monitoring-ref-2` sind erledigte Ledger, auf die abgeschlossene Roadmap-Zeilen zeigen.

## Problem / Motivation

1. **Das Alarm-Protokoll steht zweimal (R-0693).** `process_alert` (`apps/monitoring/app/alerter.py:90-238`) und
   die Sammelmeldung (`apps/monitoring/app/alert_bundle.py:247-520`) gehen dieselben Schritte: Regeln lesen
   (`alerter.py:149` gegen `alert_bundle.py:356`), „zuletzt gemeldet“ normieren (`alerter.py:157` gegen
   `_reported`, `alert_bundle.py:323-326`), Regel-Match und Cooldown (`alerter.py:195-201` gegen
   `alert_bundle.py:357-363`), Versand mit Isolation je Regel (`alerter.py:203-211` gegen `_dispatch_isolated`,
   `alert_bundle.py:388-396`), eine Log-Zeile je Versand (`alerter.py:213-222` gegen `alert_bundle.py:374-385`),
   den Glocken-Eintrag (`hub_reserved`, `alerter.py:174-177`, gegen `_record_bell`, `alert_bundle.py:515-520`) und
   die Stufe der Glocke (`alerter.py:235` gegen `_bell_severity`, `alert_bundle.py:494-499`). Dafür greift
   `alert_bundle.py` auf elf private Namen von `alerter` zu (`_build_message`, `_rule_matches`, `_is_in_cooldown`,
   `_dispatch`, `_severity_level`, `_LEVEL_SEVERITY`, `_STATUS_LEVEL`, `_emit_to_hub`, `_post_hub_event`,
   `_hub_severity`, `_capped_status`) und auf `check_engine._dispatch_alert_bg` (`alert_bundle.py:149`). Der
   Cooldown-Fehler R-0631 traf beide Kopien; monitoring-io T8 behebt ihn in der gemeinsamen `_is_in_cooldown`, die
   Doppelung bleibt.
2. **Sieben Tabellen tragen die Check-Typen ohne Paritätstest (R-0694).** `check_types.py` nennt sich „single source
   of truth“ (`apps/monitoring/app/check_types.py:5`, Tabelle `:21-34`). Daneben halten die Typen von Hand:
   `_REGISTRY` (`apps/monitoring/app/checkers/__init__.py:31-44`), `CONFIG_MODELS`
   (`apps/monitoring/app/check_configs.py:168-181`), `CHECK_TYPE_METRICS` (`apps/monitoring/app/routers/checks.py:72-111`),
   `_DYNAMIC_METRIC_PATTERNS` (`:114-118`), die funktionslokale Menge `agent_types` (`:444-451`) und
   `_PREV_DETAILS_TYPES` (`apps/monitoring/app/routers/agent.py:64`). Heute stimmen sie überein (Probe unten); nur die
   Desktop-Kopie der Push-Typen ist durch `tests/test_push_only_ui_sync.py` gepinnt. `validate_check_config` lässt
   einen Typ ohne Schema durch (`check_configs.py:184-191`, mit Absicht: unbekannte Typen weist der Router gegen
   `VALID_CHECK_TYPES` ab, gepinnt in `tests/test_check_configs.py:66`); ein Typ, der in `CHECK_TYPES` steht, aber
   kein Schema hat, liefe so ungeprüft durch. Das `Checker`-Protocol kennt nur `run` (`checkers/__init__.py:19-26`);
   welche Push-Checker die vorigen `_details` als drittes Argument nehmen, weiß der Router
   (`routers/agent.py:64`, `:240`). Probe (Endstand, Python 3.13.5, Venv des monitoring-io-Worktrees, dreimal
   gleich): `_REGISTRY`, `CONFIG_MODELS` und `CHECK_TYPE_METRICS` haben genau die 12 Typen, `_DYNAMIC_METRIC_PATTERNS`
   und `_PREV_DETAILS_TYPES` sind Teilmengen; `evaluate` von `proxmox_backup`, `smart_health`, `system_state` und
   `zfs_health` nimmt `(config, report)`, die übrigen drei `(config, report, prev_details)`.
3. **`delete_check` und `delete_template` entfernen den Scheduler-Job vor dem Commit (R-0695).**
   `routers/checks.py:284-287`: `remove_check(check.id)`, dann Tombstone, Löschen, `db.commit()`;
   `apps/monitoring/app/routers/templates.py:236-244` ebenso je Check des Templates. Scheitert der Commit, steht der
   Check weiter in der Datenbank, läuft aber bis zum nächsten Neustart des Dienstes nicht (der Job wird nur in
   `load_all_checks` beim Start neu angelegt, `apps/monitoring/app/scheduler.py:110-135`). Genau diesen Fehler
   beschreibt `template_sync._apply_scheduler_actions` als behoben (`apps/monitoring/app/template_sync.py:52-60`:
   „Mutating the running APScheduler before the rows are persisted (the old behaviour) meant a failed/rolled-back
   commit left ghost jobs … or silently unscheduled checks“). Die übrigen Router-Stellen (`routers/checks.py:180-181`,
   `:264-267`, `:301-304`, `:331-334`) committen zuerst und wiederholen dreimal denselben `if enabled: add_check …
   else: remove_check` -Block.
4. **Modell importiert Domänenlogik, private Namen über Modulgrenzen (R-0696).** `MonitorTemplate.to_dict`
   (`apps/monitoring/app/models.py:232-234`) importiert funktionslokal `builtin_edited` und
   `builtin_update_available` aus `builtin_templates`, das über `template_sync` → `scheduler` → `check_engine` →
   `alerter` den ganzen Dienst zieht; ein Import auf Modulebene wäre ein Zyklus. `cleanup_server` (Server gelöscht:
   Checks, Regeln, Zuweisungen, Schlüssel, Fenster, Fakten) liegt in `template_sync.py:701-743`. Private Namen
   über Modulgrenzen: `routers/agent.py:18` und `alert_bundle.py:149` nehmen `check_engine._dispatch_alert_bg`,
   `routers/agent.py:23` nimmt `core.bounds._find_nul`; `_finite` importiert `routers/agent.py` nach monitoring-io T6
   nicht mehr. Messung (AST, Python 3.13.5, Zugriffe `from app.x import _y` und `<app-Modul>._y` außerhalb des
   definierenden Moduls, Tests ausgenommen): origin/main 16, Endstand 15 (13 in `alert_bundle.py`, 2 in
   `routers/agent.py`).
5. **`Query(regex=…)` ist veraltet (R-0697).** `routers/checks.py:429` (`period`). Probe (FastAPI 0.141.1 und
   0.159.1, dreimal gleich): `regex=` warnt beim Import mit `FastAPIDeprecationWarning: \`regex\` has been
   deprecated, please use \`pattern\` instead`, `pattern=` nicht; das OpenAPI-Schema beider Varianten ist gleich
   (`{"type": "string", "pattern": "^(1h|6h|24h|7d)$", "default": "1h", …}`, so auch in
   `apps/monitoring/tests/openapi.snapshot.json:1444`), ein Wert außerhalb der Liste gibt in beiden 422
   `string_pattern_mismatch`.
6. **Lange Funktionen (R-0728, Monitoring-Teil).** Länge als `end_lineno - lineno + 1` (AST, Python 3.13.5),
   origin/main → Endstand: `agent_report` (`routers/agent.py:74`) 243 → 237, `AgentResourcesChecker.evaluate`
   (`apps/monitoring/app/checkers/agent.py:314`) 215 → 216, `SmartHealthChecker.evaluate`
   (`apps/monitoring/app/checkers/smart.py:87`) 171 → 171, `process_alert` (`alerter.py:90`) 149 → 149,
   `apply_result` (`apps/monitoring/app/check_engine.py:167`) 106 → 106.

## Ziel & Nicht-Ziele

Ziel (ohne Verhaltensänderung außer T2):
- Ein Regel-Pfad und eine Glocken-Logik für Einzel- und Sammelmeldung, öffentliche Namen in `alerter`;
  `alert_bundle.py` greift auf keinen privaten Namen eines anderen Moduls mehr zu (T5, T6, T9).
- Ein Test hält `_REGISTRY`, `CONFIG_MODELS` und `CHECK_TYPE_METRICS` gleich `VALID_CHECK_TYPES`, die
  Teilmengen-Tabellen innerhalb (T3); jeder Push-Checker nimmt `evaluate(config, report, prev_details=None)`, der
  Router braucht keine eigene Liste mehr (T4).
- Scheduler-Jobs ändern sich erst nach einem erfolgreichen Commit, auch beim Löschen (T2).
- `models.py` importiert aus `app` nur `app.core.*`; `cleanup_server` in eigenem Modul; kein privater Name kreuzt
  eine Modulgrenze, ein Test hält das fest (T7–T10).
- `pattern=` statt `regex=` (T1).
- Die fünf genannten Funktionen in benannte Schritte: höchstens 60 Zeilen (`apply_result` 70: Signatur und Docstring haben
  33), keine neue Funktion über 60 (T6, T11–T14).

Nicht-Ziele (YAGNI) und Befunde, die keine Task werden:
- **`agent_types` aus `PUSH_ONLY_TYPES` ableiten (R-0694, Vorschlag der Zeile):** ändert das Verhalten. Die Menge
  heißt „Serien nach `server_id` filtern“, nicht „Push-Typ“: sie enthält `agent_ping` (kein Push-Typ) und lässt
  `smart_health` aus, dessen Serien der Checker mit Check-Labels schreibt und der Endpunkt nach `check_id` liest
  (`routers/checks.py:444-451`; monitoring-io T5). Abgeleitet bekäme `smart_health` den `server_id`-Filter. Sie wird
  eine benannte Modulkonstante und Teil des Paritätstests (T3).
- **Alle Typ-Metadaten in `CHECK_TYPES`:** nicht. Checker-Instanzen, Pydantic-Schemas und PromQL-Namen gehören zu
  ihren Verwendern; der Paritätstest nennt bei einem neuen Typ jede Tabelle, die ihn nicht kennt (Trade-off 2).
- **`validate_check_config` wirft für Typen ohne Schema:** nicht; das änderte Status und Text der Antwort für
  unbekannte Typen (heute 400 „Invalid check_type. Allowed: …“ aus dem Router). Nach T3 hat jeder gültige Typ ein
  Schema, der Durchlass trifft nur noch unbekannte Typen, die der Router abweist.
- **Ein Claim für beide Pfade (R-0693):** nicht. Die Sammelmeldung claimt mehrere Zeilen, verlangt `BUNDLE_MIN` und
  `_awaits_check` und reserviert die Glocke nicht, sondern setzt `hub_status` erst nach angenommenem POST
  (`docs/features/monitoring-alert-quality.md:161-167`, `docs/developer/monitoring.html:255`); `process_alert`
  reserviert im Claim. Das ist gewollt verschieden.
- **Funktionslokale Imports in `scheduler.py:112`, `:149`, `:194` und `alert_bundle.py:239`:** bleiben. `:194`
  (`tag_sync`) und `alert_bundle.py:239` (`scheduler`) wären echte Zyklen (`scheduler` → `tag_sync` →
  `template_sync` → `scheduler`, `scheduler` → `alert_bundle` → `scheduler`); `:112`/`:149` lesen `SessionLocal`
  zur Laufzeit, die Patch-Stelle, die `check_engine.py:53-57` beschreibt.
- **`HttpChecker.run` (117 Zeilen) und `execute_check` (110):** wuchsen durch monitoring-io T1/T10 über 100, stehen
  nicht in R-0728 (offene Frage 1).
- Keine Route, kein Schema, keine Migration, keine neue Abhängigkeit, kein Umbau der Checker-Dateien
  (`checkers/agent.py` bleibt eine Datei).

## Betroffene Komponenten & Dateien

Alles Komponente `monitoring` (verify.sh), Pfade unter `apps/monitoring/` außer Doku und CHANGELOG.

| Task | Zeile | Dateien |
|---|---|---|
| T1 | R-0697 | `app/routers/checks.py`, `tests/test_checks_metrics.py` |
| T2 | R-0695 | `app/routers/checks.py`, `app/routers/templates.py`, `tests/test_scheduler_after_commit.py` (neu), `CHANGELOG.md` |
| T3 | R-0694 | `app/check_types.py`, `app/routers/checks.py`, `tests/test_check_type_parity.py` (neu) |
| T4 | R-0694 | `app/checkers/__init__.py`, `app/checkers/plugins.py`, `app/checkers/smart.py`, `app/checkers/system.py`, `app/routers/agent.py`, `tests/test_check_type_parity.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` |
| T5 | R-0693 | `app/alerter.py`, `app/alert_bundle.py` |
| T6 | R-0693, R-0728 | `app/alerter.py`, `app/alert_bundle.py`, `tests/test_alerter.py`, `tests/test_check_engine_concurrency.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` |
| T7 | R-0696 | `app/models.py`, `app/routers/templates.py`, `tests/test_alert_secrets.py`, `tests/test_module_boundaries.py` (neu) |
| T8 | R-0696 | `app/server_cleanup.py` (neu), `app/template_sync.py`, `app/routers/admin.py`, `tests/test_template_sync.py`, `tests/test_template_suggestions.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` |
| T9 | R-0696 | `app/check_engine.py`, `app/routers/agent.py`, `app/alert_bundle.py`, `tests/test_architecture_transitions.py`, `tests/test_check_engine.py`, `tests/test_check_engine_concurrency.py`, `tests/test_service_process_checker.py`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` |
| T10 | R-0696 | `app/core/bounds.py`, `app/routers/agent.py`, `tests/test_module_boundaries.py` |
| T11 | R-0728 | `app/routers/agent.py` |
| T12 | R-0728 | `app/checkers/agent.py` |
| T13 | R-0728 | `app/checkers/smart.py` |
| T14 | R-0728 | `app/check_engine.py` |

Risikopfade (`scripts/dev/review-risk.txt`): `alerter.py` (T5, T6), `routers/agent.py` (T4, T9, T10, T11),
`check_engine.py` (T9, T14) — dort zusätzlich `security`. T4, T6, T8 und T9 sind über mehr als drei Dateien, weil sie
Namen umbenennen bzw. Signaturen angleichen; die Änderung je Datei ist mechanisch.

## Datenmodell / API / Migrationen

Keine Migration, keine Tabelle, keine Route, kein Request- oder Response-Schema. `tests/test_openapi_snapshot.py`
bleibt grün (T1: gleiches Schema laut Probe; kein Docstring einer Route ändert sich). Die Template-Antworten (T7)
behalten Schlüssel, Werte und Reihenfolge, nur berechnet der Router die zwei Built-in-Flags. Kein Vertrags-Drift zu
Server, Desktop oder Agent: alle Namen, die sich ändern, sind Python-intern.

## Externe Integrationen

- FastAPI `Query(pattern=…)`: offizielle Doku „Query Parameters and String Validations“
  (fastapi.tiangolo.com/tutorial/query-params-str-validations/, gelesen 2026-10-22): „You can define a regular
  expression `pattern` that the parameter should match“; `regex` nennt die Seite nicht mehr. Die Veraltung von `regex`
  belegt die Warnung der Probe (Problem 5). `apps/monitoring/requirements.txt` pinnt FastAPI 0.138.0, die Venvs haben
  0.141.1 und 0.159.1; `pattern` gibt es seit der Pydantic-2-Umstellung von FastAPI (vor 0.138, nicht eigens geprüft).
- Sonst keine (APScheduler, SQLAlchemy und VictoriaMetrics werden nicht anders benutzt).

## Trade-offs & Alternativen

1. **Öffentliche API in `alerter` (T5, T6).** (a) Kleine öffentliche Schritte, die beide Pfade rufen —
   `enabled_rules`, `rule_applies`, `send_to_rule`, `reported_status`, `bell_severity`, `bell_record`,
   `capped_label`, `highest_severity`; `build_message`, `emit_to_hub`, `post_hub_event` umbenannt — **Empfehlung**:
   die Pfade behalten ihre Form (eine Nachricht je Regel und Check gegen eine Sammelnachricht je Regel), nur die
   Schritte gibt es einmal. Die privaten Blätter, die Tests patchen (`_dispatch`, `_is_in_cooldown`,
   `_rule_matches`), bleiben privat und werden über den Modulnamen gefunden, die Patches greifen weiter.
   (b) Ein neues Modul `alert_protocol.py`: verschiebt mehr Code und alle Patch-Stellen der Tests, ohne eine Kopie
   weniger. (c) `alert_bundle` ruft `process_alert` je Mitglied: verlöre die Sammelnachricht.
   Der Log-Text für einen gescheiterten Versand wird einer („Alert dispatch failed for rule %s“, englisch wie jeder
   neue Text); der Grund im Alert-Log (`Dispatch failed (<Typ>)`) bleibt gleich und ist gepinnt
   (`tests/test_alerter.py:431`, `tests/test_alert_bundle.py:381`).
2. **Typ-Tabellen (T3).** (a) Paritätstest, Tabellen bleiben bei ihren Verwendern — **Empfehlung**: kein Umbau,
   ein neuer Typ ohne Eintrag macht den Test rot und nennt die Tabelle. (b) Eine Metadaten-Tabelle mit Checker,
   Schema und Metriken: `check_types` müsste Checker und Schemas importieren und wäre nicht mehr neutral; die
   Router-Mengen blieben Router-Wissen.
3. **`prev_details` (T4).** (a) Jeder Push-Checker nimmt `prev_details=None`, der Router liest die vorigen
   `_details` für jeden Push-Check — **Empfehlung**: die Liste im Router entfällt, das Protocol sagt, was ein
   Push-Checker kann. Kosten: ein `json.loads` von `state.details` mehr je Push-Check der vier Typen, die es nicht
   lesen (gekappte Listen, siehe monitoring-ref-2). (b) Ein Klassenattribut `uses_prev_details`: der Router verzweigte
   weiter, nur mit anderer Quelle.
4. **Scheduler nach dem Commit (T2).** (a) Löschen: erst Commit, dann `remove_check` mit der ID aus dem Pfad bzw. den
   vorher gemerkten IDs; die drei gleichen Blöcke über einen Helfer im Checks-Router — **Empfehlung**: der Helfer ruft
   die im Router importierten `add_check`/`remove_check`, die Patches der Tests (`app.routers.checks.add_check`,
   z. B. `tests/test_templates_router.py:61`, `:292`) greifen weiter. (b) Alles über
   `template_sync.apply_scheduler_actions`: umginge diese Patches, ein Test zählte dann ins Leere.
5. **Template-Antwort (T7).** (a) `MonitorTemplate.to_dict(…, *, builtin_edited, builtin_update_available)` als
   Pflicht-Schlüsselwörter, der Router rechnet sie über einen Helfer aus — **Empfehlung**: das Modell serialisiert
   übergebene Fakten, die Reihenfolge der Schlüssel bleibt, ein vergessener Aufrufer scheitert laut. (b) `to_dict`
   ohne die Flags, der Router fügt sie an: ändert die Reihenfolge der JSON-Schlüssel. (c) Ein Default `False`: ein
   vergessener Aufrufer meldete still „nicht bearbeitet“.
6. **Wächter gegen private Namen (T10).** Ein AST-Test über `app/` wie `tests/test_architecture_transitions.py`
   statt einer ruff-Regel (ruff hat dafür keine Regel im gepinnten Satz, `ruff.toml` wählt nur Default + `I`).

## Risiken & Rollback

- Der Alarm-Pfad (T5, T6) ist der heikelste Teil: ein vertauschter Schritt meldet doppelt oder gar nicht. Abhilfe:
  die bestehenden Suiten beider Pfade (`test_alerter*.py`, `test_alert_bundle.py`, die Postgres-Tests in
  `test_check_engine_concurrency.py` in der PR-CI) vor und nach dem Diff grün, dazu je Task eine
  Mutations-Stichprobe; `security` prüft mit. Die Reihenfolge Regeln lesen → Claim-Commit → Nachricht → Versand →
  Flush → Glocke bleibt (`process_alert` liest die Regeln heute vor dem Claim-Commit, `alerter.py:149`).
- T2 ist die einzige Verhaltensänderung: scheitert der Commit, bleibt der Job; gelingt er, ist der Job danach weg wie
  bisher. Zwischen Commit und `remove_check` kann der Job noch einmal feuern; `execute_check` findet den gelöschten
  Check nicht und kehrt zurück (Anfang von `execute_check`: Abfrage mit `enabled`, ohne Treffer `return`).
- Umbenennungen (T6, T9, T10) treffen Patch-Ziele der Tests; ein vergessenes Ziel lässt `monkeypatch.setattr`
  laut scheitern (Default `raising=True`), nicht still grün.
- Rollback: jede Task ist ein Commit; Revert einzeln, in umgekehrter Reihenfolge, wo eine Task auf der vorigen
  aufbaut (T4 → T3, T6 → T5, T10 → T5/T6/T7/T9).

## Doku-Impact

Entwickler-Doku DE+EN (`docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`), weil sie interne
Namen nennt: `_PREV_DETAILS_TYPES` (`:188`, T4), `_emit_to_hub` (`:247`), `_post_hub_event` (`:253`) und `_dispatch`
in der Sammelmeldung (`:255`, T6), `_dispatch_alert_bg` (`:255`, T9), die Modulübersicht (`:62-79`, T8). CHANGELOG nur
für T2 (Fixed). Sonst keine; Admin-Doku und README beschreiben nichts, was sich ändert.

## Offene Fragen

1. `HttpChecker.run` (117 Zeilen) und `execute_check` (110) liegen nach monitoring-io über 100, R-0728 nennt sie
   nicht. Empfehlung: eine neue REF-Zeile (`neu`), nicht in dieses Paket — das Paket hat 14 Tasks, und beide
   Funktionen sind gerade erst umgebaut; ein Schnitt jetzt mischte sich mit Funden aus deren Review.
2. Keine Frage aus Kevins Bereich: keine Route, kein Schema, keine Migration; die eine Verhaltensänderung (T2) legt
   die Roadmap-Zeile fest.
