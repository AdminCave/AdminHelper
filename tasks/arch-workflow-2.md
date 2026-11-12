# Harness: Sammellauf ohne Server-pytest auf der Box — Task-Ledger
Status: aktiv · Branch: feature/arch-workflow-2 · Review: pro Task
Spec: docs/features/arch-workflow-2.md (Roadmap R-1338)
Heavy: linux-full — ändert, was der Sammellauf auf der Box fährt; Gesamtbeweis ist der erste nächtliche Lauf nach dem Merge, vorher gezielt `--step schemathesis` und `--step sse_push` auf einer frisch geleasten Lane-Box (Spec, Risiken)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1338: Schemathesis und sse_push_e2e installieren ihre Pakete selbst  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/sse_push_e2e.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6c9b4557b 2026-11-12T08:48:38+01:00
Review: approve (.ah-out/review/arch-workflow-2/T1.verdict.json)
Änderung: Der Schemathesis-Schritt installiert je Dienst vor seinem pytest dessen `requirements-dev.txt` (ein Fehler macht den Schritt rot). `sse_push_e2e.sh` legt das Venv an, wenn es fehlt, und installiert die `requirements.txt` des Servers bei jedem Lauf statt nur bei fehlendem `uvicorn`; ein Fehlschlag bleibt SKIP 75 wie heute. Erst der rote Test in `run_flags_test.sh`: mit dem Python-Shim installiert `--step schemathesis` je Dienst vor dem pytest, und `sse_push_e2e.sh` installiert die Server-Pakete auch in ein Venv, das `uvicorn` schon hat.
Beweis: run.sh:737 installiert die Server-Pakete nur im Schritt server-pytest; der Schemathesis-Block (run.sh:752-793) ruft kein pip; sse_push_e2e.sh:36 prüft nur auf uvicorn, das Monitoring mitbringt · Dedup-Key: ref:harness:sammellauf:server-pytest
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (internes Verhalten zweier Schritte; die Doku beschreibt nicht, welcher Schritt was ins Venv installiert)

### T2 — R-1338: run.sh `--exclude <ids…>`  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, .claude/rules/testing.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e36e45015 2026-11-12T09:09:36+01:00
Review: approve (.ah-out/review/arch-workflow-2/T2.verdict.json)
Änderung: Neue Option `--exclude <ids…>` (Env-Form `AH_EXCLUDE`) nach der Spec, Abschnitt „Design `--exclude`“. Ein ausgeschlossener Schritt läuft nicht, erscheint nicht als SKIP und nicht im Artefakt und gilt unter `--strict` nicht als Pflicht-SKIP. Geprüft wird in `run_step`, `run_py_step` und `skip` vor dem Filter für Teil und Schritt. Eine unbekannte Id endet im Probelauf mit Exit 2, bevor ein Schritt läuft, ebenso `--exclude` ohne Id. Die Zusammenfassung druckt `excluded: <ids>`, das Artefakt trägt `exclude`. Tests: ein ausgeschlossener Pflicht-Schritt unter `--strict` (Exit 0, kein SKIP, nicht im Artefakt), unbekannte Id, fehlende Id, Kombination mit `--part` und `--step`, Env-Form, Zusammenfassung und Artefakt-Feld. Die Flag-Liste in `.claude/rules/testing.md` zieht mit.
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: .claude/rules/testing.md (Flag-Liste); DEVELOPMENT.md und cicd.html DE+EN in T4

### T3 — R-1338: iter.sh reicht `--exclude` weiter, heavy.sh lässt server-pytest in Teil rest aus  [ ]
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/tests/iter_flags_test.sh, scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, .claude/skills/test/SKILL.md
Änderung: `iter.sh` nimmt `--exclude` in die Liste der weitergereichten Flags auf (Kopf, Fall-Liste, Fehlertext). `heavy.sh part_job` hängt für Teil `rest` `--exclude server-pytest` an, mit einem Kommentar zum Warum (CI fährt dieselbe Suite auf jedem `main`-Commit, R-1338), und der Report trägt dazu eine Notiz; der Kopfkommentar zu den Teilen zieht mit. Tests: `iter_flags_test` prüft per Probelauf die Weiterleitung samt Ids; `heavy_test` prüft die Argumente von Teil `rest` (mit `--exclude server-pytest`) und Teil `gui` (ohne), auch beim seriellen Ersatz auf der Desktop-Box, und die Notiz im Report. Der Abschnitt zu `all` im `/test`-Skill zieht mit.
Verify: bash scripts/dev/verify.sh scripts --strict -- iter_flags_test heavy_test
Doku: .claude/skills/test/SKILL.md (Teil rest); DEVELOPMENT.md und cicd.html DE+EN in T4
Abhängt von: T1, T2

### T4 — Doku: `--exclude` und Teil rest ohne Server-pytest  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: `DEVELOPMENT.md`: die `run.sh`-Flag-Zeile bekommt `--exclude <ids…>`, und der Wochenlauf-Punkt `all` sagt, dass Teil `rest` `server-pytest` auslässt und warum. `cicd.html` DE+EN: eine Zeile `--exclude` in der Flag-Tabelle des Test-Aggregators und derselbe Satz im Abschnitt „Wochenlauf“.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: DEVELOPMENT.md, docs/developer/cicd.html DE+EN
Task-Review: am Ende
Abhängt von: T2, T3

## Entscheidungen
- 2026-11-12: Vergleich frisch wiederholt (Spec, Problem): CI py3.14 3415 passed, 0 skipped; Box 3415 Tests, 54 skipped — die Bedingung der Zeile ist erfüllt.
- 2026-11-12: `--exclude` in run.sh statt `AH_ONLY` (nähme Schemathesis und ruff für den Server mit) oder gekürztem `AH_REQUIRED` (Schritt liefe weiter); Spec, Trade-offs.
- 2026-11-12: Die Option setzt heavy.sh (Teil rest), nicht nightly.sh: auch ein manueller `/test all` lässt den Schritt aus; vor einem Release bleiben main-CI und `run.sh quick --strict`.
- 2026-11-12 (T1): Der Schemathesis-Schritt verliert die Vorprüfung `import schemathesis`. Er installiert das Paket selbst (es steht in allen drei `requirements-dev.txt`), und auf einem frischen Venv hätte die Vorprüfung ihn übersprungen, bevor er installieren kann. Ein fehlgeschlagenes `pip install` ist ein FAIL, auch ohne `--strict`. Der Test „missing package strict-fails“ wird dadurch ersetzt durch „failed install fails, runs no suite“, der strenger ist (FAIL statt Pflicht-SKIP). Der Kommentar in `ci.yml:521-522` („gate finds the package“) veraltet; ci.yml gehört dem Zug `arch-workflow-ci-1`, deshalb eine Roadmap-Zeile.
- 2026-11-12 (T2): `excluded()` vergleicht jede Id wörtlich nach Wortaufteilung von `AH_EXCLUDE` (Schritt-Ids tragen keine Leerzeichen); dieselbe Aufteilung prüft der Probelauf, also kann keine Id den Probelauf bestehen und im Lauf anders wirken. `--step X --exclude X` ist Exit 2 mit Hinweis, weil sonst ein strenger Lauf mit „no step ran“ endete, ohne den Grund zu nennen. Der alte Test zur Meldung „no step ran“ prüft jetzt `exclude=none` mit (strenger, nicht schwächer).
