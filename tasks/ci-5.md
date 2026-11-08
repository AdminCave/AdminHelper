# ruff 0.17.4 mit dem bisherigen Regelsatz — Task-Ledger
Status: erledigt · Branch: feature/ci-5 · Review: am Ende
Spec: docs/features/ci-5.md (Roadmap R-1038)
Heavy: linux-full — `scripts/vm/bootstrap_linux.sh` installiert das ruff der Test-Boxen; der Sammellauf faehrt es
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — ruff-Pins auf 0.17.4, alter Standard-Regelsatz ausdruecklich (R-1038)  [x]
Komponente: scripts · Dateien: ruff.toml, apps/server/requirements-dev.txt, .github/workflows/ci.yml, scripts/vm/bootstrap_linux.sh, changelog.d/ci-5.md
Evidenz: run.sh[quick] server monitoring ca-issuer scripts: 12 passed, 0 failed, 6 skipped @1b8ff1cd9 2026-11-08T07:42:50+01:00
Review: am Ende (Branch-Review)
Änderung: `required-version = "==0.17.4"`, `ruff==0.17.4` in `requirements-dev.txt`, `pip install ruff==0.17.4` in `ci.yml` (Job `python-lint`), `RUFF_VERSION` Default 0.17.4 in `bootstrap_linux.sh`. `ruff.toml` ersetzt `extend-select = ["I"]` durch `select = ["E4", "E7", "E9", "F", "I"]` (der Standard bis 0.15) und sagt im Kommentar, warum. `changelog.d/ci-5.md` (`### Changed`, umlautfrei).
Verify: bash scripts/tests/run.sh lint --strict --only server monitoring ca-issuer scripts
Doku: changelog.d/ci-5.md
