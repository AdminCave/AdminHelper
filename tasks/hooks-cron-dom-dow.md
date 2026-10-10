<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hooks: Tag-im-Monat und Wochentag bleiben mit UND verknüpft — Task-Ledger
Status: geplant · Branch: feature/hooks-cron-dom-dow · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0274 (Kurz-Ledger ohne Spec)
Heavy: none — kein Code; ein Test hält das bestehende Verhalten des Parsers fest, dazu Doku. Kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-10
triagiert hat. Sie stammt aus dem Opus-Review von R-0249. Kevin hat am 2026-10-10 vorab entschieden, nach der
Vorabmeldung mit dem Gegenfall „erster Montag“: Option (b), UND behalten und als bewusste Abweichung vom Standard-Cron
dokumentieren. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@7573443a.

### T1 — Doku und Test: Tag-im-Monat und Wochentag müssen beide passen, abweichend vom Standard-Cron (R-0274)  [ ]
Komponente: server · Dateien: apps/server/tests/test_scheduler_cron.py, docs/developer/server.html, docs/en/developer/server.html, CHANGELOG.md
Änderung: APScheduler 3.x verknüpft im `CronTrigger` Tag-im-Monat und Wochentag mit UND. Standard-Cron verknüpft sie
mit ODER, sobald keines der beiden Felder mit `*` beginnt (Vixie-Cron, `cron.c` `find_jobs`: `(e->flags &
(DOM_STAR|DOW_STAR)) != 0 ? (thisdom && thisdow) : (thisdom || thisdow)`; `entry.c` setzt die Flags, wenn das Feld mit
`*` beginnt). Kevin hat entschieden: UND bleibt.
- Mit UND lässt sich „erster Montag im Monat“ ausdrücken (`0 9 1-7 * mon`), was Standard-Cron nicht kann.
- Kein gespeicherter Hook ändert seine Laufzeiten.
- Mit ODER liefe derselbe Hook an jedem 1. bis 7. und an jedem Montag.

Test in `tests/test_scheduler_cron.py`, mit `_parse_trigger` ab dem festen Freitag (`START`), die nächsten drei
Läufe als Daten:
- `0 9 1-7 * mon` → Mo 02.11.2026, Mo 07.12.2026, Mo 04.01.2027 (je der erste Montag).
- `0 9 15 * mon` → Mo 15.02.2027, Mo 15.03.2027, Mo 15.11.2027 (nur Montage am 15.).
- Der Test ist auf HEAD grün: Er hält das Verhalten fest, das bleiben soll; einen Fehler zeigt er nicht. Ein späterer
  Wechsel auf ODER (OrTrigger) macht ihn rot.

Doku `server.html:157` DE und EN, hinter dem Satz zur Zählung des Wochentags: „Abweichend vom Standard-Cron müssen
Tag-im-Monat und Wochentag beide passen, wenn beide gesetzt sind: `0 9 1-7 * mon` läuft am ersten Montag des Monats,
`0 9 15 * mon` nur an einem Montag, der auf den 15. fällt.“

CHANGELOG: kein eigener Eintrag, denn das Verhalten bleibt. Aber der Eintrag von R-0249 unter `### Changed` (`CHANGELOG.md:562`) sagt „Jetzt
gilt Standard-Cron“. Er bekommt einen Halbsatz: Tag-im-Monat und Wochentag bleiben mit UND verknüpft (R-0274). Sonst
verspräche er mehr, als gilt.
Beweis: APScheduler 3.11.3 im Server-Venv, ohne Repo-Import, nächste Läufe ab Fr 09.10.2026 12:00 UTC:
- `CronTrigger.from_crontab('0 9 15 * mon')` → Mon 15.02.2027, Mon 15.03.2027, Mon 15.11.2027.
- `'0 9 1-7 * mon'` → Mon 02.11., Mon 07.12., Mon 04.01., Mon 01.02., Mon 01.03., Mon 05.04.
- Gegenprobe `OrTrigger([CronTrigger(day='1-7', …), CronTrigger(day_of_week='mon', …)])` → Mon 12.10., Mon 19.10.,
  Mon 26.10., Sun 01.11., Mon 02.11., Tue 03.11., …
Dedup-Key: bug:server:hooks/scheduler.py:dom-dow-and
HEAD: 7573443a
Semantik: keine Stelle in docs/ sagt, wie Tag-im-Monat und Wochentag zusammenwirken (gesucht in
`docs/developer/server.html`, `docs/developer/hooks.html`, `docs/developer/api-reference.html`). `server.html:157` nennt
seit R-0249 die Zählung des Wochentags nach Standard-Cron. Kevins Entscheidung (b) legt das Verhalten fest.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_scheduler_cron.py
Doku: docs/developer/server.html + docs/en/developer/server.html · CHANGELOG.md (Halbsatz im Eintrag von R-0249)
