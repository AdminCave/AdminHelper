# CI-Workflow: Stack-Job auf PRs, Pfad-Steuerung, Shards nach Laufzeit, merge_group, Nightly — Task-Ledger
Status: aktiv · Branch: feature/arch-workflow-ci-1 · Review: pro Task
Spec: docs/features/arch-workflow-ci-1.md (Roadmap R-1339, R-1340, R-1341, R-1342, R-1343)
Heavy: none — nur Workflows und Test-Infrastruktur; kein Produktcode, kein Stack-, Gateway-, PKI- oder Install-Pfad; Stack-Job und nightly.yml beweisen sich im PR-Lauf selbst
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1339: Stack-Job auch auf PRs, Sammeljobs mit !cancelled()  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_shards.py, apps/server/tests/test_ci_workflow.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @85b545864 2026-11-12T06:32:30+01:00
Review: approve (.ah-out/review/arch-workflow-ci-1/T1.verdict.json)
Änderung: `integration-stack` verliert `if: github.event_name != 'pull_request'`, der Kommentar davor nennt den neuen Stand. `server-result` und `python-lock-server-result` laufen mit `if: ${{ !cancelled() }}` statt `always()`; `test_ci_shards.py` prüft das (heute `== "always()"`). Neu `test_ci_workflow.py` (SPDX): der Stack-Job hat kein Ereignis-`if`. Die Session fährt `bash .github/scripts/cache_settings_test.sh` zusätzlich direkt (liest `ci.yml`, R-1352).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_shards.py tests/test_ci_workflow.py tests/test_release_images.py
Doku: → T6

### T2 — R-1342: merge_group als Trigger  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_ci_workflow.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0b1ddd685 2026-11-12T06:37:37+01:00
Review: approve (.ah-out/review/arch-workflow-ci-1/T2.verdict.json)
Änderung: `on:` bekommt `merge_group:`. `public-repo-guard` benennt den Fall `merge_group` ausdrücklich (Bereich `origin/main...$SHA`, Basis `origin/main`), statt ihn dem `*`-Zweig zu überlassen; `concurrency` bleibt (Queue-Refs eindeutig, abgebrochen werden nur `pull_request`-Läufe). `test_ci_workflow.py` prüft Trigger, Gruppe und Abbruchregel je Ereignis und fährt den Bereichs-Schritt des Guards mit `EVENT=merge_group` gegen ein Wegwerf-Repo.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py tests/test_ci_shards.py
Doku: → T6
Abhängt von: T1

### T3 — R-1340: Job changes, Pfad-Steuerung, Server auf PRs nur py3.14, Dauer-Ausgabe  [x]
Komponente: server · Dateien: .github/scripts/ci_changes.py, .github/workflows/ci.yml, apps/server/tests/test_ci_changes.py, apps/server/tests/test_ci_shards.py, apps/server/tests/test_ci_workflow.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4092edca9 2026-11-12T07:40:16+01:00
Review: approve (.ah-out/review/arch-workflow-ci-1/T3.verdict.json)
Änderung: Neues `ci_changes.py` (SPDX, stdlib) bildet die geänderten Pfade auf Ausgaben ab (`server`, `server-legs`, `monitoring`, `ca-issuer`, `schemathesis`, `lock-*`, `agent-windows`, `rust-windows`); nur auf `pull_request` aus `git diff origin/$BASE_REF...$SHA`, sonst alles; ein unbekannter Pfad schaltet alles ein. Neuer Job `changes`; die gesteuerten Jobs tragen `${{ !cancelled() && needs.changes.outputs.<x> != 'false' }}`, die Server-Matrix kommt aus `server-legs` mit Fallback beider Beine; `server-result` bleibt feste Matrix und endet für ein nicht gewolltes Bein grün. Server-Pytest mit `--durations=25`, die JUnit-XML des 3.14-Beins wird Artefakt. Neu `test_ci_changes.py` (SPDX): Wahrheitstabelle, jede getrackte Datei klassifiziert, jede Datei unter `apps/` gehört zu einem Job, dockerignore-Positivliste von `apps/frps` im Server-Bezug, statischer Abgleich der Pfad-Literale der drei Python-Suiten; `test_ci_shards.py` fährt die Sammel-Schritte mit gewolltem und nicht gewolltem Bein. Dazu direkt `bash .github/scripts/cache_settings_test.sh`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_changes.py tests/test_ci_shards.py tests/test_ci_workflow.py tests/test_release_images.py
Doku: → T6
Abhängt von: T2

### T4 — R-1341: Server-Shards nach Laufzeit  [x]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/shard_weights.toml, apps/server/tests/test_shard.py, apps/server/tests/shard_weights.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fc70df0bd 2026-11-12T08:05:35+01:00
Review: approve (.ah-out/review/arch-workflow-ci-1/T4.verdict.json)
Änderung: `shard_of_each_file` gewichtet je Datei mit Sekunden je Test × gesammelte Tests aus `shard_weights.toml` (neu, SPDX als Kommentar, Kopf nennt den Befehl zum Neuerzeugen); unbekannte Dateien bekommen den Mittelwert je Test, ohne Tabelle gilt die Testanzahl wie heute. Die Tabelle stammt aus der JUnit-XML des 3.14-Beins eines CI-Laufs dieses Branches (Artefakt aus T3; lokal gemessen nur als Fallback, im Commit-Body genannt). `test_shard.py`: gewichtete Verteilung, Fallback, Reihenfolge-Unabhängigkeit, Manifest unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_shard.py tests/test_ci_shards.py
Doku: → T6
Abhängt von: T3

### T7 — Nachzug T2 (R-1342): review_scripts_test erwartet die concurrency-Gruppe mit merge_group  [x]
Komponente: scripts · Dateien: scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5d183e7d7 2026-11-12T08:13:03+01:00
Review: approve (.ah-out/review/arch-workflow-ci-1/T7.verdict.json)
Änderung: Der Abgleich der `concurrency:`-Zeilen von `ci.yml` (R-0174) erwartet wörtlich die Gruppe vor T2; der Dispatch-Lauf 43169817646 (fc70df0bd) ist deshalb im Job „Ops scripts“ rot (243 passed, 1 failed). Erwartung, Kommentar und Meldung nennen jetzt die Gruppe je Commit auch für `merge_group`; der Vergleich bleibt wörtlich.
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: keine (Test zieht die Konfiguration aus T2 nach)
Abhängt von: T2

### T5 — R-1343: nightly.yml mit schemathesis-tief und backup_restore  [ ]
Komponente: server · Dateien: .github/workflows/nightly.yml, apps/server/tests/test_ci_workflow.py
Änderung: Neuer Workflow (SPDX) mit `schedule`, `workflow_dispatch` und `pull_request` (`paths` nur auf sich selbst). Job schemathesis wie in `ci.yml`, aber `AH_SCHEMATHESIS_EXAMPLES: "100"`, Commit und Beispielzahl in der Job-Summary; Job backup-restore fährt `bash scripts/tests/backup_restore_test.sh`, Exit 75 ist rot. `test_ci_workflow.py` prüft Trigger, Budget, die Schritte und dass kein Job ein Ereignis-`if` trägt. Die Probe auf GitHub-Runnern ist der PR-Lauf dieses Workflows (vor dem Merge, im Bericht an Kevin). Dazu direkt `bash .github/scripts/cache_settings_test.sh`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ci_workflow.py
Doku: → T6

### T6 — Doku: CI-Seite DE+EN, CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/arch-workflow-ci-1.md, DEVELOPMENT.md
Änderung: `cicd.html` DE+EN: Stack-Job auf PRs, Jobs auf PRs vs. `main`/`merge_group`/Dispatch, Pfad-Steuerung mit Fail-safe und Pflicht-Checks, Shards nach Laufzeit (Tabelle neu erzeugen), `nightly.yml`. CHANGELOG-Fragment (Changed, Entwickler-Infrastruktur).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/arch-workflow-ci-1.md
Task-Review: am Ende
Abhängt von: T5

## Entscheidungen
- 2026-11-12 T2: merge_group bekommt eine eigene concurrency-Gruppe je Commit (`ci-merge_group-<sha>`, push bleibt `ci-push-<sha>`), statt die Gruppe nach `github.ref` zu lassen — die Doku sagt eindeutige Queue-Refs nicht zu (nur das Präfix `gh-readonly-queue/{base_branch}`), und ein verdrängter wartender Gruppenlauf hielte den PR in der Queue; Abbruch weiter nur bei pull_request.
- 2026-11-12 T1: DEVELOPMENT.md (Stack-Job „kein PR-Gate“, Reviewer-Nit) zieht T6 nach.
- 2026-11-12 T3: `tasks/**` und `changelog.d/**` zählen zu den engen Bereichen (keine Suite liest sie); sonst schaltete fast jeder PR mit Ledger und Fragment alles ein.
- 2026-11-12 T3: Abweichung von der Spec-Zeile „`server` wird bei `server-legs == '[]'` übersprungen“: `server-legs` ist nie leer, ob `server` läuft, sagt die Ausgabe `server`; `server-result` prüft ein Bein bei `server != 'false'` und `contains(legs, leg)`. Die Doku sagt nicht zu, dass ein `if:` vor der Matrix-Auswertung greift, eine leere Matrix wäre ein Fehler.
- 2026-11-12 T3: Ein PR ohne geänderten Pfad fährt alles (Fail-safe), statt nichts.
- 2026-11-12 T3: Die JUnit-XML des 3.14-Beins ist Artefakt mit `if-no-files-found: warn`, 14 Tage (Quelle für T4).
- 2026-11-12 T3: `test_ci_changes.py` liest den Baum von der Platte, nicht per git: auf einer Box ist `.git` ein toter Zeiger (`scripts/vm/rsync-exclude.txt`).
- 2026-11-12 T3: Der Pfad-Scan der Python-Suiten ist eine Heuristik: er löst auf `__file__` gebaute Pfade auf (`Path()`, `.resolve()`, `.parent`, `.parents[k]`, `/`, `.joinpath`, `.with_name`, `os.path`-Ketten, an solche gebundene Namen; Reviewer-Fund: die frpc-Testdaten unter `apps/agent/internal/frpc/testdata/`, jetzt im Server-Scope), sonst `/`- und `join`-Ketten ab einem Bereichs-Literal und Pfade in Strings; ein Treffer außerhalb der engen Bereiche schaltet ohnehin alles ein. Ausnahmen stehen mit Grund in `_NOT_READ` (Basis des frps-Kontexts und der Plugin-Pakete, Diff-Label in `test_ssrf_parity.py`), die Datei selbst (Pfade als Testdaten) in `_DATA`. Dazu prüft `test_what_a_gated_job_works_in_and_names_lies_in_its_scope` Arbeitsverzeichnis und genannte Pfade jedes gesteuerten Jobs (Lock-Jobs nur die Lock-Dateien, Kevins Trade-off). Gegenprobe: jeder Scope-Eintrag einzeln im Speicher entfernt macht einen Test rot (die `!`-Ausnahmen verbreitern nur), die Lock-Dockerfiles über die Wahrheitstabelle.
- 2026-11-12 T3: `agent-windows` bekommt `docs/**` nicht (Reviewer-Nit, `docs_cli_test.go` liest die Doku): die Windows-Quellen des CLI-Pakets (`run_windows.go`) registrieren weder Befehl noch Flag, den Befehlsbaum prüft der Linux-Job `agent` auf jedem PR; ein Windows-Runner je Doku-PR stünde dagegen.
- 2026-11-12 T3: Die Abgleich-Tests laufen in der Server-Suite; ein PR, der sie nicht fährt, wird auf `main` geprüft (Backstop der Spec). `WANT` (Ausdruck → `'true'`/`'false'` im env) bestätigt der PR-Lauf.
