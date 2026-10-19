<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: rustls 0.23.46 — Task-Ledger
Status: bereit · Branch: feature/deps-rustls · Review: am Ende
Spec: Roadmap R-0547
Heavy: linux-full — der Bump ändert die TLS-Bibliothek des Desktop-Binaries (reqwest `rustls-tls`, TOFU-Verifier, mTLS-Client); die Desktop-Journeys laufen im Sammellauf über `main`. Die Windows-Jobs der PR-CI (`cargo test` unter Windows) laufen ohnehin; kein `scenario`, der FRP-Datenpfad bleibt unverändert
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-19: R-0547 angenommen, Kurz-Ledger. Der Dependency-Audit vom 2026-10-19 (`audit.yml`, Lauf 39257407858, Job „cargo audit (desktop)“) ist rot: vier Advisories in `rustls` 0.23.45 (RUSTSEC-2026-0346, -0347, -0348, -0349), behoben ab 0.23.46. Die übrigen Jobs (pip-audit, govulncheck, npm audit) sind grün. `cargo update -p rustls --dry-run` hebt genau ein Paket: `rustls v0.23.45 -> v0.23.46`; `Cargo.toml` bleibt (`rustls = { version = "0.23", … }`).

### T1 — rustls im Desktop-Lockfile auf 0.23.46  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @d6e95190 2026-10-19T15:50:51+02:00
Review: am Ende (Branch-Review)
Änderung: `cargo update --manifest-path apps/desktop/src-tauri/Cargo.toml -p rustls` hebt `rustls` im Lockfile von 0.23.45 auf 0.23.46; kein anderes Paket ändert sich (im Diff prüfen: genau die `version`- und `checksum`-Zeile des Pakets `rustls`). `Cargo.toml` bleibt unverändert. Danach lokal `cargo audit` im Desktop-Verzeichnis: keine Meldung mehr zu `rustls` (die bisher erlaubten Warnungen bleiben); die Zeile `error: … vulnerabilities found` darf nicht mehr erscheinen, das Ergebnis kommt in den Commit-Body. Vor dem Merge zusätzlich `gh workflow run audit.yml --ref feature/deps-rustls` und dessen Job „cargo audit (desktop)“ grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md (Security: Desktop nutzt rustls 0.23.46, die vier Advisories genannt)
Beweis: audit.yml-Lauf 39257407858 (2026-10-19, schedule) — Job „cargo audit (desktop)“: `error: 4 vulnerabilities found!`, alle `Crate: rustls`, `Version: 0.23.45`, `Solution: Upgrade to >=0.23.46`; `apps/desktop/src-tauri/Cargo.lock:3897-3898` (`name = "rustls"`, `version = "0.23.45"`)
Dedup-Key: rel:deps-audit
HEAD: 0ea27174
Semantik: docs/developer/cicd.html:43 — „Wöchentlicher Dependency-Audit (Montag früh, auch manuell per workflow_dispatch): pip-audit (Server- + Monitoring-Locks), cargo audit (Desktop), govulncheck (Agent), npm audit (Web + Desktop-UI)“; ein roter Audit ist eine REL-Zeile und blockiert die nächste Beta
