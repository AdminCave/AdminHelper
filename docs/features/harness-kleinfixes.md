<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinfixes: Verify-Zeile, REG-Ledger, Doku-Drift (R-0104, R-0119, R-0111)

## Problem / Motivation

Drei kleine Stellen im Harness sagen oder tun etwas anderes, als die Regeln verlangen:

- **R-0104:** `task-close.sh` fährt eine `Verify:`-Zeile, die kein `verify.sh`-Aufruf ist, nicht selbst,
  sondern nur die Suite der Task-Komponente (`scripts/dev/task-close.sh:184–196`, Zweig `*)`). Die
  Form `bash scripts/tests/run.sh <layer> --strict --only <keys…>` erlaubt der feature-plan-Skill
  aber ausdrücklich (`.claude/skills/feature-plan/SKILL.md:127`). Im Close von 5c T2
  (`--only web desktop-e2e`) lief so nur `web`; die Evidenz-Zeile belegt dann weniger, als das Ledger
  verlangt, und nennt die gelaufenen Komponenten nicht (`task-close.sh:284`). `verify.sh` nimmt heute
  genau eine Komponente (`scripts/dev/verify.sh:45–55`, `verify_test.sh:84` hält „second component
  -> exit 2“ fest), obwohl `run.sh quick --only` mehrere Keys kann (`verify.sh:109–113`).
- **R-0119:** `heavy.sh` schreibt das REG-Ledger mit `Branch: fix/$1` (`scripts/tests/heavy.sh:653`).
  Das Gate von `/feature-plan --kurz` legt aber `feature/<slug>` an und committet den Plan dort
  (R-0065); `feature-build` würde mit `fix/…` einen neuen Branch von main ohne Plan-Commit
  anlegen. Außerdem steht der schwere Befehl als `Verify:` in der Task (`:664`), obwohl schwere
  Läufe in die `Heavy:`-Zeile des Kopfs gehören (feature-plan-Skill, Abschnitt 3).
- **R-0111:** `DEVELOPMENT.md:413–414` und `:449–451` sowie `AUTONOMOUS.md:252–254` führen
  `git add`/`git commit`/`git checkout`/`git restore`/`git stash` noch unter `permissions.ask`.
  `.claude/settings.json` hat dort nur drei Einträge (bootstrap, `harness.sh off`,
  `ledger.sh mark-done`), und `scripts/tests/hooks_test.sh:998–1012` hält mit `never_ask` fest,
  dass die fünf Git-Verben dort nicht zurückkehren: Sie sind beim Runner hart verboten, in Kevins
  Sessions frei, committet wird über `task-close.sh`.

## Ziel & Nicht-Ziele

Ziel: Jede zugelassene Verify-Form wird so gefahren, wie sie dasteht, und die Evidenz nennt, was lief;
das REG-Ledger aus dem Wochenlauf passt ohne Handarbeit in den `--kurz`-Weg; die Doku stimmt mit den
Settings überein.

Nicht-Ziele: kein neuer Layer in `verify.sh` (es bleibt der quick-Layer); Prosa-Zeilen behalten den
heutigen Rückfall auf die Komponente der Task; der Skill-Satz `SKILL.md:127` bleibt (die `run.sh`-Form
ist weiter erlaubt); `docs/features/harness-stufe-4.md` bleibt als historische Spec unverändert.

## Betroffene Komponenten & Dateien

- `scripts/dev/verify.sh`, `scripts/dev/task-close.sh`, `scripts/tests/verify_test.sh`,
  `scripts/tests/task_close_test.sh` (T1)
- `scripts/tests/heavy.sh`, `scripts/tests/heavy_test.sh`, `tasks/README.md` (T2)
- `DEVELOPMENT.md`, `AUTONOMOUS.md` (T3)

Harness-Pfade (`scripts/dev/harness-paths.txt`): `verify.sh`, `task-close.sh`, `heavy.sh`,
`task_close_test.sh`, `verify_test.sh`, `AUTONOMOUS.md` — Bau interaktiv, Reviewer Opus.

## Datenmodell / API / Migrationen

Keine. Einzige Formänderung: die Evidenz-Zeile von `task-close.sh` nennt die gelaufenen Komponenten
(z. B. `run.sh[quick] web desktop-e2e: 2 passed, …`), und `last-verify.json` trägt im Feld
`component` bei mehreren Komponenten die Liste. `ledger.sh lint` prüft nur, dass unter einem `[x]`
eine `Evidenz:`-Zeile steht (`scripts/dev/ledger.sh:302–304`); die neue Form ändert daran nichts.

## Trade-offs & Alternativen

- R-0104 über ein `verify.sh` mit mehreren Komponenten (empfohlen, am Gate der Aufsicht bestätigt)
  statt einer Schleife je Komponente in `task-close.sh`: ein Lauf, ein Artefakt, eine Summary-Zeile;
  die Schleife hätte zwei Artefakte und mehr Code bedeutet. Mehrere Komponenten plus `-- args` ist ein
  Aufruffehler (Exit 2), weil unklar wäre, zu welcher Suite die Argumente gehören.
- R-0119 mit Verify-Platzhalter `bash scripts/dev/verify.sh <komponente> --strict` statt ganz ohne
  Verify: die Form bleibt vollständig, `ledger.sh lint` prüft sie, und `/feature-plan --kurz` ersetzt
  nur `<komponente>`.

## Risiken & Rollback

`task-close.sh` ist das Commit-Gate: ein Fehler dort hält jeden Bau auf. Deshalb bleibt der
Prosa-Rückfall unverändert, und eine Verify-Zeile, deren Liste die Task-Komponente nicht enthält, ist
Exit 2 statt eines stillen Laufs mit der falschen Liste. Rollback: `git revert` des T1-Commits.

## Doku-Impact

DEVELOPMENT.md (Abschnitt `verify.sh`, `task-close.sh`, Permissions), `tasks/README.md` (REG-Ledger),
AUTONOMOUS.md (Permissions), CHANGELOG [Unreleased].

## Offene Fragen

Keine; die Varianten hat die Aufsicht am 2026-09-30 mit Kevin entschieden (verify.sh mit mehreren
Komponenten, Verify-Platzhalter im REG-Ledger, Bau nach `schutz-nachziehen` wegen gemeinsamer
Doku-Stellen).
