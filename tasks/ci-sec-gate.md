<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI-Sperre für Privates: review.sh sec über PR-Diff und vor jedem Push — Task-Ledger
Status: aktiv · Branch: harness/ci-sec-gate · Commit-Granularität: pro Task · Review: am Ende (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Freigabe: Kevin, 2026-10-05 („ci-sec-gate freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0123
Hängt ab von: harness/stufe-6b (gemergt) — beide ändern scripts/dev/review.sh, review_scripts_test.sh, DEVELOPMENT.md und docs/developer/cicd.html; erst nach dem Merge von 6b bauen und origin/main vorher hineinmergen
Heavy: none — nur ein Harness-Skript, ein neuer git-Hook, ein CI-Job und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad. Der CI-Job beweist sich im eigenen PR.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-04 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-10-03/04. Zeilenangaben main@cf4a9ab2.
Bau interaktiv: alle Dateien liegen unter Harness-Pfaden.

Befund: `review.sh sec` läuft heute nur lokal, in task-close und in vier Commit-Hooks (pre-commit, prepare-commit-msg,
pre-merge-commit, pre-applypatch; DEVELOPMENT.md:754–770). Kein Workflow fährt es: Was an den lokalen Hooks vorbeigeht
(ein Klon ohne `core.hooksPath`, ein Edit im GitHub-Web-UI, ein anderer Rechner), kommt ungeprüft auf main. Dazu kommt
eine zweite Lücke: Ohne pre-push-Hook ist ein Branch schon öffentlich, bevor ein CI-Check etwas meldet.

Entscheidungen:
- A: Die CI-Prüfung und ein lokaler pre-push-Hook zusammen (Kevin). Erst pre-push verhindert, dass Privates überhaupt
  öffentlich wird; CI fängt, was an den lokalen Hooks vorbeigeht.
- B: Ein eigener CI-Job mit festem Namen „Public repo guard (review.sh sec)“, damit er sich im Ruleset einzeln als
  Pflicht-Check eintragen lässt (Aufsicht).

Kevins Handgriff nach dem Merge: Im GitHub-Ruleset für main den Check „Public repo guard (review.sh sec)“ als
Pflicht-Check eintragen, wie die schon offenen „… (pytest, image lock)“-Checks. Der pre-push-Hook wirkt über das
gesetzte `core.hooksPath=scripts/dev/hooks` ohne weiteren Handgriff in jedem Klon, der main danach holt.

### T1 — `review.sh sec --range <a>..<b>`: sec über eine Commit-Spanne  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @87f2cc46 2026-10-05T06:29:32+02:00
Review: Review am Ende (Kurz-Ledger, Opus); Gegenprobe mit review.sh aus HEAD: 8 der 11 Range-Faelle rot (die 3 Usage-Faelle lehnt HEAD ohnehin ab)
Änderung: `--range` gilt heute nur für `risk` (`review.sh:168` „--range is for risk alone“). Es gilt künftig auch für
`sec`; `--staged` und `--range` schließen sich weiter aus (`:169`). Beide Prüfungen von sec lesen schon über
`changed_paths` bzw. `GIT_DIFF` mit `DIFF_ARGS` (`:164–179`, `:612–648`): die gesperrten Pfade und der
`sec:`-Dedup-Key in einer hinzugefügten Zeile. Sie gelten damit ohne weitere Änderung auch für die Spanne, inklusive
`a...b`, die das bestehende Muster `*..*` schon annimmt.

Die Ausgabe bleibt Pfad bzw. `datei:zeile`, nie der Inhalt einer Zeile; so darf sie in einem öffentlichen CI-Log
stehen. Ein Satz dazu kommt in den Kopfkommentar.

Tests: Fixture-Repo mit zwei Commits.
- Ein Commit, der `tasks/private/x.md` per `-f` hinzufügt, ⇒ `sec --range base..HEAD` Exit 4 mit dem Pfad.
- Ein Commit mit einem Dedup-Key der Klasse SEC (die Fixture baut die Zeile zur Laufzeit zusammen, wie die
  bestehenden sec-Tests) ⇒ Exit 4 mit `datei:zeile`, ohne den Schlüsseltext.
- Eine saubere Spanne ⇒ `sec: clean`.
- `--staged --range` ⇒ Fehler.
- Vor der Änderung rot: der erste Test, weil `--range is for risk alone`.

Beweis: main@cf4a9ab2. `grep -n "review.sh sec" .github/workflows/*.yml` liefert keinen Treffer, und
`bash scripts/dev/review.sh sec --range origin/main..HEAD` endet mit „--range is for risk alone“ (`review.sh:168`).
Dedup-Key: ref:ci:ci.yml:review-sec
HEAD: cf4a9ab2
Semantik: `DEVELOPMENT.md:754–757`: „`scripts/dev/hooks/pre-commit` faehrt vor jedem Commit `review.sh sec --staged` —
bis dahin lief die Sperre fuer privaten Plan, SEC-Ledger, `sec:`-Dedup-Keys, `.devenv.sh` und `settings.local.json`
nur in `task-close.sh`“. Dieselbe Sperre soll jeden Weg nach außen abdecken, nicht nur den lokalen Commit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine eigene (der Kopfkommentar von review.sh; die Nutzer-Doku folgt mit T2/T3)
Notiz: Eine Spanne wird Commit für Commit gelesen, nicht als Netto-Diff (eine Datei, die in der Spanne kommt und
wieder geht, verlässt mit dem Push trotzdem die Box); Merges über den kombinierten Diff (nur was gegen alle Eltern neu ist —
ein Merge von main bringt dessen öffentliche Zeilen nicht als Fund mit; Aufsicht 2026-10-05). Neu `--not-on <remote>`
für den pre-push (nur Commits, die der Remote noch nicht hat). Altbestand auf main, Aufsicht: bleibt —
`docs/features/harness-stufe-4.md:124` und `tasks/harness-stufe-4.md:42` (86128f52) beschreiben die Regel selbst;
eine Spanne, die 86128f52 enthält (z. B. `workflow_dispatch` auf einem Branch von vor dem 2026-09-18), trifft sie.

### T2 — CI-Job „Public repo guard (review.sh sec)“  [ ]
Komponente: scripts · Dateien: .github/workflows/ci.yml, scripts/tests/review_scripts_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md, CHANGELOG.md
Änderung: Neuer Job `public-repo-guard` in `ci.yml` mit `name: Public repo guard (review.sh sec)`, eingefügt nach
`openapi-compat` (`ci.yml:705`). Muster für Basis-Ref und `fetch-depth: 0` ist openapi-compat (`:714–738`).
- Rechte: `permissions: contents: read` (gilt schon global, `:13–14`), keine Secrets.
- Beim Pull Request: `bash scripts/dev/review.sh sec --range "origin/${{ github.base_ref }}...HEAD"`. Der Job läuft auch
  für Fork-PRs, weil er nichts Geheimes braucht.
- Beim Push auf main: `--range "${{ github.event.before }}..${{ github.sha }}"`. Ein leeres oder Null-`before` ist ein
  Fehler mit Meldung (fail closed); auf main kommt es nie vor, weil das Ruleset Force-Push verbietet.
- Läuft per `workflow_dispatch`, also ohne Vergleichsbasis: `--range "origin/main...HEAD"`.

Test: Eine statische Prüfung in `review_scripts_test.sh` liest `.github/workflows/ci.yml`. Der Job hat genau diesen
Namen, `fetch-depth: 0` und einen Aufruf `review.sh sec --range`; keiner seiner Schritte nutzt `secrets.`. Rot ohne den
Job.

Beweis: wie T1 (kein Workflow fährt sec).
Dedup-Key: ref:ci:ci.yml:review-sec
HEAD: cf4a9ab2
Semantik: `docs/developer/cicd.html:46–51`: „jede Änderung geht über einen Pull Request, CI muss grün sein“. Erst mit
diesem Job gehört die Sperre für Privates zu dem, was „CI grün“ bedeutet.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Tabelle der Workflows `:40` und der Ruleset-Absatz
`:46–51`: der neue Pflicht-Check) · DEVELOPMENT.md (Absatz pre-commit-Hook `:754` ff.: dieselbe Sperre in der CI) ·
CHANGELOG (Added)
Abhängt von: T1

### T3 — pre-push-Hook: sec über jede Spanne, die das Repo verlässt  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/pre-push, scripts/dev/harness.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md
Änderung: Neuer Hook `scripts/dev/hooks/pre-push` mit SPDX-Kopf, im Stil von `pre-commit` (fail closed: Exit ≠ 0
bricht den Push ab). Er liest von stdin die Zeilen `<local ref> <local sha> <remote ref> <remote sha>` (githooks(5),
pre-push) und fährt je Zeile `review.sh sec --range <basis>..<local sha>`.
- Basis bei bekanntem Remote-Stand: `<remote sha>`.
- Neuer Branch (Remote-sha nur Nullen): `git merge-base origin/main <local sha>`. Fehlt origin/main, zählt die ganze
  Historie des Branches (fail closed).
- Gelöschte Ref (local sha nur Nullen): überspringen.
- Tag: genauso, gegen merge-base.

`harness.sh status` nennt den Hook mit, in der Liste der Hooks bei `harness.sh:53`. `scripts/dev/hooks/**` ist schon
Harness-Pfad (`harness-paths.txt:18`).

Tests in `hooks_test.sh`, in einem Fixture-Repo mit einem lokalen Bare-Remote, Muster der vier Hooks `:127–136`:
- Push eines Commits mit `tasks/private/x.md` (per `-f`) ⇒ abgebrochen, der Remote bleibt unverändert.
- Ein neuer Branch mit sauberem Inhalt ⇒ durch.
- Eine Löschung ⇒ durch.
- `harness.sh status` nennt pre-push.
- Vor der Änderung rot: der erste Test, weil es keinen pre-push gibt.

Beweis: main@cf4a9ab2. `ls scripts/dev/hooks/` zeigt keinen `pre-push`; ein Push läuft heute ohne jede Prüfung
(`DEVELOPMENT.md:767–770` nennt nur die vier Commit-Hooks).
Dedup-Key: ref:ci:ci.yml:review-sec
HEAD: cf4a9ab2
Semantik: `DEVELOPMENT.md:767`: „dort vier Hooks, alle mit demselben `review.sh sec --staged`“. Die Sperre deckt bisher
Commits ab; der Push ist der Schritt, ab dem etwas öffentlich ist.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zu den Hooks `:767` ff.: fünfter Hook pre-push, was er prüft, Abbruch = kein Push)
Abhängt von: T1
