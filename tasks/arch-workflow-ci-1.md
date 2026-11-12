# CI-Workflow: Stack-Job auf PRs, Pfad-Steuerung, Shards nach Laufzeit, merge_group, Nightly — Task-Ledger
Status: geplant · Branch: feature/arch-workflow-ci-1 · Review: pro Task
Spec: docs/features/arch-workflow-ci-1.md (Roadmap R-1339, R-1340, R-1341, R-1342, R-1343)
Heavy: none — nur Workflows und Test-Infrastruktur; kein Produktcode, kein Stack-, Gateway-, PKI- oder Install-Pfad; Stack-Job und nightly.yml beweisen sich im PR-Lauf selbst
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1339: Stack-Job auch auf PRs, Sammeljobs mit !cancelled()  [ ]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_shards.py, apps/server/tests/test_ci_workflow.py
Änderung: `integration-stack` verliert `if: github.event_name != 'pull_request'`, der Kommentar davor nennt den neuen Stand. `server-result` und `python-lock-server-result` laufen mit `if: ${{ !cancelled() }}` statt `always()`; `test_ci_shards.py` prüft das (heute `== "always()"`). Neu `test_ci_workflow.py` (SPDX): der Stack-Job hat kein Ereignis-`if`. Die Session fährt `bash .github/scripts/cache_settings_test.sh` zusätzlich direkt (liest `ci.yml`, R-1352).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_shards.py tests/test_ci_workflow.py tests/test_release_images.py
Doku: → T6

### T2 — R-1342: merge_group als Trigger  [ ]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_workflow.py
Änderung: `on:` bekommt `merge_group:`. `public-repo-guard` benennt den Fall `merge_group` ausdrücklich (Bereich `origin/main...$SHA`, Basis `origin/main`), statt ihn dem `*`-Zweig zu überlassen; `concurrency` bleibt (Queue-Refs eindeutig, abgebrochen werden nur `pull_request`-Läufe). `test_ci_workflow.py` prüft Trigger, Gruppe und Abbruchregel je Ereignis und fährt den Bereichs-Schritt des Guards mit `EVENT=merge_group` gegen ein Wegwerf-Repo.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py tests/test_ci_shards.py
Doku: → T6
Abhängt von: T1

### T3 — R-1340: Job changes, Pfad-Steuerung, Server auf PRs nur py3.14, Dauer-Ausgabe  [ ]
Komponente: server · Dateien: .github/scripts/ci_changes.py, .github/workflows/ci.yml, apps/server/tests/test_ci_changes.py, apps/server/tests/test_ci_shards.py, apps/server/tests/test_ci_workflow.py
Änderung: Neues `ci_changes.py` (SPDX, stdlib) bildet die geänderten Pfade auf Ausgaben ab (`server`, `server-legs`, `monitoring`, `ca-issuer`, `schemathesis`, `lock-*`, `agent-windows`, `rust-windows`); nur auf `pull_request` aus `git diff origin/$BASE_REF...$SHA`, sonst alles; ein unbekannter Pfad schaltet alles ein. Neuer Job `changes`; die gesteuerten Jobs tragen `${{ !cancelled() && needs.changes.outputs.<x> != 'false' }}`, die Server-Matrix kommt aus `server-legs` mit Fallback beider Beine; `server-result` bleibt feste Matrix und endet für ein nicht gewolltes Bein grün. Server-Pytest mit `--durations=25`, die JUnit-XML des 3.14-Beins wird Artefakt. Neu `test_ci_changes.py` (SPDX): Wahrheitstabelle, jede getrackte Datei klassifiziert, jede Datei unter `apps/` gehört zu einem Job, dockerignore-Positivliste von `apps/frps` im Server-Bezug, statischer Abgleich der Pfad-Literale der drei Python-Suiten; `test_ci_shards.py` fährt die Sammel-Schritte mit gewolltem und nicht gewolltem Bein. Dazu direkt `bash .github/scripts/cache_settings_test.sh`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_changes.py tests/test_ci_shards.py tests/test_ci_workflow.py tests/test_release_images.py
Doku: → T6
Abhängt von: T2

### T4 — R-1341: Server-Shards nach Laufzeit  [ ]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/shard_weights.toml, apps/server/tests/test_shard.py
Änderung: `shard_of_each_file` gewichtet je Datei mit Sekunden je Test × gesammelte Tests aus `shard_weights.toml` (neu, SPDX als Kommentar, Kopf nennt den Befehl zum Neuerzeugen); unbekannte Dateien bekommen den Mittelwert je Test, ohne Tabelle gilt die Testanzahl wie heute. Die Tabelle stammt aus der JUnit-XML des 3.14-Beins eines CI-Laufs dieses Branches (Artefakt aus T3; lokal gemessen nur als Fallback, im Commit-Body genannt). `test_shard.py`: gewichtete Verteilung, Fallback, Reihenfolge-Unabhängigkeit, Manifest unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_shard.py tests/test_ci_shards.py
Doku: → T6
Abhängt von: T3

### T5 — R-1343: nightly.yml mit schemathesis-tief und backup_restore  [ ]
Komponente: server · Dateien: .github/workflows/nightly.yml, apps/server/tests/test_ci_workflow.py
Änderung: Neuer Workflow (SPDX) mit `schedule`, `workflow_dispatch` und `pull_request` (`paths` nur auf sich selbst). Job schemathesis wie in `ci.yml`, aber `AH_SCHEMATHESIS_EXAMPLES: "100"`, Commit und Beispielzahl in der Job-Summary; Job backup-restore fährt `bash scripts/tests/backup_restore_test.sh`, Exit 75 ist rot. `test_ci_workflow.py` prüft Trigger, Budget, die Schritte und dass kein Job ein Ereignis-`if` trägt. Die Probe auf GitHub-Runnern ist der PR-Lauf dieses Workflows (vor dem Merge, im Bericht an Kevin). Dazu direkt `bash .github/scripts/cache_settings_test.sh`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: → T6

### T6 — Doku: CI-Seite DE+EN, CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/arch-workflow-ci-1.md
Änderung: `cicd.html` DE+EN: Stack-Job auf PRs, Jobs auf PRs vs. `main`/`merge_group`/Dispatch, Pfad-Steuerung mit Fail-safe und Pflicht-Checks, Shards nach Laufzeit (Tabelle neu erzeugen), `nightly.yml`. CHANGELOG-Fragment (Changed, Entwickler-Infrastruktur).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/arch-workflow-ci-1.md
Task-Review: am Ende
Abhängt von: T5

## Entscheidungen
