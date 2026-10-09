<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Kleinpaket 1: Kostenquelle, Zeilengrenzen, lane_db geschlossen (R-0250, R-0251, R-0255) — Task-Ledger
Status: bereit · Branch: harness/loop-kleinpaket-1 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (Harness-Kleinpaket aus R-0250, R-0251 und R-0255, von Kevin am 2026-10-09 in der Triage angenommen; Delegation Kevin 2026-10-05; den PR merged Kevin). Offene Fragen (Aufsicht): 1 die Kostendatei; 2 der Satz in DEVELOPMENT.md ja, keine Normalisierung von postgres:// in lane.sh
Spec: Roadmap R-0250, R-0251, R-0255 (Kurz-Ledger ohne Spec)
Heavy: none — Shell und Python unter scripts/dev mit hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-09 in der
Triage als Harness-Futter angenommen (Pakete zu höchstens drei). Alle drei sind Funde aus dem Bau 4b
(harness/team-4b-loop-profile@591afaa0). Zeilenangaben main@6ca2f3a2; beim Bau an Symbolen orientieren.

Entwurf:
- R-0250: Heute nimmt der Loop die Reviewer-Kosten als letzte passende Zeile aus `$CLOSE`, der stdout von
  task-close. Diese stdout erben auch die Suite und alles, was sie startet. Künftig schreibt task-close die Kosten
  zusätzlich in eine Datei, deren Pfad der Loop mit `--cost-file` mitgibt; sie liegt im Loop-Verzeichnis, nicht in
  der Lane. Der Loop liest die Kosten nur dort. Kein Prozess der Suite hat einen Deskriptor auf diese Datei. Wer ihren
  Pfad kennt, kann sie unter derselben UID trotzdem schreiben; das ist die bekannte Klasse „keine harte Grenze“.
  Die Zeile im Close-Log bleibt für den Menschen.
- R-0251: `ledger_rest` trennt Zeilen nur an `\n`, wie sed und awk des Loops (`next_task`, `task_box`).
- R-0255: `lane.sh lane_db` bricht ab, wenn nach dem Zerlegen noch `user:password@` in der URL steht. Weder
  createdb noch dropdb laufen, und die Meldung nennt den Wert nicht. So hält es schon `builder-home.sh` `pg`.

### T1 — Die Reviewer-Kosten kommen aus einer Datei des Loops, nicht aus der letzten Zeile des Close-Logs (R-0250)  [x]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/dev/ledger-loop.sh, scripts/tests/task_close_test.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0ed0578e 2026-10-09T20:27:18+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `task-close.sh` nimmt `--cost-file <pfad>`. Nach einem Reviewer-Lauf mit Verdict (`:432`) schreibt es dieselbe Zeile
  `review cost_usd=<x|unknown> round=<n>` auch in diese Datei: neu angelegt bzw. abgeschnitten. Ohne das Flag
  verhält es sich wie heute.
- `close_task` (`ledger-loop.sh:851`) entfernt die Datei `$LOOP/<slug>/<id>.cost.r<round>.<n>.<try>` vor dem Close,
  gibt ihren Pfad mit und liest die Kosten nur von dort, nicht mehr aus `$CLOSE` (`:874`).
- Die Deckel-Regeln bleiben: kein brauchbares Verdict, `unknown`, oder eine Runde mit `raw.json` ohne Kostendatei
  zählen mit `REVIEW_BUDGET_MAX`.
- Der Kopfkommentar von ledger-loop.sh (`:80`) sagt, woher die Kosten kommen.
Tests:
- `task_close_test.sh`:
  - Mit `--cost-file` steht genau die Kostenzeile in der Datei.
  - Ohne das Flag entsteht keine Datei.
  - Bei Exit 74 vor dem Reviewer entsteht keine Datei.
- `ledger_loop_test.sh`:
  - Die Fake-Close schreibt die Kosten in die Datei und danach eine fremde Zeile `review cost_usd=0 round=<n>` ins Log,
    wie ein Prozess der Suite. Der Loop zählt den Wert aus der Datei.
  - Die bestehenden Fälle (`ruk`, `rvz`, `rrw`, `rnr`, `rca`, `74r`) behalten ihre erwarteten Werte. Die Fake-Close
    schreibt dafür die Datei so, wie es task-close dann tut.
Rot vorher: Der Loop zählt die späte Zeile mit 0 $.
Beweis: main@6ca2f3a2 · Code-Lesung:
- `task-close.sh:311`/`:315` fährt die Suite, also Code der Session, mit der stdout, die der Loop nach `$CLOSE` lenkt
  (`ledger-loop.sh:860`).
- Ein Prozess, den die Suite hinterlässt, erbt diese stdout. `reap_session` beendet ihn erst nach dem Close (`:862`).
- `:874` nimmt die letzte passende Zeile: `printf 'review cost_usd=0.4 round=1\nreview cost_usd=0 round=1\n' | sed -nE 's/^review cost_usd=([0-9][0-9.]*|unknown) round=[12]$/\1/p' | tail -n 1` ergibt `0`.
Dedup-Key: ref:scripts:ledger-loop.sh:cost-line-source
HEAD: 6ca2f3a2
Semantik: `AUTONOMOUS.md:263–264` „`--max-budget-usd 200` (Bau-Sessions **und** Reviewer, im Loop selbst gezählt;
unbekannte Kosten zählen mit ihrem Deckel)“. Gezählt wird, was der Reviewer gekostet hat, nicht was zuletzt im Log
steht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Kopf von ledger-loop.sh)

### T2 — `ledger_rest` trennt nur an `\n` (R-0251)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4717d016 2026-10-09T20:43:59+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `ledger_rest` (`ledger-loop.sh:612`) zerlegt den Text mit `re.split(r"(?<=\n)", text)` statt mit `splitlines(True)`.
  So endet eine Zeile dort, wo sie auch für sed und awk des Loops endet (`next_task`, `task_box`).
- `ledger_commit` braucht keine Änderung: Es vergleicht seit R-0191 mit `diff` und `sed`.
Test: Die Bau-Session ändert nur ihre eigene Task. Danach trägt eine Zeile ihres Abschnitts ein U+2028 und dahinter
`### T2 …` (ein Fake-Modus wie `cr` aus T5 von 4b). Erwartet: `bereit`, kein Block „outside its own task“. Die
bestehenden Gegenproben (`ncr`, eine Änderung in einer anderen Task) bleiben rot.
Rot vorher: `splitlines` liest `### T2 …` als eigenen Kopf, der Rest-Hash ändert sich, und das Ledger wird blockiert.
Beweis: main@6ca2f3a2 · `python3 -c 'print(len("Dateien: a ### T2 x\n".splitlines(True)))'` ergibt `2`,
`printf 'Dateien: a\342\200\250### T2 x\n' | wc -l` ergibt `1`.
Dedup-Key: ref:scripts:ledger-loop.sh:splitlines
HEAD: 6ca2f3a2
Semantik: `AUTONOMOUS.md:246–248` „ändert ein Ledger nur über `ledger.sh` (`mark-skip`, `mark-question`,
`set-files`) und nur in ihrer eigenen Task — Kopf und andere Tasks bleiben, wie sie waren, sonst wird die Task
`[?]`“. Was zur eigenen Task gehört, bemisst sich an den Zeilen, die auch die Zeilenwerkzeuge des Loops sehen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — `lane.sh lane_db` schlägt geschlossen fehl (R-0255)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f456936b 2026-10-09T20:57:03+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `lane_db` (`lane.sh:74`) prüft nach dem Zerlegen (`:81–86`), ob die URL noch `user:password@` trägt. Wenn ja, endet
  es mit Exit ≠ 0 und einer Meldung ohne den Wert. Weder createdb noch dropdb laufen. `lane.sh new` legt dann nichts
  an, denn die DB kommt zuerst (`:158`).
- `DEVELOPMENT.md` (`:204`, „Eine Lane hat ihre eigene Test-DB“) bekommt einen Satz: Das Passwort reist in
  `PGPASSWORD`, nie in einem Argument; eine URL, deren Passwort `lane.sh` nicht herauslösen kann, legt keine Lane an.
Test `lane_test.sh` mit dem Recorder für createdb und dropdb (`:45`): Zwei Formen, die das Muster nicht zerlegt:
- leerer Benutzer: `postgresql+psycopg://:secret@localhost:5432/adminhelper_test`;
- `postgres://ah:secret@localhost:5432/adminhelper_test` (`lane_db_url`, `:71`, schreibt nur `postgresql+<treiber>`
  um).
Für beide gilt: `lane.sh new` endet mit Exit ≠ 0, es gibt keinen createdb-Aufruf und keine Lane, und `secret` steht
weder im Recorder-Log noch in der Ausgabe.
Rot vorher: createdb läuft mit `--maintenance-db=…:secret@…`, das Passwort steht also im Argument.
Beweis: main@6ca2f3a2 · `[[ "postgresql://:secret@localhost/db" =~ ^(postgresql://[^:@/]+):([^@]*)@(.*)$ ]] || echo no-match`
ergibt `no-match`; dann geht `$url` unverändert in `createdb --maintenance-db="$url"` (`lane.sh:89`).
Dedup-Key: ref:scripts:lane.sh:lane-db-fail-closed
HEAD: 6ca2f3a2
Semantik: keine Stelle in docs/. Gesucht habe ich in DEVELOPMENT.md (`:204` nennt die eigene Test-DB, nichts zum
Passwort), in AUTONOMOUS.md und in docs/developer nach PGPASSWORD, Passwort und createdb. Die Regel steht nur im
Kommentar `lane.sh:77–80`: „The password travels in the environment, and not through `env`'s arguments either:
every local user can read a process's arguments (/proc/<pid>/cmdline), only its owner its environment.“ Der Satz in
DEVELOPMENT.md schließt die Lücke; siehe die offene Frage 2.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (ein Satz, „Eine Lane hat ihre eigene Test-DB“)

## Offene Fragen am Gate

1. R-0250, der Weg. Die Empfehlung ist die Kostendatei, die der Loop mitgibt: eine Quelle, an die die Suite keinen
   Deskriptor hat. Die Alternative ist billiger: Steht mehr als eine Kostenzeile im Close-Log, zählt der Loop den
   Deckel. Das fängt eine angehängte Zeile, aber kein Abschneiden des Logs über den geerbten Deskriptor. Beide
   bleiben unter derselben UID keine harte Grenze.
2. R-0255, die Semantik-Lücke. Die Regel „Passwort nie im Argument“ steht nur im Code. Empfehlung: der eine Satz in
   DEVELOPMENT.md (in T3). Normalisiert `lane.sh` `postgres://` wie `builder-home.sh`? Empfehlung: nein. Die
   Projekt-URLs sind SQLAlchemy-URLs (`postgresql+<treiber>`), und die Prüfung lehnt jede andere Form ab.
