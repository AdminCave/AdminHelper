# kern-desktop-e2e-2 — Task-Ledger
Status: geplant · Branch: feature/kern-desktop-e2e-2 · Review: am Ende
Spec: docs/features/kern-desktop-e2e-2.md (Roadmap R-0573)
Heavy: linux-full — Desktop-Journey (settings-enroll.live.js läuft in desktop_e2e_tunnel); nur Testcode
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0573: werfender invoke-Helfer in settings-enroll.live.js  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js
Beweis: reviewer desktop-fixes-2 T4, 2026-10-21 (Code-Lesung): apps/desktop/e2e/test/specs/settings-enroll.live.js:151 und :201 lesen nur .value
Dedup-Key: ref:desktop-e2e:settings-enroll.live.js:invoke-rejection-text
Änderung: Helfer `invokeValue(cmd, args)` wie `invoke` in `tunnel-connect.live.js:36` (wirft `${cmd} failed: <Text>` bei `rejected`, liefert sonst `value`); Zeile 151 und 201 nutzen ihn. Die GUI-Spec selbst läuft im Sammellauf (`desktop_e2e_tunnel`), lokal nur Lint.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testcode)
