<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Backend: quinn-proto 0.11.18 im Lockfile, cargo audit wieder grün (R-0357) — Task-Ledger
Status: erledigt · Branch: feature/quinn-proto-0118 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13: sofort; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0357 (Kurz-Ledger ohne Spec)
Heavy: none — nur `apps/desktop/src-tauri/Cargo.lock` (Patch im selben Minor, kein Code, kein Feature-Wechsel); kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, `cargo fmt` und `cargo clippy -- -D warnings` sauber, CHANGELOG im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen („sofort“).
Stand origin/main@23539b81. Läufe des Desktop-Backends nur mit totem Session-Bus
(`DBUS_SESSION_BUS_ADDRESS=unix:path=<eigener Pfad>/no-bus`).

### T1 — Cargo.lock: quinn-proto 0.11.15 → 0.11.18 (R-0357)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @39816691 2026-10-13T14:26:09+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- In `apps/desktop/src-tauri`: `cargo update -p quinn-proto --precise 0.11.18`, sonst nichts. Kein volles
  `cargo update`, kein anderes `-p`, kein `Cargo.toml`-Edit.
- Erwartete Lockfile-Änderung (Probe `--dry-run` auf origin/main@23539b81, cargo 1.99.0): `quinn-proto`
  0.11.15 → 0.11.18, neu hinzu `chacha20` 0.10.2, `cpufeatures` 0.3.1, `rand` 0.10.3, `rand_core` 0.10.1,
  `rand_pcg` 0.10.2 (Abhängigkeiten von quinn-proto 0.11.18). Weicht das Ergebnis davon ab (andere Pakete
  geändert), ist die Task `[?]` mit dem Diff, nicht still angepasst.
- `cargo audit` (dieselbe Version wie im Audit-Workflow, `.github/workflows/audit.yml`) im Verzeichnis: keine
  Vulnerability mehr; die bekannten `unmaintained`-Warnungen bleiben, sie lassen den Job nicht scheitern. Ist cargo-audit
  lokal nicht installiert, gilt der Nachweis aus dem Audit-Workflow nach dem Push (`gh workflow run audit.yml --ref
  feature/quinn-proto-0118`, Aufsicht).
- CHANGELOG `[Unreleased]`, Abschnitt Security, im Stil des rustls-Eintrags: quinn-proto 0.11.15 → 0.11.18
  (RUSTSEC-2026-0338, -0339, -0340, -0341, -0342; über `quinn` ← `reqwest`), nur der Lockfile-Stand, gefunden vom
  Audit-Sweep.
Rot vorher: Lauf 38395878852 (audit.yml, workflow_dispatch auf harness/go-toolchain-126@211014fb, Stand main),
Job „cargo audit (desktop)“: failure mit fünf Funden in quinn-proto 0.11.15, je „Solution: Upgrade to >=0.11.17“
bzw. „>=0.11.18“. Der Lauf vom 2026-10-12 (38269130931) war in diesem Job noch grün; die Advisories sind neu.
Beweis: origin/main@23539b81, `apps/desktop/src-tauri/Cargo.lock` führt `quinn-proto` 0.11.15 (über `quinn` 0.11.9,
gezogen von `reqwest` 0.12.28); `gh run view 38395878852 --log-failed` → RUSTSEC-2026-0338/0339/0340/0341/0342.
Orakel: analyzer — cargo audit gegen die RustSec-Datenbank
Dedup-Key: rel:desktop-rs:Cargo.lock:quinn-proto
HEAD: 23539b81
Semantik: DEVELOPMENT.md:1314 „`audit.yml` faehrt den woechentlichen CVE-Sweep in CI.“
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG (Security)
