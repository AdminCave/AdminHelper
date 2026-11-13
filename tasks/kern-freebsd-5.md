<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FreeBSD-Proben auf eigene Adressen, root-Tests im Box-Lauf — Task-Ledger
Status: bereit · Branch: feature/kern-freebsd-5 · Review: am Ende
Spec: docs/features/kern-freebsd-5.md (Roadmap R-1411, R-1412)
Heavy: linux-full — Agent (Proben-Wächter); dazu vor dem Merge `scripts/tests/freebsd_box.sh` auf der FreeBSD-Pool-Box (T1 auf der Plattform, T2 real)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1411: sockstat-Zeile ohne Port überspringen  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sockstat.go, apps/agent/internal/probe/sockstat_test.go, changelog.d/kern-freebsd-5.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @04d08ee76 2026-11-13T05:58:15+01:00
Review: am Ende (Branch-Review)
Beweis: kern-freebsd-3 Box-Lauf 2026-11-12, main@c702ea485: TestHTTPClient*, TestGuardDropsAConnectionAnotherSocketTook rot: sockstat printed a line of unknown form: tcp4 *:* *:*
Dedup-Key: bug:agent:sockstat.go:sockstatListener
Änderung: `parseSockstat` überspringt eine sonst wohlgeformte Zeile, deren lokaler Port `*` ist (ungebundene Socket);
jede andere Form verwirft die Ausgabe weiter. Test zuerst rot: `TestParseSockstatReadsBothForms` bzw. ein neuer Fall
mit `tcp4 *:* *:*` und `tcp46 *:* *:*`.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: changelog.d/kern-freebsd-5.md

### T2 — R-1412: root-Tests von internal/probe in Phase roottests  [x]
Komponente: scripts · Dateien: scripts/tests/box_freebsdbox.sh, scripts/tests/freebsd_box.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5f25dbeba 2026-11-13T06:18:44+01:00
Review: am Ende (Branch-Review)
Änderung: `phase_roottests` fährt dazu die root-Tests von `internal/probe` je Name (getcred, Guard), den pf-Test nur
mit `AH_FREEBSD_PF=1`, das nur `freebsd_box.sh` setzt (nicht `opnsense_box.sh`). Harness-Pfad auf Kevins Wort
(2026-11-13).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Testskript)

## Entscheidungen
