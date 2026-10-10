<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hooks: Cron-Wochentage nach Standard-Cron — Task-Ledger
Status: bereit · Branch: feature/hooks-cron-weekday · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-10-10 (im Chat mit der Aufsicht; sichtbares Verhalten). Offene Fragen (Kevin): 1 Altbestand unveraendert nach Standard-Cron umdeuten (a); 2 die Abfrage nach betroffenen Hooks steht im CHANGELOG-Eintrag; T2 Web-Hilfe ja
Spec: Roadmap R-0249 (Kurz-Ledger ohne Spec)
Heavy: linux-full — der Scheduler-Prozess des Stacks liest jeden gespeicherten Schedule-Hook beim Abgleich mit dem geänderten Parser, und die Routen prüfen mit demselben Parser; auf einer Pool-VM `run.sh integration`.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, svelte-check und ESLint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin am 2026-10-09
triagiert hat („Fix auf Standard-Cron, sichtbare Verschiebung am Plan-Gate zeigen“). Sie stammt aus dem Opus-Review
von R-0235 (feature/hooks-cron-fields@c59258c3). Die private Roadmap ist in diesem Worktree nicht lesbar; der
Zeileninhalt kommt von der Aufsicht. Zeilenangaben origin/main@7600dc25. Die Freigabe gibt Kevin: Bestehende Hooks
mit Ziffern im Wochentag laufen danach an einem anderen Tag (CLAUDE.md §2, Entscheidung 3).

Was sich für gespeicherte Hooks verschiebt (Weg (a) der offenen Frage 1). Die Spalte „bisher“ ist die Probe unten,
die Spalte „danach“ ist Standard-Cron:

| Wochentag-Feld | bisher (APScheduler 3.x) | danach (Standard-Cron) |
|---|---|---|
| `0` | Mo | So |
| `1` | Di | Mo |
| `6` | So | Sa |
| `1-5` | Di–Sa | Mo–Fr |
| `0,6` | Mo, So | Sa, So |
| `*/2` | Mo, Mi, Fr, So | So, Di, Do, Sa |
| `7` | seit R-0235 422; ein älterer Hook läuft nie und steht als Warnung im Log | So |
| `mon-fri`, `sun`, `*` | unverändert | unverändert |
| `1/2`, `mon/2`, `mon-fri/2` (Schritt auf Einzelzahl oder Name) | liefen: `1/2` Di, Do, Sa; `mon/2` Mo; `mon-fri/2` Mo–Fr (Schritt ignoriert) | abgelehnt wie in Vixie-Cron: 422; ein gespeicherter Hook läuft erst nach einer Korrektur wieder, Warnung im Log (T3) |

### T1 — Scheduler: das Wochentag-Feld eines Cron-Ausdrucks gilt nach Standard-Cron (R-0249)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/scheduler.py, apps/server/tests/test_scheduler_cron.py, apps/server/tests/test_hooks.py, docs/developer/server.html, docs/en/developer/server.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @fd358c62 2026-10-10T04:27:48+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `_parse_trigger` (`scheduler.py:44-53`) gibt einen Ausdruck aus fünf Feldern unverändert an
`CronTrigger.from_crontab` (`:50`). APScheduler 3.x zählt den Wochentag dort ab Montag; Standard-Cron zählt 0 und 7 als
Sonntag, 1 als Montag. Jeder Wochentag in Ziffern liegt deshalb einen Tag daneben, `7` ist ungültig. Die Routen prüfen
seit R-0235 mit demselben Parser (`router.py:89-99`), der Abgleich registriert mit ihm.

Der Plan folgt der Empfehlung zu offener Frage 1, Weg (a), und Kevins Triage: Das Feld gilt künftig nach Standard-Cron.
- Ein neuer Helfer in `scheduler.py` übersetzt das fünfte Feld vor `from_crontab`:
  - Ziffern, Bereiche, Listen und Schritte (`0`, `1-5`, `0,6`, `*/2`, `1-5/2`) werden zur Menge der gemeinten Tage
    (0 und 7 = Sonntag) und als Namensliste weitergegeben, etwa `1-5` → `mon,tue,wed,thu,fri`.
  - Namen (`mon-fri`, `sun`) und `*` bleiben, wie sie sind; APScheduler liest sie schon richtig.
  - Eine Namensliste, keine Bereiche, weil APScheduler einen Bereich über das Wochenende ablehnt (`sun-sat`, Probe).
  - Werte über 7, umgekehrte Bereiche (`5-1`) und gemischte Teile (`1-fri`) sind ein `ValueError`. An den Routen wird
    daraus der 422 aus R-0235, im Abgleich die Warnung aus R-0235.
- Die übrigen vier Felder und die Intervall-Aliase ändern sich nicht.
- Gespeicherte Ausdrücke bleiben in der Datenbank, wie sie sind (Weg (a)). Den neuen Zeitpunkt schreibt der nächste
  Abgleich nach `next_run`, spätestens nach 30 Sekunden.

Tests, neue Datei `tests/test_scheduler_cron.py` (SPDX-Header). `_parse_trigger` wird ab einem festen Freitag (UTC)
gefragt, an welchen Tagen der Hook läuft:
- `0 9 * * 0` und `0 9 * * 7` laufen sonntags, `0 9 * * 1` montags.
- `0 9 * * 1-5` läuft Mo–Fr, `0 9 * * 0,6` Sa und So, `0 9 * * */2` So, Di, Do, Sa.
- `0 9 * * mon-fri` und `0 9 * * *` bleiben, wie sie sind.
- `0 9 * * 8`, `0 9 * * 5-1` und `0 9 * * 1-fri` sind ein `ValueError`.
- Rot vor dem Fix bis auf die unveränderten Fälle.

In `test_hooks.py` neben `test_a_valid_cron_is_accepted` (`:229`): `0 0 * * 7` ergibt bei POST 201 (heute 422).
`test_a_cron_the_scheduler_cannot_read_is_422` (`:205`) bekommt `0 9 * * 8` als weiteren Fall.

Doku: `server.html:157` DE und EN, Satz „Trigger-Typen: … oder Cron (5 Felder)“: Der Wochentag zählt wie im
Standard-Cron (0 und 7 = Sonntag, 1 = Montag), Namen (`mon`–`sun`) gehen auch. CHANGELOG unter `[Unreleased]` →
`### Changed`, mit dem Hinweis auf die Verschiebung:
- Schedule-Hooks mit Ziffern im Wochentag laufen ab diesem Stand einen Tag früher als bisher, am im Cron gemeinten Tag.
- Hooks mit `7` laufen ab dann sonntags.
- Die Abfrage, die die betroffenen Hooks findet, steht dabei (offene Frage 2).

Beweis: APScheduler 3.11.3 im Server-Venv, ohne Repo-Import. `CronTrigger.from_crontab(expr, timezone="UTC")`, nächste
Läufe ab Fr 09.10.2026 12:00 UTC:
- `'0 9 * * 0'` → Mon 12.10., Mon 19.10., …
- `'0 9 * * 1'` → Tue 13.10., …
- `'0 9 * * 1-5'` → Sat 10.10., Tue 13.10., Wed 14.10., Thu 15.10., Fri 16.10.
- `'0 9 * * 6'` → Sun 11.10., …
- `'0 0 * * 7'` → `ValueError: Error validating expression '7': the last value (7) is higher than the maximum value (6)`
- `'0 0 * * sun-sat'` → `ValueError: The minimum value in a range must not be higher than the maximum`
- `'0 9 * * mon-fri'` → Mon–Fri, `'0 9 * * sun,sat'` → Sat, Sun.

Das Lockfile nennt `apscheduler==3.11.2` (`requirements.txt:26`), das Venv der Dev-Box hat 3.11.3. In beiden
Fassungen gibt `from_crontab` das fünfte Feld unverändert als `day_of_week` weiter; geprüft am Wheel von 3.11.2 von
PyPI. Erst der Docstring von 3.11.3 und die Doku der 3.x-Reihe
(apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html) sagen es ausdrücklich: „Due to a historical mistake,
there is a mismatch between weekday numbers, as APScheduler treats 0 as Monday while the original crontab treats it as
Sunday. This has been rectified in the v4.x series but cannot be changed in the 3.x series due to backwards
compatibility.“
Dedup-Key: bug:server:hooks/scheduler.py:cron-dow-zero
HEAD: 7600dc25
Semantik: `docs/developer/server.html:157`: „Trigger-Typen: vordefinierte Intervalle (1m, 5m, 15m, 30m, 1h, 6h, 12h,
24h) oder Cron (5 Felder).“ Die Hilfe im Hook-Dialog des Web-Panels sagt „Format: Minute Stunde Tag Monat Wochentag“
(`apps/web/src/lib/i18n/dictionaries.ts:181`). Beide versprechen Cron ohne Abweichung beim Wochentag; keine Stelle in
docs/ nennt die Zählung von APScheduler.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_scheduler_cron.py tests/test_hooks.py tests/test_scheduler_reconcile.py
Doku: docs/developer/server.html + docs/en/developer/server.html (Trigger-Typen) · CHANGELOG.md (Changed, mit Hinweis auf die Verschiebung)

### T2 — Web-Panel: die Cron-Hilfe im Hook-Dialog nennt die Zählung des Wochentags (R-0249)  [x]
Komponente: web · Dateien: apps/web/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @cf6142f1 2026-10-10T04:28:50+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Die Hilfe unter dem Cron-Feld (`HookModal.svelte:181`, Schlüssel `modal.hook.cronFormat`,
`dictionaries.ts:181` DE und `:410` EN) bekommt den Zusatz „(Wochentag: 0 und 7 = Sonntag, 1 = Montag)“ bzw.
„(weekday: 0 and 7 = Sunday, 1 = Monday)“. Dort tippt man die Ziffern; nach T1 stimmt die Angabe. Kein Test: ein
Übersetzungstext ohne Logik (CLAUDE.md §6, triviales Wiring); `npm run check` und Lint laufen im Verify.
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (der Text ist die Hilfe selbst; server.html kommt mit T1)
Abhängt von: T1

### T3 — Nachbesserung aus dem Review am Ende: Stillstand bei Schritt auf Einzelzahl oder Name benennen (R-0249)  [x]
Komponente: server · Dateien: CHANGELOG.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @dfc73527 2026-10-10T05:11:50+02:00
Review: Review am Ende (Kurz-Ledger, Opus), Runde 2 über die Nachbesserung
Änderung: Angelegt 2026-10-10 aus dem Review am Ende (Opus, request_changes, ein belegtes `wichtig`). Kevin hat über
die Aufsicht entschieden: ablehnen und klar benennen, nur Doku, kein Code.
- `wichtig`: Ein Schritt auf einer Einzelzahl oder einem Namen lief bisher und wird seit T1 abgelehnt, wie in
  Vixie-Cron. APScheduler 3.x las `1/2` als Bereich bis zum Ende seiner Woche (Di, Do, Sa), `mon-fri/2` als `mon-fri`
  und `mon/2` als `mon`; der Schritt fiel still weg. Ein gespeicherter Hook damit läuft erst nach einer Korrektur
  wieder, mit der Warnung aus R-0235 im Scheduler-Log; ein PUT gibt 422. Der CHANGELOG-Eintrag aus T1 nannte das
  nicht. Er bekommt den Satz, die Tabelle im Ledger-Kopf eine Zeile.
- nit: „einen Tag früher als bisher“ stimmt bei gemischten Listen nur für den Ziffernteil. `mon,0` lief bisher nur
  montags und läuft danach So und Mo. Der Satz heißt künftig: die Ziffern meinen jetzt den Tag davor.

Beweis: feature/hooks-cron-weekday@e27f4462, APScheduler 3.11.3 direkt ab Fr 09.10.2026: `'0 9 * * 1/2'` → Tue, Thu,
Sat; `'0 9 * * mon-fri/2'` → Mon–Fri; `'0 9 * * mon/2'` → Mon. `_parse_trigger` auf demselben Stand: alle drei
`ValueError: invalid weekday …`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_scheduler_cron.py
Doku: CHANGELOG.md (Changed, der Eintrag aus T1)
