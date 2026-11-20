# agent-install.sh: TOFU-Ausweg nennt --ca-fp — Task-Ledger
Status: bereit · Branch: feature/ops-13 · Review: am Ende
Spec: docs/features/ops-13.md (Roadmap R-1648)
Heavy: none — nur der Text einer Warnung, der Stub-Test in scripts deckt den Zweig
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1648: TOFU-Ausweg nennt --ca-fp  [x]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, changelog.d/ops-13.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @79dc9709b 2026-11-20T09:07:31+01:00
Review: am Ende (Branch-Review)
Änderung: Die Warnung im Fallback-Zweig ohne `--ca-fp`-Unterstützung sagt, nach dem Server-Update neu mit neuem Token und `--ca-fp` zu provisionieren. Der Test des Fallbacks prüft das, erst rot.
Beweis: reviewer ops-11 2026-11-19 (feature/ops-11@c9efedcea scripts/agent-install.sh:396)
Dedup-Key: ref:scripts:agent-install.sh:tofu-ca-fp
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: changelog.d/ops-13.md
