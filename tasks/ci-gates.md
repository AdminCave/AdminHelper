<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI-Gates: Image-Tests im Server-Job, Skip-Gate, Keyring in ops-scripts, Playwright-Install — Task-Ledger
Status: erledigt · Branch: feature/ci-gates · Review: pro Task
Spec: docs/features/ci-gates.md (Roadmap R-0808, R-0475, R-0500, R-0588)
Heavy: none — nur der CI-Workflow, Struktur-Tests, ein hermetisches Test-Skript und Doku; kein Stack-, Gateway-, PKI-, FRP-, Compose- oder Install-Pfad. Der Beweis der Workflow-Änderungen ist die PR-CI (3.13-Leg des server-Jobs, ops-scripts, Web-Frontend E2E), nicht eine VM
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Der Playwright-Job installiert nur Chromium, der Install-Schritt hat eine Frist von 10 min (R-0808). (2) Die
3.13-Leg des server-Jobs zieht die Basis-Images aller Image-Tests, und ein übersprungener Test macht sie rot (R-0475).
(3) Der Kommentar im Job agent-windows kommt ohne Zahl aus (R-0500). (4) ops-scripts installiert gnome-keyring,
`lib_e2e_stack_test.sh` endet ohne Keyring-Werkzeuge mit 75 (R-0588). Zeilenangaben: origin/main@b25c65a6; der
builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Jede Task ändert `.github/workflows/ci.yml` (Risikopfad in `scripts/dev/review-risk.txt`, kein Harness-Pfad):
  zusätzlich `security`. Den PR merged Kevin (CLAUDE.md §2), nicht die Session.
- Es gibt kein lokales CI. Lokal beweisen Struktur-Tests in `apps/server/tests/test_release_images.py` (Hilfen
  `_workflow`, `_step`, `_run_step`, `:101-133`; `_run_step` führt den `run:`-Text mit `bash -e` aus, Werkzeuge als
  Stubs vorn im `PATH`) bzw. das Test-Skript selbst. Der eigentliche Beweis ist die PR-CI; die Session nennt die
  Summary-Zeilen der betroffenen Jobs im PR-Text.
- Reihenfolge: T3 hängt an T2 und am grünen Dispatch-Lauf nach T2; T1, T4, T5 sind unabhängig. Alle teilen `ci.yml`,
  also nacheinander.
- Neue Strings (Kommentare, Meldungen) englisch.

### T1 — Playwright-Job: nur Chromium, Install-Schritt mit eigener Frist (R-0808)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_release_images.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @bbc49b87 2026-10-23T06:20:27+02:00
Review: approve (.ah-out/review/ci-gates/T1.verdict.json)
Änderung: Im Job `frontend-e2e` (`ci.yml:490-517`) wird der Schritt „Install Playwright browsers“ (`:504-506`) zu `npx playwright install --with-deps chromium` (wie `scripts/tests/run.sh:928` und `scripts/tests/web_live.sh:42`) und bekommt `timeout-minutes: 10` (gemessen 44–125 s, Job-Frist `:493` 30 min). Ein Kommentar über dem Schritt nennt das Warum: ohne Browser-Argument zieht apt die Abhängigkeiten aller Browser (gstreamer/ffmpeg für webkit/firefox), daran hing Lauf 39767066088; ein Browser-Cache hilft nicht, weil der Hänger in apt lag. Kein Cache, kein Retry (Spec, Nicht-Ziele). Test in `test_release_images.py`: (a) der Schritt hat ein ganzzahliges `timeout-minutes`, kleiner als das des Jobs; (b) `_run_step` mit einem `npx`-Stub, der seine Argumente ausgibt: genau `playwright install --with-deps chromium`. Zuerst rot: (a) und (b) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: docs/developer/cicd.html:40 + docs/en/developer/cicd.html:40 (bei „Playwright-E2E“: nur Chromium, der Install-Schritt hat eine Frist von 10 min, damit ein hängender apt-Spiegel nicht den ganzen Job blockiert)
Beweis: origin/main@b25c65a6 · Lauf 39767066088 (PR #262), Job 119785048681: Schritt „Install Playwright browsers“ 10:59:30–11:29:36 UTC, abgebrochen mit dem Job; apt „8 upgraded, 181 newly installed“, „Need to get 119 MB“, 26 Zeilen „Ign:“ von azure.archive.ubuntu.com im 30-s-Takt, letzte Zeile „Get:85 … libavfilter9“, der Browser-Download begann nie; Re-Run 47 s. Lokal: der neue Test auf HEAD rot (kein `timeout-minutes`, kein `chromium`)
Orakel: contract — die Install-Zeile nennt nur `chromium`, der Schritt hat eine Frist unter der des Jobs
Metrik: playwright-core 1.60.0, Paketliste `ubuntu24.04-x64`: 12 tools + 21 chromium + 25 firefox + 52 webkit = 110 → 12 + 21 = 33 direkte Pakete (vor dem Entdoppeln)
Dedup-Key: bug:ci:ci.yml:playwright-install-hang
HEAD: b25c65a6

### T2 — server-Job: die 3.13-Leg zieht die Basis-Images aller Image-Tests (R-0475)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_release_images.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @ab435f57 2026-10-23T06:29:14+02:00
Review: approve (.ah-out/review/ci-gates/T2.verdict.json)
Änderung: Der Schritt „Pull the base of the frps image“ (`ci.yml:86-88`, `if: matrix.python-version == '3.13'`) wird zu „Pull the base images of the image tests“ und zieht die `FROM`-Referenzen von `apps/frps/Dockerfile` (frps-Tests), `apps/gateway/Dockerfile` (nginx, Docker-Tests von `test_gateway_container.py` aus feature/compose-hardening) und `apps/ca-issuer/Dockerfile` (python:3.12-slim, die Fixture `box` in `apps/server/tests/test_images_exec_only.py:204-228`), abgeleitet aus den Dockerfiles wie heute per `sed`, kein zweiter Digest. `timeout-minutes` des server-Jobs (`:33`) von 15 auf 20 (3.13-Leg heute 12:21–12:34). Der Test `test_the_server_job_pulls_the_base_of_the_frps_image_before_its_tests` (`test_release_images.py:362-376`) wird durch einen genaueren ersetzt: Schritt vor „Run pytest“, gleiches `if:`, `docker`-Stub; gezogen werden genau `_image()[0]` (`test_frps_supervisor.py:2021`), `_base()` (`test_images_exec_only.py:142-147`) und die `FROM`-Referenz aus `apps/gateway/Dockerfile:1`, jede einmal. Docstring `test_release_images.py:17-18` und `_PULL_STEP` (`:49`) nachziehen. Zuerst rot: der neue Test auf HEAD (nur frps gezogen).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: docs/developer/cicd.html:40 + docs/en/developer/cicd.html:40 (statt nur `apps/frps/Dockerfile`: die Basis-Images von frps, Gateway und der Python-Images, damit die Image-Tests laufen statt zu überspringen)
Test-Löschung: apps/server/tests/test_release_images.py::test_the_server_job_pulls_the_base_of_the_frps_image_before_its_tests — ersetzt durch den genaueren Test über alle drei Basis-Images im selben Commit
Beweis: origin/main@b25c65a6 · Lauf 39768448078, server (3.13): „1926 passed, 4 skipped“; `pytest --co` belegt die 4 als die Container-Tests von `test_images_exec_only.py` (`:231`, `:245`, `:261`, `:292`), deren Basis kein Job zieht. Danach dispatcht die Session `gh workflow run ci.yml --ref feature/ci-gates` und erwartet in der 3.13-Leg „0 skipped“ und grün; ein roter Image-Test wird eine eigene Task vor T3 (Plan-Nachtrag), kein Skip, kein abgeschalteter Test
Dedup-Key: ref:ci:ci.yml:server-pytest-strict
HEAD: b25c65a6

### T3 — server-Job: in der 3.13-Leg macht ein übersprungener Test den Job rot (R-0475)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_release_images.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @edf0c1a6 2026-10-23T07:52:04+02:00
Review: approve (.ah-out/review/ci-gates/T3.verdict.json)
Änderung: „Run pytest“ (`ci.yml:89-94`) schreibt JUnit-XML (`--junitxml` unter `$RUNNER_TEMP`) und bekommt `-rs`. Direkt danach ein neuer Schritt „No test skipped“ mit demselben `if: matrix.python-version == '3.13'`: Python-stdlib liest die JUnit-Datei, gibt für jeden `<skipped>` `classname::name: message` aus und endet ≠ 0; eine fehlende oder unlesbare Datei ist ebenfalls rot. Struktur-Tests per `_run_step` mit Fixture-Dateien: (a) ohne Skip → rc 0; (b) ein Skip → rc ≠ 0, Test-ID und Grund in der Ausgabe; (c) keine Datei → rc ≠ 0; (d) Reihenfolge, gleiches `if:`, und der Pfad, den der pytest-Befehl schreibt, ist der, den der Schritt liest. Zuerst rot: der neue Test auf HEAD (Schritt fehlt).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: docs/developer/cicd.html:40 + docs/en/developer/cicd.html:40 (die 3.13-Leg ist rot, sobald ein Test übersprungen wird) · docs/developer/cicd.html:89 + docs/en/developer/cicd.html:90 (test-skips: in CI prüft die 3.13-Leg des server-Jobs jeden Skip, nicht nur Pflicht-Tests)
Abhängt von: T2 und dem grünen Dispatch-Lauf danach („0 skipped“ in der 3.13-Leg)
Dedup-Key: ref:ci:ci.yml:server-pytest-strict
HEAD: b25c65a6

### T4 — Job agent-windows: Kommentar ohne Zählung (R-0500)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4660cd55 2026-10-23T06:36:33+02:00
Review: approve (.ah-out/review/ci-gates/T4.verdict.json)
Änderung: Der Kommentar `ci.yml:410-415` („Seven files are windows-tagged … exactly one of them has a test“) wird ohne Zahlen neu gefasst: `GOOS=windows go vet` auf Ubuntu kompiliert nur; hier laufen die plattformübergreifenden und die windows-getaggten Tests (`*_windows_test.go`), die kein anderer Job ausführt; hart mit Absicht (kein `continue-on-error`). Nur der Kommentar, kein Schritt ändert sich. Das Verify zeigt, dass `ci.yml` weiter lädt und die Struktur-Tests grün bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Kommentar; die Doku nennt die Zahl nirgends, grep über docs/, DEVELOPMENT.md, README.md ohne Treffer)
Beweis: origin/main@b25c65a6 · `find apps/agent -name '*_windows.go' | wc -l` → 9, `find apps/agent -name '*_windows_test.go' | wc -l` → 8
Dedup-Key: ref:ci:ci.yml:agent-windows-comment
HEAD: b25c65a6

### T5 — ops-scripts installiert gnome-keyring; lib_e2e_stack_test.sh endet ohne Keyring-Werkzeuge mit 75 (R-0588)  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, scripts/tests/lib_e2e_stack_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c35ac708 2026-10-23T06:52:35+02:00
Review: approve (.ah-out/review/ci-gates/T5.verdict.json)
Änderung: ops-scripts (`ci.yml:833-874`) bekommt neben „Install minisign“ (`:849-850`) einen Schritt `sudo apt-get install -y -qq --no-install-recommends gnome-keyring` mit Kommentar wie bei minisign (ohne ihn endet `lib_e2e_stack_test.sh` mit 75, `--strict` macht das rot). `dbus-run-session`, `dbus-send`, `python3`, `pgrep` hat der Runner schon (Log: nur `gnome-keyring-daemon` fehlt). In `scripts/tests/lib_e2e_stack_test.sh` bleibt die Fallauswahl (`:797-809`); das Ende (`:885-886`) wird: rot bei `FAIL > 0`, sonst Exit 75 mit Meldung, wenn `KR_MISSING` nicht leer ist, sonst 0. Gegenprobe des builders in einem Probe-Worktree (nicht im Bau-Worktree): ein Werkzeug per `PATH` verdeckt → rc 75; mit Werkzeugen → rc 0.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: DEVELOPMENT.md (Absatz neben oasdiff `:321-325`: der Pflicht-Schritt `scripts` braucht gnome-keyring, dbus-run-session und dbus-send, sonst endet `lib_e2e_stack_test.sh` mit 75; CI-Job ops-scripts und die Test-Boxen installieren es) · docs/developer/cicd.html:82 + docs/en/developer/cicd.html:83 (bei „Exit 75 heisst SKIP“: auch die Keyring-Fälle von `lib_e2e_stack_test.sh`)
Beweis: origin/main@b25c65a6 · Lauf 39768448078, ops-scripts: „lib_e2e_stack_test: 82 passed, 0 failed, 6 skipped“, sechs Zeilen „SKIP keyring …: not available: gnome-keyring-daemon“, Exit 0. Nach T5 erwartet die PR-CI „88 passed, 0 failed, 0 skipped“; die Sekunden von Fall (b) (`:739`, Grenze 7 s) auf dem Runner gehören in den PR-Text
Dedup-Key: ref:ci:lib_e2e_stack_test.sh:keyring-skip
HEAD: b25c65a6

### T6 — CA-Issuer-Jobs mit Postgres-Dienst: die pg_engine-Tests laufen in der CI (R-0820)  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, apps/server/tests/test_release_images.py, docs/developer/cicd.html, docs/en/developer/cicd.html, scripts/tests/stack_pytest.sh
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e52ecdf2 2026-10-23T07:01:38+02:00
Review: approve (.ah-out/review/ci-gates/T6.verdict.json)
Änderung: Die Jobs `ca-issuer` (`ci.yml:156-176`) und `python-lock-ca-issuer` (`:278-300`) bekommen je einen `services.postgres` wie `python-lock-server` (`:192-205`: `postgres:17-alpine`, Benutzer `adminhelper`, Passwort `cipw`, DB `adminhelper`, Port 5432, Healthcheck) und `env: AH_TEST_DB: postgresql+psycopg://adminhelper:cipw@localhost:5432/adminhelper`; ohne Redis (der ca-issuer braucht keinen). `CA_ALLOW_MEMORY_STORE` bleibt (conftest setzt es, der übrige Testlauf nutzt den Speicher-Store); kein `DATABASE_URL`. Der Kommentar `:175` („no DB service needed“) wird ersetzt: die Suite nutzt den Speicher-Store, die pg_engine-Tests in `test_db_token_store.py` (TOCTOU, Nebenläufigkeit) brauchen den Postgres-Dienst über `AH_TEST_DB` und werden ohne ihn übersprungen. Neuer Struktur-Test in `test_release_images.py` mit den Hilfen `_workflow`/`_step`: beide CA-Issuer-Jobs haben `services.postgres` und ein `AH_TEST_DB`, das auf `postgresql` zeigt; zuerst rot gegen den Stand ohne die Änderung.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (nur, wenn die Seite die CA-Issuer-Jobs oder ihre Dienste beschreibt: Postgres-Dienst für die Nebenläufigkeits-Tests; sonst keine, grep belegt im Commit-Body)
Beweis: origin/main@b25c65a6 · `ci.yml:156-176` und `:278-300` ohne `services:`; `apps/ca-issuer/tests/test_db_token_store.py:104-108` überspringt ohne `AH_TEST_DB` mit Postgres-URL; PR #270 Lauf 39776102278, Job CA-Issuer (pytest): Laufzeit 29 s ohne DB. Nach T6 nennt der PR-Text die Summary-Zeile beider CA-Issuer-Jobs mit den sechs pg_engine-Tests als passed (`pytest -q -rs` zeigt keine Skips aus `test_db_token_store.py`)
Dedup-Key: bug:ci:ca-issuer-no-postgres
HEAD: b25c65a6
