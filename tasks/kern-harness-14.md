<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-harness-14 — Box-Bootstrap mit Pins, OPNsense-Vorlage, Ledger-Feld — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-14 · Review: pro Task
Spec: docs/features/kern-harness-14.md (Roadmap R-1364, R-1824, R-1803, R-1796, R-1800)
Heavy: linux-full — frische Box bootstrappt mit dem geänderten bootstrap_linux.sh (warm.sh desktop) und Bake base-opnsense mit Lease daraus, vor dem Merge (Kevin 2026-11-27)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-27 R-1824: Feld `Assertion-Änderung:` entfernen, die Lint-Prüfung samt ihren Fällen in scripts/tests/ledger_test.sh geht mit.
- R-1803, Nit zur Entscheidung in tasks/kern-netretry-1.md: das Ledger ist erledigt und Geschichte; hier festgehalten: `apps/gateway/Dockerfile` (`apk upgrade`) bleibt aus demselben Grund wie `apps/frps/Dockerfile` ohne Wiederholung.

### T1 — R-1824: Ledger-Feld Assertion-Änderung entfernen  [x]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a99cc5035 2026-11-27T17:07:28+01:00
Review: approve (.ah-out/review/kern-harness-14/T1.verdict.json)
Änderung: `ledger.sh lint` prüft nur noch `Test-Löschung:` (Form und eine Zeile je Task); die Fälle für `Assertion-Änderung:` in ledger_test.sh gehen, die für `Test-Löschung:` bleiben.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: keine (tasks/README.md beschreibt das Feld nicht)

### T2 — R-1796, R-1803: Box-Bootstrap: Temp-Dateien, pip-Pause, Kommentare  [x]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/vm/vm.py, scripts/tests/harness_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @725351a44 2026-11-27T20:27:17+01:00
Review: approve (.ah-out/review/kern-harness-14/T2.verdict.json)
Änderung: Python, oasdiff, Go und frpc laden in ein `mktemp -d` statt nach festen `/tmp`-Namen; `pip_install` schläft nicht nach dem letzten Versuch; der oasdiff-Kommentar nennt die Leases statt des Bake-Warmlaufs; der Kommentar an `WARMUP_EXCLUDE` sagt, dass die Vorlage ohne Python-Venv-Cache bleibt. harness_consistency_test verlangt: kein fester `/tmp/`-Pfad in bootstrap_linux.sh.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Kommentare und Temp-Pfade)

### T3 — R-1800: Docker-Schlüssel, nodesource und rustup gepinnt  [x]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/tests/harness_consistency_test.sh, DEVELOPMENT.md, changelog.d/kern-harness-14.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3cc6782da 2026-11-27T20:38:52+01:00
Review: approve (.ah-out/review/kern-harness-14/T3.verdict.json)
Änderung: Docker-Schlüssel nur mit dem Fingerprint aus der Spec (sonst Abbruch); nodesource in der Form aus Kevins Antwort (Empfehlung: Repo als deb822 von Hand, Schlüssel per Fingerprint, Apt-Pin wie das Setup-Skript); rustup-init aus dem Archiv mit gepinnter Version und sha256. harness_consistency_test verlangt die Pins (Fingerprint 40 Hex, sha256 64 Hex) und keinen Download eines Skripts, das ausgeführt wird.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: DEVELOPMENT.md (Box-Bootstrap: was gepinnt ist) · changelog.d/kern-harness-14.md
Abhängt von: T2

### T4 — R-1364: OPNsense: shellcheck, sshd-Prüfung, rc.conf der Vorlage  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/vm/vm.py, scripts/vm/tests/test_vm.py
Änderung: der shellcheck-Schritt nimmt `scripts/vm/opnsense/*.sh` mit (als sh, wie der Inhalt es verlangt); `OPNSENSE_CHECK` fragt `/usr/local/sbin/sshd -T` (Form der Ausgabe auf einer Probe-Box belegt); `OPNSENSE_CLEAN` entfernt die rc.conf-Zeilen aus base-freebsd (`sysrc -x`), die eine OPNsense-Lease nicht braucht, belegt durch Bake und Lease.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Harness-intern)
