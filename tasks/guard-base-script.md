<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Public repo guard: Logik der Basis, kein abgebrochener Push-Lauf, leere Spanne sagt es — Task-Ledger
Status: erledigt · Branch: harness/guard-base-script · Commit-Granularität: pro Task · Review: am Ende (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Freigabe: Kevin, 2026-10-05 (Design-Gate guard-base-script, „Freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0174
Heavy: none — nur der CI-Job `public-repo-guard`, die Workflow-`concurrency`, `review.sh sec` und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den echten Beweis liefern der eigene PR-Lauf und der erste Push-Lauf auf main nach dem Merge (siehe T2).
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-05 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-10-05. Zeilenangaben main@bde4cfa4.
Bau interaktiv: alle Dateien liegen unter Harness-Pfaden.

Befund: Der CI-Job „Public repo guard (review.sh sec)“ (#77, R-0123) prüft mit dem `review.sh` aus dem Checkout des
Pull Requests (`.github/workflows/ci.yml:775`) — ein PR, der `sec` lockert oder bricht, prüft sich mit der eigenen,
geänderten Logik. Die Workflow-`concurrency` (`ci.yml:16–18`, `group: ci-${{ github.ref }}`,
`cancel-in-progress: true`) bricht auch einen laufenden Push-Lauf auf main ab, sobald der nächste Push kommt; dessen
Spanne `before..sha` bleibt dann ungelesen. Und eine leere Spanne (`workflow_dispatch` auf main: `origin/main...HEAD`
mit HEAD = origin/main) meldet „sec: clean“ (`scripts/dev/review.sh:759`), ohne einen Commit gelesen zu haben.

Entscheidungen (Kevin 2026-10-05, C Aufsicht):
- A: Basis **und** PR müssen grün sein. Die Logik der Basis ist das Gate, das ein PR nicht lockern kann; der Lauf mit
  der Logik des PRs fängt ein kaputtes `review.sh` sofort und hält den Gleichlauf mit den lokalen Hooks. Grenze, bewusst
  hingenommen: ein PR, der einen Fehlalarm der Basis-Logik beheben will, wird von ihr noch blockiert (dann Admin-Merge).
- B: Jeder Push auf main bekommt eine eigene Concurrency-Gruppe und wird nie abgebrochen oder verdrängt; Pull Requests
  brechen wie bisher ab.
- C: Ein `workflow_dispatch` liest nicht die ganze Historie (~48 s, trifft den bekannten Altbestand); die Meldung „empty
  span“ aus T3 reicht.

Nicht in diesem Ledger: Punkt (4) der Roadmap-Zeile (Push über die ganze Historie dauert lange) — der pre-push-Hook
nennt den Grund schon (`scripts/dev/hooks/pre-push:32`).

### T1 — Der Guard prüft mit der Logik der Basis und mit der des PRs  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, scripts/tests/review_scripts_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 8 ok @5c3330b6 2026-10-05T10:00:30+02:00
Review: Review am Ende (Kurz-Ledger, Opus); Gegenprobe mit ci.yml aus HEAD: 5 Job-Faelle rot, der PR mit gelockertem review.sh laeuft dort gruen (rc 0)
Änderung: Im Job `public-repo-guard` (`ci.yml:747`) läuft vor dem bisherigen Aufruf (`:775`) ein zweiter mit dem
`review.sh` der Basis: `git worktree add --detach "$RUNNER_TEMP/base" "origin/$BASE_REF"` (bei push und
workflow_dispatch `origin/main`), dann `bash "$RUNNER_TEMP/base/scripts/dev/review.sh" sec --range …`. Die Spanne nennt
`$SHA` (`github.sha`, beim PR der Merge-Commit) statt `HEAD`, denn im Worktree ist HEAD die Basis: PR
`origin/$BASE_REF...$SHA`, push `$BEFORE..$SHA`, sonst `origin/main...$SHA`. Das geht, weil `review.sh` sich über den
eigenen Ort an sein Repo bindet (`review.sh:114–115`, `ROOT=…/../..; cd "$ROOT"`) und der Worktree Refs und Objekte mit
dem Checkout teilt; `sec` liest keine Beidatei (`harness-paths.txt` liest nur `scope`, `:616`). Fehlt in der Basis
`scripts/dev/review.sh` oder kann es kein `sec --range` (`grep -q -- '--range'` im Kopf der Datei), endet der Schritt mit
`::error::` und Exit 1 (fail-closed). Beide Aufrufe müssen grün sein (Entscheidung A); die Ausgabe nennt, welcher
gelaufen ist („base logic“ / „this change's logic“). Event-Werte weiter nur über `env`, nie als Ausdruck im Skript.
Test: statische Prüfung in `review_scripts_test.sh` (der Job ruft das review.sh unter `$RUNNER_TEMP/base` und das
eigene, beide mit `$SHA`, der fail-closed-Zweig existiert) und ein hermetischer Fall: ein Wegwerf-Repo mit einer Basis,
deren review.sh einen privaten Pfad sperrt, und einem PR-Commit, der die Sperre aus review.sh entfernt und
`tasks/private/x.md` hinzufügt ⇒ der Aufruf mit der Logik der Basis endet mit 4, der mit der Logik des PRs mit 0.
Beweis: main@bde4cfa4, `ci.yml:775`: `bash scripts/dev/review.sh sec --range "$range"` — das review.sh des
ausgecheckten PR-Stands; `git show origin/main:.github/workflows/ci.yml | grep -c 'RUNNER_TEMP/base'` ⇒ 0
Dedup-Key: ref:ci:ci.yml:public-repo-guard-base-script
HEAD: bde4cfa4
Semantik: `docs/developer/cicd.html:40`: „Der Job `public-repo-guard` (…) fährt dieselbe Sperre wie die lokalen Hooks
über jeden Commit eines Pull Requests bzw. Pushs“ — eine Sperre, die der geprüfte PR selbst ändern kann, ist keine.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: cicd.html DE+EN (Satz zum Job `:40`: prüft mit der Logik der Basis und der des PRs, beide müssen grün sein, mit
der Grenze aus A), DEVELOPMENT.md (Absatz zum Guard `:824` ff.), CHANGELOG
Abweichung (Bau): Beim Push ist die Basis `$BEFORE`, nicht `origin/main` — nach dem Push zeigt `origin/main` schon
auf den gepushten Commit, dessen `review.sh` wäre die Logik des Änderungsstands. Der Test hält beide Basen fest
(„base logic (origin/main)“ beim PR, „base logic (<before>)“ beim Push).

### T2 — Pushes auf main laufen immer zu Ende  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, scripts/tests/review_scripts_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 8 ok @f7fb1f54 2026-10-05T10:09:32+02:00
Review: Review am Ende (Kurz-Ledger, Opus); Gegenprobe mit ci.yml aus HEAD: Concurrency-Pruefung rot; GitHub-Auswertung des Ausdrucks nicht verifiziert, Beweis nach dem Merge (Aufsicht)
Änderung: Die Workflow-`concurrency` (`ci.yml:16–18`) wird
`group: ${{ github.event_name == 'push' && format('ci-push-{0}', github.sha) || format('ci-{0}', github.ref) }}` und
`cancel-in-progress: ${{ github.event_name == 'pull_request' }}` (Entscheidung B). Ein Push bekommt so eine eigene
Gruppe je Commit — weder abgebrochen noch als `pending` verdrängt (laut GitHub-Doku verdrängt ein neuer Lauf einen
wartenden derselben Gruppe auch ohne `cancel-in-progress`, daher die eigene Gruppe statt nur `false`); Pull Requests
brechen wie bisher den älteren Lauf derselben Ref ab. `workflow_dispatch` bleibt bei `ci-<ref>` ohne Abbruch.
Test: statische Prüfung in `review_scripts_test.sh` (beide Ausdrücke stehen so in `ci.yml`).
**Nicht verifiziert:** dass GitHub den Group-Ausdruck mit `&&`/`||` als Zeichenkette so auswertet; die Doku belegt
Ausdrücke in `group` und `cancel-in-progress` (für `cancel-in-progress` wörtlich: „you can specify
`cancel-in-progress` as an expression“), zeigt diese Form aber nicht. **Beweis-Schritt nach dem Merge** (Aufsicht): den
ersten Push-Lauf auf main mit `gh run view <id> --json jobs,displayTitle` ansehen — er läuft durch, und ein zweiter
Push kurz danach bricht ihn nicht ab; ein PR-Lauf bricht weiter ab. Ergebnis in den Abschluss dieses Ledgers.
Beweis: main@bde4cfa4, `ci.yml:16–18`: `group: ci-${{ github.ref }}` und `cancel-in-progress: true` gelten für jedes
Event, also auch für push auf main
Dedup-Key: ref:ci:ci.yml:public-repo-guard-base-script
HEAD: bde4cfa4
Semantik: `docs/developer/cicd.html:40` (wie T1): der Guard prüft „jeden Commit eines Pull Requests bzw. Pushs“ — ein
abgebrochener Push-Lauf prüft keinen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: cicd.html DE+EN (ein Satz: Läufe auf main-Pushes werden nie abgebrochen), CHANGELOG
Abhängt von: T1 (dieselbe Datei)

### T3 — Eine leere Spanne heißt „nothing read“, nicht „clean“  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 8 ok @b64f0ac7 2026-10-05T10:19:28+02:00
Review: Review am Ende (Kurz-Ledger, Opus); Gegenprobe mit review.sh aus HEAD (neues ci.yml und neuer Test im Wegwerf-Worktree): 3 Faelle rot, dort sec: clean
Änderung: `sec --range` gibt bei null Commits in der Spanne (`COMMITS` leer nach `git rev-list`, `review.sh:740`)
`sec: empty span (<range>) — nothing read` aus und endet mit Exit 0 — nicht mehr „sec: clean“ (`:759`). Exit 0, weil
der pre-push-Hook bei einem Push ohne neue Commits sonst fälschlich verweigerte; er verwirft die Standardausgabe ohnehin
(`pre-push:46`, `>/dev/null`). Der CI-Schritt macht aus dieser Zeile eine `::notice::` (Entscheidung C: keine ganze
Historie). Test: leere Spanne (`HEAD..HEAD`, `a...a`) ⇒ genau diese Meldung, kein „clean“, Exit 0; eine Spanne mit einem
sauberen Commit ⇒ weiter „sec: clean“.
Beweis: main@bde4cfa4, `review.sh:740–759`: bei leerem `COMMITS` läuft die Schleife nicht, `BLOCKED` bleibt leer, und
`:759` druckt „sec: clean“
Dedup-Key: ref:ci:ci.yml:public-repo-guard-base-script
HEAD: bde4cfa4
Semantik: `docs/developer/cicd.html:40`: der Guard „nennt nur Pfad bzw. Datei:Zeile“ — und „clean“ ist ein Befund über
gelesene Commits; über eine leere Spanne gibt es keinen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: cicd.html DE+EN (ein Halbsatz zum Dispatch auf main), CHANGELOG
Abhängt von: T1 (ci.yml)

### T4 — Befunde aus dem Gesamt-Review: Job-Kommentar enger, Umbruch in DEVELOPMENT.md  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 7 ok @16ab2d3d 2026-10-05T10:48:51+02:00
Review: aus dem Gesamt-Review (Opus, approve): zwei nit mitgenommen, Job-Kommentar enger, Umbruch; kein Verhalten geaendert
Änderung: Zwei `nit` aus dem Gesamt-Review (Opus, approve), mitgenommen, weil der Kommentar mehr zusagt als der Job
hält: (1) Der Kommentar über `public-repo-guard` sagt „a pull request cannot loosen the rule it is checked by“ — die
Workflow-Datei selbst kommt beim PR aber aus dem PR; enger gefasst wie die Doku: eine Änderung an `review.sh` wird mit
der Logik geprüft, die vor ihr galt. (2) Der in T1 eingefügte Absatz in `DEVELOPMENT.md` (Guard, R-0174) neu
umbrochen (eine Zeile mit 121 Zeichen). Kein Verhalten ändert sich.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine weitere (die Änderung ist selbst Kommentar und Doku)

Abschluss-Evidenz (2026-10-05):
- Gesamt-Schnellcheck @16ab2d3d: `run.sh[quick]: 18 passed, 0 failed, 0 skipped, 12 test-skips, 0 reruns`
  (`run.sh quick --strict`); T4 danach nur Kommentar und Umbruch, sein Verify `run.sh[quick] scripts: 6 passed,
  0 failed, 12 skipped`. origin/main (bde4cfa4, #77) enthalten, seitdem nichts Neues auf main.
- Review am Ende (Opus, eine Runde) über T1–T3: approve, zwei `nit` → T4; ein Roadmap-Kandidat an die Aufsicht.
- Gegenproben gegen die jeweils vorige Fassung rot: T1 5 Job-Fälle (der Fall „PR ändert sein review.sh“ lief dort
  grün), T2 die Concurrency-Prüfung, T3 3 Fälle („sec: clean“ für eine leere Spanne).
- T1 weicht beim Push ab: Basis `$BEFORE`, nicht `origin/main` (Vermerk in T1).
- T2 nicht verifiziert: wie GitHub den Group-Ausdruck auswertet, belegt der erste Push-Lauf auf main nach dem Merge
  (Aufsicht).
- Heavy: none (wie geplant). Der Job beweist sich im eigenen PR-Lauf.
