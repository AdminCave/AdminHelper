<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Regression monitoring pytest (2026-11-13) — Task-Ledger
Status: bereit · Branch: feature/reg-2026-11-13-monitoring-pytest · Review: am Ende
Spec: Roadmap R-1418 · Quelle: Wochenlauf 2026-11-13-0130
Heavy: linux-full — der Schritt ist im Wochenlauf rot; der Fix beweist sich auf einer Box (`/test`: `bash scripts/tests/run.sh all --strict --step "monitoring pytest"`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### R1 — Box-venv auf Python 3.14 (R-1418)  [x]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @24f529a5c 2026-11-13T07:00:12+01:00
Review: am Ende (Branch-Review)
Änderung: Ursache: die Box (Ubuntu 24.04) baut das venv der Python-Suiten mit Python 3.12; die zentralen Mail-/TLS-Sensoren rufen `SSLSocket.get_unverified_chain()` (ab Python 3.13), Images und CI laufen auf 3.14. `bootstrap_linux.sh` installiert `python3.14` und `python3.14-venv` aus dem deadsnakes-PPA (Ubuntu noble, apt-signiert); `ensure_venv` in `run.sh` nimmt `python3.14`, wo es installiert ist, sonst `python3`, und baut ein venv, dessen Interpreter eine andere Version hat, mit `--clear` neu (ein warmes Box-venv aus der Zeit vor dem Fix). Test in `run_flags_test.sh`: mit `python3.14` im PATH baut run.sh das venv damit; ein venv mit anderer Version wird mit `--clear` neu gebaut, eines mit gleicher nicht.
Beweis: main@b0d3babff709839e2b29f41a24145924053280e4 · `bash scripts/tests/run.sh all --strict --step "monitoring pytest"` auf der Box → rot mit `AttributeError: 'SSLSocket' object has no attribute 'get_unverified_chain'` (app/central/mail.py:74, venv `python3.12`), erste Box 3x und frische Zweit-VM; grün auf 185870ddf304b2f74e12f894f6ad6cfec204267d (vor fc0124e65)
Semantik: DEVELOPMENT.md:70 „Lock neu erzeugen (im passenden Python wie im Dockerfile, derzeit 3.14)“; scripts/vm/bootstrap_linux.sh:13 „Mirrors the dependency setup in .github/workflows/ci.yml so the box matches CI.“
Dedup-Key: reg:monitoring-pytest
HEAD: b0d3babff709839e2b29f41a24145924053280e4
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (Harness-intern; DEVELOPMENT.md nennt 3.14 schon)

## Beweis (heavy.sh, 2026-11-13-0130)
- Schritt `monitoring pytest` war auf der ersten Box 3x rot, jedes Mal mit demselben Marker: `FAIL  monitoring pytest`
- auf einer frischen zweiten VM (Lane w2) ebenfalls rot
- auf dem letzten PASS-Commit `185870ddf304b2f74e12f894f6ad6cfec204267d` in derselben Lane grün
- Ursache im Log der Zweit-VM: venv unter `python3.12`, 94 Treffer `get_unverified_chain`

## Entscheidungen
- Kevin 2026-11-13: Box-venv auf 3.14 statt Fallback im Code oder Warten auf R-1043.
- deadsnakes-PPA statt uv: apt-signierte Pakete im bestehenden apt-Pfad; dass uv die Prüfsumme des geladenen Python prüft, war in der Doku nicht belegbar.
