<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinpaket 3: eine angekündigte Assertion-Änderung im diff-scan — Task-Ledger
Status: freigegeben · Branch: harness/kleinpaket-3 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (kleines Fund-Paket aus R-0206, von Kevin am 2026-10-06 angenommen; Kevin am Gate: Helfer eng gefasst ja (T2), Restrisiko verrutschter Spannen durch Testköpfe in Kommentar oder String und `assert True` als neue Assertion hingenommen; Aufsicht: n ≥ r, die Absicht in review.sh und tasks/README.md ändert sich mit Kevins Annahme von R-0206; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0206 (Kurz-Ledger ohne Spec)
Heavy: none — nur Harness-Skripte unter scripts/dev, ihre hermetischen Tests, Skills und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus R-0206, die Kevin am 2026-10-06 als
Kleinpaket-3 nach Kleinpaket-2 angenommen hat. `review.sh diff-scan` wertet eine geänderte, auch eine verschärfte
Assertion in einem Test, der stehen bleibt, als gelöscht (Exit 3); einen geregelten Weg gibt es nicht, zweimal
brauchte es einen Handcommit auf Kevins Wort, und R-0202 hängt daran. Das Ledger baut den Weg nach dem Muster von
`Test-Löschung:` (R-0079): angekündigt in der committeten Task, geprüft am Inhalt der Dateien. Die Testgrenzen ohne
Kopf im `-U0`-Block sind kein Hindernis: `heads()` (`review.sh:381`) rechnet die Spanne eines Tests aus dem ganzen
alten und dem ganzen neuen Dateiinhalt, für pytest, Go, vitest/jest und Rust mit `#[test]`.
Der Branch setzt auf `harness/kleinpaket-2` (@0327cb92) auf, weil beide `review.sh`, `ledger.sh`, ihre Tests und
`tasks/README.md` anfassen; gemergt wird er erst nach Kleinpaket-2, und Kleinpaket-2 wird vor dem Bau
hereingeholt. Bau interaktiv (Harness-Pfade), keine Lane, der Runner nicht. Zeilenangaben
harness/kleinpaket-2@0327cb92.

### T1 — `diff-scan` lässt eine angekündigte `Assertion-Änderung:` durch, `task-close` sperrt die Selbst-Ankündigung  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh, tasks/README.md, AUTONOMOUS.md, DEVELOPMENT.md
Änderung: (1) `diff-scan --task` liest neben `Test-Löschung` (`review.sh:240`) das Feld
`Assertion-Änderung: <datei>::<test> — <Grund>[; …]` aus dem Ledger in `HEAD`, mit demselben Parser. Das awk gibt
neben `RA` für jede hinzugefügte Zeile mit Assertion einen Datensatz `AA` aus (dasselbe Prädikat wie `RA`, als awk-
Funktion herausgezogen; eine reine Kommentarzeile zählt nicht); der Filter der Ausgabe kennt `AA`. Eine Ankündigung
zählt nur, wenn sie einen Grund trägt, der Name im alten **und** im neuen Stand der Datei genau einmal Kopf eines
Tests ist, keine der beiden Spannen den Kopf eines anderen Tests enthält (der `inner`-Schutz von `review.sh:457`,
auf beide Seiten) und die Datei im Diff nicht umbenannt ist. Dann geht eine entfernte Assertion durch, wenn ihre
alte Zeile in der alten Spanne liegt und die neue Spanne mindestens so viele hinzugefügte Assertions trägt, wie
die alte verliert (n ≥ r, offene Frage 1). Die Clean-Zeile nennt sie (`… declared assertion change(s):
<datei>::<test> (r removed, n added)`), ein Fund nennt den Grund, aus dem eine Ankündigung nicht zählte, wie heute.
Kopfkommentar (`review.sh:44–51`) und Hinweis (`:571–573`) nennen das Feld. (2) `task-close.sh` behandelt die neue
Zeile wie `Test-Löschung:`: `decl_lines` (`:120`) und die Prüfung des Commits (`:511–515`) erfassen beide Felder.
Tests (`review_scripts_test.sh`, Fixture-Ledger wie `:598–625`): durch geht eine verschärfte Assertion je Sprache
(pytest, Go, vitest, Rust), angekündigt und genannt. Ein Fund bleibt:
- die Änderung ohne Ankündigung;
- n = 0, und r = 2 bei n = 1;
- eine Assertion aus dem Nachbartest;
- derselbe Name in zwei Klassen;
- der Kopf ist im neuen Stand weg;
- die Ankündigung steht nur im Arbeitsbaum;
- eine Ankündigung ohne Grund;
- eine Kommentarzeile als neue Assertion;
- schiefe Einrückung, die zwei Tests in eine Spanne zieht;
- eine `Test-Löschung:` auf einen bleibenden Test wird keine Änderung.

`task_close_test.sh` (`:490–528`) fährt seine vier Fälle für beide Felder.
`tasks/README.md` bekommt nach dem Abschnitt `Test-Löschung:` (`:85–134`) einen Abschnitt `Assertion-Änderung:`.
Er nennt Syntax, Regeln, Passt/Passt nicht und das Restrisiko. Passt: schärfer, oder der Sollwert wechselt die Form.
Passt nicht: eine rote Assertion abschwächen. Das Restrisiko: Ein Testkopf in einem Kommentar oder String kann eine
Spanne verschieben; dagegen schützen nur das Gate und der Review.
Punkt 6 (`:119–121`) sagt: Eine Assertion aus einem bleibenden Test bleibt ein Fund, außer sie ist als
`Assertion-Änderung:` angekündigt. `AUTONOMOUS.md:32` und `DEVELOPMENT.md:469` bekommen je einen Halbsatz.
Beweis: R-0064 T4 (feature/tz-aware-datetimes@19585b29, gemergt mit #87), nachgestellt im Wegwerf-Worktree auf
`19585b29^`: `git cherry-pick -n 19585b29 && bash scripts/dev/review.sh diff-scan --staged` → Exit 3,
`apps/server/tests/test_users.py:228  removed assertion: assert expected["created_at"] == jsonable_encoder(user.created_at)`.
Präzedenz: server-api-contract, 2026-09-28 (ein Zähler in `mocks.contract.test.ts` je Task angehoben). Beide
gingen als Handcommit auf Kevins Wort.
HEAD: 0327cb92
Semantik: `review.sh:50–51`: „an assertion out of a test that stays is still a finding, declared or not.“ und
`tasks/README.md:120–121`: „Eine Assertion aus einem Test, der stehen bleibt, bleibt ein Fund, angekündigt oder
nicht.“ Die Doku beschreibt das heutige Verhalten als Absicht. Kevin hat R-0206 am 2026-10-06 angenommen; die
Absicht ändert sich damit, und T1 zieht beide Stellen nach (offene Frage 3).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (neuer Abschnitt, Punkt 6) · AUTONOMOUS.md · DEVELOPMENT.md

### T2 — Ein Helfer in einer Testdatei ist ankündbar  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, tasks/README.md
Änderung: Nur bei Ja zu offener Frage 2, sonst `ledger.sh mark-skip` mit Verweis auf die Antwort. Der Anlassfall
von T1 stand nicht in einem Test, sondern im Helfer `TestUserResponseShape._expected`, den vier Tests aufrufen;
`heads()` sieht Helfer nicht, und `diff-scan` zählt die Zeile trotzdem, weil `tests/` ein `TEST_PATH` ist.
`Assertion-Änderung:` darf deshalb auch eine Funktion einer Datei unter `TEST_PATH` nennen (`review.sh:539`):
- pytest `def <name>(`;
- Go `func <name>(` ohne Receiver;
- Rust `fn <name>` ohne `#[test]`;
- vitest/jest `function <name>(`.

Pfeil-Funktionen (`const name = … =>`) bleiben außen vor, denn ihre Formen sind zu vielfältig für eine Regex. Die
Regeln aus T1 gelten unverändert: genau einmal alt und neu, `inner` auf beiden Seiten, n ≥ r. Ein Kopf, den beide
Regex-Sätze treffen, zählt einmal. Die Clean-Zeile kennzeichnet die Zeile mit `(helper)`, damit der Review den
Radius sieht: Eine Ankündigung gilt für alle Aufrufer.
Tests:
- `_expected` als Klassenmethode nach dem Vorbild von 19585b29: durch.
- Ein Helfername, der doppelt vorkommt: Fund.
- Ein Pfeil-Helfer: nicht ankündbar, Fund.
- Ein Helfer außerhalb von `TEST_PATH`: dort ist die Zeile ohnehin kein Fund.

`tasks/README.md` bekommt einen Absatz zum Helfer und seinem Radius.
Beweis: wie T1; `git show 19585b29:apps/server/tests/test_users.py`, Zeilen 219–230 (Helfer) und 246, 257,
273, 289 (Aufrufer).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (Absatz Helfer)
Abhängt von: T1

### T3 — `ledger.sh lint` prüft die Form, die Skills nennen die Ankündigung  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-build/SKILL.md, .claude/skills/feature-review/SKILL.md, .claude/skills/build-task/SKILL.md
Änderung: (1) Der Lint für `Test-Löschung:` (`ledger.sh:308–318`) läuft über beide Felder, die Meldung nennt das
Feld; `<datei>::<test> — <Grund>`, der Grund ist Pflicht. Tests (`ledger_test.sh:278–296`): je Feld gültig, ohne
Grund, leerer Grund; `tasks/README.md` sagt es im neuen Abschnitt. (2) Die Ankündigung kommt nur über den Plan-
Commit ans Gate, und der Plan-Skill nennt heute keines der beiden Felder: Das Task-Schema von
`feature-plan/SKILL.md` (`:122–130`) bekommt die zwei optionalen Zeilen und einen Satz („ändert oder löscht eine
Task eine bestehende Assertion, kündigt sie sie an“). `feature-build/SKILL.md` (der Exit-3-Punkt) und
`build-task/SKILL.md` (`--fix`) sagen: eine bewusst geänderte Assertion ohne Ankündigung wird nicht
zurückgebaut, sondern `[?]` und gefragt. `feature-review/SKILL.md` (Tests) sagt: bei `Assertion-Änderung:` prüft der
Review, dass die neue Assertion mindestens so streng ist — das, was der Scan nicht sehen kann (`assert True`).
Beweis: wie T1; `ledger.sh lint` prüft heute nur `Test-Löschung:` (`ledger.sh:313–315`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (Lint-Satz) · die vier Skills
Abhängt von: T1
