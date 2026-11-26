# Netz-Aussetzer und Haenger in Bake, Bootstrap und Images — Task-Ledger
Status: geplant · Branch: feature/kern-netretry-1 · Review: am Ende
Spec: docs/features/kern-netretry-1.md (Roadmap R-1794, R-1795, R-1797, R-1798)
Heavy: linux-full — die Dockerfiles bauen den Stack (Sammellauf); dazu vor dem Merge ein `vm.py bake --profile linux-full`, dessen Warm-Schritt mit Exit 0 endet (Beweis fuer R-1794 und den Bootstrap)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Semantik: keine Stelle in docs/ — gesucht `WARMUP`, `warm the caches`, `retry` in docs/ und DEVELOPMENT.md; die Absicht steht im Kommentar `scripts/vm/vm.py:1976` („this is what fills ~/.cargo, ~/go and node_modules“). Der Fix stellt diese Absicht her.

### T1 — vm.py: Aufwaermen ohne Testschritte, rsync mit I/O-Grenze  [ ]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, DEVELOPMENT.md, changelog.d/kern-netretry-1.md
Änderung: Der Warm-Schritt in `bake_linux` faehrt `run.sh unit --exclude monitoring-pytest ca-issuer-pytest server-pytest schemathesis scripts vm-pytest dev-pytest`; `rsync()` setzt `--timeout=300`. Tests: der Warm-Befehl schliesst genau die Testschritte aus und jede ausgeschlossene ID ist eine Step-ID von `run.sh`; `rsync` traegt `--timeout`.
Beweis: bake linux-full 3903 / linux-server 3905 2026-11-25, „warm the caches exited 255“ in server pytest · Dedup-Key: BUG:scripts:vm.py:warmup-limit (R-1794), REF:scripts:vm.py:rsync-timeout (R-1798)
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: DEVELOPMENT.md (vm.py-Tabelle, Zeile `bake`) · changelog.d/kern-netretry-1.md

### T2 — bootstrap_linux.sh: Downloads mit Wiederholung und Stall-Grenze  [ ]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/tests/harness_consistency_test.sh, changelog.d/kern-netretry-1.md
Änderung: apt bekommt `Acquire::Retries` und `Acquire::http(s)::Timeout` als Datei unter `/etc/apt/apt.conf.d/`; die pip3-Installs laufen mit `PIP_RETRIES`/`PIP_DEFAULT_TIMEOUT` und einer aeusseren Wiederholung; jede curl traegt `--retry 5 --retry-all-errors --connect-timeout 30 --speed-limit 1024 --speed-time 60` (auch Docker-GPG und rustup); `cargo install` mit `CARGO_NET_RETRY`. `harness_consistency_test.sh` prueft, dass jede curl des Bootstraps `--retry` und `--connect-timeout` traegt.
Beweis: bake linux-server 2026-11-25 ReadTimeoutError files.pythonhosted.org bei `pip3 install pytest` · Dedup-Key: BUG:scripts:bootstrap_linux.sh:pip-retry (R-1795), R-1797, R-1798
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: changelog.d/kern-netretry-1.md

### T3 — Dockerfiles: apt, pip und npm mit Wiederholung  [ ]
Komponente: scripts · Dateien: Dockerfile, apps/ca-issuer/Dockerfile, apps/monitoring/Dockerfile, scripts/tests/xrdp-gfx/Dockerfile, scripts/tests/harness_consistency_test.sh, changelog.d/kern-netretry-1.md
Änderung: `apt-get` mit `-o Acquire::Retries=5`, `pip install` mit `--retries 10 --timeout 60`, `npm ci` mit `--fetch-retries 5`; Paketstand und `--require-hashes` unveraendert. `harness_consistency_test.sh` prueft die Optionen je Dockerfile. Lokal `docker build` der drei Service-Images als Beleg im Commit-Body.
Beweis: Box-Beweis kern-pybox-1 2026-11-25, Docker-Build „alembic==1.20.1 from versions: none“ · Dedup-Key: R-1797
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: changelog.d/kern-netretry-1.md

## Entscheidungen
- R-1796 (security-Nit zu `/tmp/ah-python.tgz`) faehrt nicht mit: Zeile `neu`, Kevins Triage; T2 aendert an der curl nur die Optionen.
