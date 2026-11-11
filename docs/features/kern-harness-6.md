# kern-harness-6 — `roadmap.py` vergibt keinen gemergten Ledger-Slug neu

Roadmap: R-1291 (BUG).

## Problem
Die Triage ordnete R-1216 `tasks/kern-ca-7.md` zu, ein Ledger, das schon auf `main` lag. Der Plan des neuen Zugs
überschrieb dadurch Spec, Ledger und ein unveröffentlichtes `changelog.d`-Fragment des gemergten Zugs (behoben in
kern-ca-12). `roadmap.py status --ledger` und `add --ledger` nehmen heute jeden Pfad an.

## Ziel & Nicht-Ziele
Ziel: `roadmap.py status R-nnnn … --ledger tasks/<slug>.md` und `roadmap.py add … --ledger tasks/<slug>.md` lehnen
mit Exit 2 ab, wenn der Pfad auf `origin/main` existiert und nicht schon in der Spalte `Ledger` der Zeile steht; die
Meldung rät zu einem neuen Slug. `/feature-plan --zug` nennt die Prüfung des Slugs gegen `origin/main:tasks/` und die
Remote-Branches.
Nicht-Ziele: eine Prüfung gegen offene Branches im Skript (ein Zug, der auf seinem Branch Zeilen aufnimmt, soll
weiter gehen); `sync`, `approve` und Zeilen, deren Spalte den Pfad schon trägt, bleiben unberührt.

## Betroffene Komponenten & Dateien
`scripts/dev/roadmap.py` (`cmd_status`, `cmd_add`, ein Helfer neben `repo_git`), `scripts/dev/tests/test_roadmap.py`,
`.claude/skills/feature-plan/SKILL.md` (§3a `--zug`), `DEVELOPMENT.md` (Abschnitt zu `--ledger`). Harness, Änderung
auf Kevins Wort 2026-11-11.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs
Geprüft wird gegen `origin/main` (`git cat-file -e origin/main:<pfad>`), nicht gegen das lokale `main`: der
Haupt-Checkout steht oft hinter `origin/main`. Ohne git, ohne Repo oder ohne diese Ref lehnt das Skript nicht ab
(Fixtures, frisches Klon ohne Remote): die Prüfung ist eine Sperre gegen einen bekannten Fehler, kein Pflicht-Gate.
Eine unveränderte Zuordnung (der Pfad steht schon in der Spalte) bleibt erlaubt, damit `status` einer gemergten
Zeile ihr Ledger mitgeben kann.

## Risiken & Rollback
Gering; ein falsch abgelehnter Aufruf ist Exit 2 mit Meldung. Rollback durch Revert der Task.

## Doku-Impact
`DEVELOPMENT.md` (Satz zu `--ledger`), `/feature-plan` §3a.

## Offene Fragen
Keine.
