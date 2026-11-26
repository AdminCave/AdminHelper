# Netz-Aussetzer und Haenger in Bake, Bootstrap und Images — Task-Ledger
Status: aktiv · Branch: feature/kern-netretry-1 · Review: am Ende
Spec: docs/features/kern-netretry-1.md (Roadmap R-1794, R-1795, R-1797, R-1798)
Heavy: linux-full — die Dockerfiles bauen den Stack (Sammellauf); dazu vor dem Merge ein `vm.py bake --profile linux-full`, dessen Warm-Schritt mit Exit 0 endet (Beweis fuer R-1794 und den Bootstrap)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Semantik: keine Stelle in docs/ — gesucht `WARMUP`, `warm the caches`, `retry` in docs/ und DEVELOPMENT.md; die Absicht steht im Kommentar `scripts/vm/vm.py:1976` („this is what fills ~/.cargo, ~/go and node_modules“). Der Fix stellt diese Absicht her.

### T1 — vm.py: Aufwaermen ohne Testschritte, rsync mit I/O-Grenze  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, DEVELOPMENT.md, changelog.d/kern-netretry-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8da5da870 2026-11-26T06:48:52+01:00
Review: am Ende (Branch-Review)
Änderung: Der Warm-Schritt in `bake_linux` faehrt `run.sh unit --exclude monitoring-pytest ca-issuer-pytest server-pytest schemathesis scripts vm-pytest dev-pytest`; `rsync()` setzt `--timeout=300`. Tests: der Warm-Befehl schliesst genau die Testschritte aus und jede ausgeschlossene ID ist eine Step-ID von `run.sh`; `rsync` traegt `--timeout`.
Beweis: bake linux-full 3903 / linux-server 3905 2026-11-25, „warm the caches exited 255“ in server pytest · Dedup-Key: BUG:scripts:vm.py:warmup-limit (R-1794), REF:scripts:vm.py:rsync-timeout (R-1798)
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: DEVELOPMENT.md (vm.py-Tabelle, Zeile `bake`) · changelog.d/kern-netretry-1.md

### T2 — bootstrap_linux.sh: Downloads mit Wiederholung und Stall-Grenze  [x]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/tests/harness_consistency_test.sh, changelog.d/kern-netretry-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f1abaa30d 2026-11-26T06:53:25+01:00
Review: am Ende (Branch-Review)
Änderung: apt bekommt `Acquire::Retries` und `Acquire::http(s)::Timeout` als Datei unter `/etc/apt/apt.conf.d/`; die pip3-Installs laufen mit `PIP_RETRIES`/`PIP_DEFAULT_TIMEOUT` und einer aeusseren Wiederholung; jede curl traegt `--retry 5 --retry-all-errors --connect-timeout 30 --speed-limit 1024 --speed-time 60` (auch Docker-GPG und rustup); `cargo install` mit `CARGO_NET_RETRY`. `harness_consistency_test.sh` prueft, dass jede curl des Bootstraps `--retry` und `--connect-timeout` traegt.
Beweis: bake linux-server 2026-11-25 ReadTimeoutError files.pythonhosted.org bei `pip3 install pytest` · Dedup-Key: BUG:scripts:bootstrap_linux.sh:pip-retry (R-1795), R-1797, R-1798
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: changelog.d/kern-netretry-1.md

### T3 — Dockerfiles: apt, pip und npm mit Wiederholung  [x]
Komponente: scripts · Dateien: Dockerfile, apps/ca-issuer/Dockerfile, apps/monitoring/Dockerfile, scripts/tests/xrdp-gfx/Dockerfile, scripts/tests/harness_consistency_test.sh, changelog.d/kern-netretry-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8808fcd85 2026-11-26T07:01:59+01:00
Review: am Ende (Branch-Review)
Änderung: `apt-get` mit `-o Acquire::Retries=5`, `pip install` mit `--retries 10 --timeout 60`, `npm ci` mit `--fetch-retries 5`; Paketstand und `--require-hashes` unveraendert. `harness_consistency_test.sh` prueft die Optionen je Dockerfile. Lokal `docker build` der drei Service-Images als Beleg im Commit-Body.
Beweis: Box-Beweis kern-pybox-1 2026-11-25, Docker-Build „alembic==1.20.1 from versions: none“ · Dedup-Key: R-1797
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: changelog.d/kern-netretry-1.md

### T4 — test_images_exec_only.py: Muster kennen die Wiederholungs-Optionen  [ ]
Komponente: server · Dateien: apps/server/tests/test_images_exec_only.py
Änderung: Aus der PR-CI (#678): zwei Tests lesen die Dockerfiles mit festen Mustern und kennen `apt-get -o …` und `pip install --retries … --timeout …` nicht. Das Install-Muster laesst `-o <opt>` zwischen `apt-get` und `install` zu; das pip-Muster verlangt jetzt `--retries` und `--timeout` vor `--no-cache-dir --require-hashes` (strenger, nicht schwaecher).
Beweis: PR #678 Server (pytest, image lock, shard 2/4): test_each_image_ends_its_last_stage_… `{'pip'} == {'apt-get','pip'}`, test_each_image_removes_pip_… `assert None` · Dedup-Key: R-1797
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: keine (Test)

## Entscheidungen
- R-1796 (security-Nit zu `/tmp/ah-python.tgz`) faehrt nicht mit: Zeile `neu`, Kevins Triage; T2 aendert an der curl nur die Optionen.
- T3: `apps/frps/Dockerfile` (apk) faehrt nicht mit: eine apk-Wiederholungsoption ist nicht in der Doku verifiziert; Fund fuer eine eigene Zeile, falls frps-Builds wackeln.
- T2: Downloads, die vorher in eine Pipe gingen (Docker-GPG, nodesource, rustup), laufen jetzt in eine `mktemp`-Datei: ein Retry nach einem Teil-Body haette den ganzen Body hinter den gelesenen Teil gehaengt.
