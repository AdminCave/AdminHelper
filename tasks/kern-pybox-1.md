# Box-Python ohne PPA — Task-Ledger
Status: erledigt · Branch: feature/kern-pybox-1 · Review: am Ende
Spec: Roadmap R-1789
Heavy: linux-full — der Beweis ist eine frische Box aus der alten Vorlage (ohne python3.14), die per `warm.sh desktop` bootstrappt und `run.sh all --strict --step agent_monitoring` fährt; vor dem Merge, weil der Fix die Box-Leases selbst betrifft
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Semantik: keine Stelle in docs/ — gesucht `deadsnakes`, `python3.14`, `bootstrap_linux` in docs/ und DEVELOPMENT.md; die Absicht steht nur im Kommentar `scripts/vm/bootstrap_linux.sh:146` („The services run on the Python of their Dockerfiles (python:3.14-slim)“). Der Fix ändert die Quelle, nicht die Absicht.

### T1 — python3.14 der Boxen aus gepinntem python-build-standalone statt deadsnakes-PPA  [x]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/tests/harness_consistency_test.sh, DEVELOPMENT.md, changelog.d/kern-pybox-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @402ac9577 2026-11-25T20:55:43+01:00
Review: am Ende (Branch-Review)
Änderung: `bootstrap_linux.sh` installiert python3.14 aus dem `install_only`-Archiv von astral-sh/python-build-standalone (Version, Release-Datum und sha256 als `${AH_…:-…}`-Defaults, 3.14.10 wie `python:3.14-slim`), prüft die sha256 vor dem Entpacken, legt es unter `/opt/ah-python/<version>` ab und verlinkt `/usr/local/bin/python3.14`; idempotent über die exakte Version, `curl --retry`. Das deadsnakes-PPA fällt weg. `harness_consistency_test.sh` prüft: kein `deadsnakes` im Bootstrap, Pin mit 64-hex-sha256, Minor des Pins = Minor des `FROM python:` der Dockerfiles.
Beweis: kern-session 2026-11-25 (PPA InRelease 503, Paket-Downloads Ign; zwei `--step`-Läufe infra) · Dedup-Key: BUG:scripts:bootstrap_linux.sh:deadsnakes-ppa
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: DEVELOPMENT.md (Abschnitt VMs, eine Zeile zur Box-Python-Quelle) · changelog.d/kern-pybox-1.md

## Entscheidungen
- python-build-standalone statt PPA mit Retry: GitHub ist für die Boxen ohnehin Pflicht (oasdiff, Repo), das Archiv ist per sha256 reproduzierbar und trifft die Patch-Version der Dockerfiles; ein zweiter Paketquellen-Fallback wäre mehr Code für denselben Zweck.
- Nach dem Merge backt die Session `linux-full` und `linux-server` neu (Pool `adminhelper-ci`), damit frische Leases python3.14 schon tragen und gar nichts mehr laden; das ist Betrieb, kein Commit.
- R-1419 (Version an Dockerfile koppeln, run.sh/toolchain-lockstep.sh) bleibt in kern-harness-10: run.sh überlappt feature/harness-hygiene-1; die Minor-Prüfung hier deckt nur den neuen Pin.
