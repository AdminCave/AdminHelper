<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-harness-2 — Task-Ledger
Status: bereit · Branch: feature/kern-harness-2 · Review: am Ende
Spec: docs/features/kern-harness-2.md (Roadmap R-1106, R-1087)
Heavy: linux-full — run.sh installiert die npm-Bäume auf den Boxen neu; Beweis ist der Neustart des roten Sammellaufs 2026-11-02 (Kevin 2026-11-03), der den Schritt desktop-ui vitest wieder fährt
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — npm_ci_if_stale vergleicht einen Lock-Hash-Stempel (R-1106)  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, scripts/dev/worktree-setup.sh, scripts/tests/worktree_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b45f0475 2026-11-03T13:37:21+01:00
Review: am Ende (Branch-Review)
Änderung: `npm_ci_if_stale` installiert, wenn `node_modules/.ah-lock-sha256` fehlt oder nicht dem sha256 von `package-lock.json` entspricht, und schreibt den Stempel nach erfolgreichem `npm ci` über tmp+mv. `worktree-setup.sh` lässt das mtime-`touch` weg. Die Tests stellen auf Stempel um, und ein neuer Fall bildet den Sammellauf-Fehler nach: `node_modules` jünger als der Lock, aber mit dem Stempel eines anderen Locks, führt zu `npm ci`.
Beweis: Sammellauf 2026-11-02-2310 (desktop-ui svelte-check 31x Cannot find module @lucide/svelte) · scripts/tests/run.sh:572 · Dedup-Key: bug:scripts:run.sh:npm_ci_if_stale-mtime (R-1106) · HEAD: 4e0d5f7e
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test worktree_setup_test
Doku: keine (internes Test-Harness, nirgends dokumentiert)

### T2 — VM-Bootstrap auf Node 26, gleich ci.yml (R-1087)  [x]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/tests/harness_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @94784916 2026-11-03T13:39:25+01:00
Review: am Ende (Branch-Review)
Änderung: `NODE_MAJOR` Default 26. `harness_consistency_test.sh` prüft, dass jedes `node-version` in `.github/workflows/ci.yml` dem Default in `bootstrap_linux.sh` entspricht.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Box-Ausstattung, nirgends dokumentiert)
