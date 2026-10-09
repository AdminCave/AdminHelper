<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hooks: Cron-Intervalle wirklich prüfen, kein stilles Überspringen — Task-Ledger
Status: aktiv · Branch: feature/hooks-cron-fields · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0235, von Kevin am 2026-10-09 in der Triage angenommen; Delegation Kevin 2026-10-05). Offene Fragen (Aufsicht): 1 Weg (a), eine Warnung je Hook und Intervall, keine Datenaenderung; 2 Heavy linux-full
Spec: Roadmap R-0235 (Kurz-Ledger ohne Spec)
Heavy: linux-full — die Server-API lehnt kuenftig mehr Eingaben ab (Aufsicht 2026-10-09: Server-API-Pfad laut Heavy-Regel); run.sh integration auf einer Pool-VM
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-09
triagiert und angenommen hat. Sie stammt aus dem Gesamt-Review von Server-Kleinpaket-2 (R-0207). Die private Roadmap
ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@bf383a7a.

### T1 — Hook-Routen: ein Intervall, das der Scheduler nicht lesen kann, ist ein 422 (R-0235)  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/test_hooks.py, CHANGELOG.md
Änderung: `_validate_schedule_interval` (`router.py:89-99`) prüft nur, ob ein Intervall ein bekannter Alias ist oder
aus fünf Feldern besteht. `"a b c d e"` und `"61 * * * *"` kommen deshalb mit 201 durch. Der Scheduler liest dieselben
Werte mit `_parse_trigger` (`scheduler.py:44-53`, `CronTrigger.from_crontab`) und scheitert mit `ValueError`.
- Die Prüfung läuft künftig über `_parse_trigger` selbst. Ein `ValueError` wird zum 422 mit `loc =
  ("body", "schedule_interval")` und dem bisherigen Text, wie R-0207 es eingeführt hat.
- Prüfung und Ausführung haben damit eine Regel. Das gilt für POST (`:122`) und PUT (`:277`).
- Der Docstring (`:90-92`) nennt noch den alten Weg „add_hook -> _parse_trigger“; die Hooks registriert seit dem
  Scheduler-Prozess der Abgleich. Er beschreibt künftig, was gilt.

Tests in `test_hooks.py`, neue Fälle neben `test_invalid_create_answers_in_the_promised_format` und
`test_invalid_update_answers_in_the_promised_format` (`:170`, `:191`):
- `"a b c d e"` und `"61 * * * *"` ergeben bei POST und PUT ein 422 mit `loc` `schedule_interval`;
- `"*/5 * * * *"` bleibt 201.
Rot vor dem Fix.
CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis: origin/main@bf383a7a, im Server-Venv mit dem devenv: `CronTrigger.from_crontab("a b c d e")` →
`ValueError: Invalid month name "d"`; `"61 * * * *"` → `ValueError: … the last value (61) is higher than the maximum
value (59)`. Beide bestehen die Fünf-Felder-Prüfung von `router.py:93-94`, `"*/5 * * * *"` parst.
HEAD: bf383a7a
Semantik: `docs/developer/server.html:157`: „Trigger-Typen: vordefinierte Intervalle (1m, 5m, 15m, 30m, 1h, 6h, 12h,
24h) oder Cron (5 Felder).“ EN `docs/en/developer/server.html:157`: „Trigger types: predefined intervals (…) or cron
(5 fields).“ Fünf beliebige Wörter sind kein Cron.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: CHANGELOG.md (Fixed); server.html beschreibt die Regel schon

### T2 — Scheduler: ein gespeichertes Intervall, das nicht parst, wird gemeldet statt still übersprungen (R-0235)  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/scheduler.py, apps/server/tests/test_scheduler_reconcile.py, CHANGELOG.md
Änderung: `reconcile_scheduled_hooks` fängt den `ValueError` von `add_hook` und macht `continue` (`scheduler.py:149`).
Ein Hook, der vor T1 mit einem solchen Intervall gespeichert wurde, läuft deshalb nie, und niemand erfährt es.
- Der Plan folgt der Empfehlung zu offener Frage 1, Weg (a).
- Der Abgleich schreibt dann eine Warnung ins Log, mit der Hook-ID und dem Intervall.
- Sie erscheint einmal je Hook und Intervall im Scheduler-Prozess, denn der Abgleich läuft alle 30 Sekunden.
- Der Hook bleibt, wie er ist: kein Job, keine Datenänderung.
- Ändert jemand das Intervall auf ein gültiges, wird der Hook wieder registriert, wie heute.

Tests in `test_scheduler_reconcile.py`:
- Ein direkt in die DB geschriebener Hook mit `"a b c d e"` bekommt keinen Job und genau eine Warnung, auch über zwei
  Abgleiche.
- Ein gültiger Hook daneben wird registriert.
Rot vor dem Fix (keine Warnung).
Beweis: origin/main@bf383a7a `sed -n 145,150p apps/server/app/modules/hooks/scheduler.py` → `except ValueError:
continue` ohne Log; `logger` gibt es im Modul (`:18`).
HEAD: bf383a7a
Semantik: wie T1. Ein Hook, der laut API als Scheduled Hook existiert, aber nie läuft, ist kein beschriebenes
Verhalten; keine Stelle in docs/ sagt, was mit einem unlesbaren gespeicherten Intervall geschieht (gesucht in
`server.html`, `hooks.html`, `api-reference.html`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_scheduler_reconcile.py
Doku: CHANGELOG.md (der Eintrag aus T1 bekommt den Satz zur Warnung)
Abhängt von: T1
