<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tauri-Command `enroll_device` entfernen (R-0040) — Task-Ledger
Status: bereit · Branch: feature/remove-enroll-device · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (Kevin hat R-0040 am 2026-10-06 entschieden: entfernen, Doku korrigieren; Ein-Task-Paket, Delegation Kevin 2026-10-05)
Spec: Roadmap R-0040 (Kurz-Ledger ohne Spec)
Heavy: none — entfernt einen registrierten Command, den die UI nie aufruft, samt seinem einzigen Rust-Pfad; das Enrollment mit Einmal-Token (`enroll_with_token`) und der Browser-Export (`export_browser_p12`) bleiben unberührt. Build, clippy, die Rust-Tests und der IPC-Inventar-Test belegen den Schnitt; keine Journey ändert sich.
DoD je Task: CLAUDE.md (Tests grün, cargo fmt und clippy -D warnings sauber, ESLint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac). Kevin hat am 2026-10-06 entschieden: entfernen und die Doku
korrigieren, nicht verdrahten. `enroll_device` (`apps/desktop/src-tauri/src/commands.rs:105`) holt ein Zertifikat
über die Login-Session (`enrollment::enroll`, `apps/desktop/src-tauri/src/enrollment.rs:218`); die UI ruft nur
`enroll_with_token` auf (`apps/desktop/ui/src/lib/bridge/index.ts:111`, ADR 0003). Review am Ende mit einem
Opus-Reviewer, weil der Diff im Enrollment-Pfad liegt.

### T1 — `enroll_device` und `enrollment::enroll` entfernen, Allowlist und Doku nachziehen (R-0040)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts, docs/developer/index.html, docs/en/developer/index.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs desktop-ui: 2 passed, 0 failed, 16 skipped · contracts: 1 ok @6ff0782f 2026-10-06T07:42:09+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Den Command `enroll_device` aus `commands.rs` löschen, ebenso Import und Eintrag in `generate_handler!`
(`main.rs:30`, `:115`) und `enrollment::enroll` (`enrollment.rs:218`), dessen einziger Aufrufer er ist. `mint_token`
bleibt, `export_browser_p12` nutzt es (`enrollment.rs:610`); was danach sonst verwaist (Imports, Hilfsfunktionen nur
für `enroll`, Tests nur dafür), mit entfernen, nichts darüber hinaus. In `ipc.inventory.test.ts` den Eintrag
`enroll_device` aus `UNCALLED_ALLOWLIST` (`:32`) streichen; die Prüfung `:103–106` verlangt dann, dass jeder
registrierte Command einen UI-Aufrufer hat. Doku DE und EN: der Satz „Go-Agent (beim Provisioning), Desktop (nach
Login), frps/Tunnel-Certs“ (`docs/developer/index.html:107`) bzw. „desktop (after login)“
(`docs/en/developer/index.html:85`) nennt für den Desktop den Einmal-Token-Weg (ADR 0003, `enroll_with_token`);
vorher die Stelle und ihre Nachbarsätze lesen, damit der Browser-Export nach dem Login richtig stehen bleibt.
CHANGELOG unter `[Unreleased]` → `### Removed`. ADRs und alte Specs unter `docs/features/` bleiben (Historie).
Beweis: `grep -rn enroll_device apps/desktop/ui/src` ⇒ nur der Allowlist-Eintrag `ipc.inventory.test.ts:32`; Quelle
der Zeile: 8a-Exploration 2026-09-14 (IPC-Inventar-Test, 8a T11).
Dedup-Key: ref:desktop:commands.rs:enroll_device
HEAD: 9fece775
Semantik: Kevin 2026-10-06 (R-0040): „Entfernen, Doku korrigieren“. Heute behauptet `docs/en/developer/index.html:85`
„desktop (after login)“ und `docs/developer/index.html:107` „Desktop (nach Login)“; das Soll ist der Einmal-Token
aus ADR 0003 („Decoupled enrollment … WITHOUT a prior login“, Kommentar über `enroll_with_token`, `commands.rs:115`).
Verify: bash scripts/tests/run.sh quick --strict --only desktop-rs desktop-ui
Doku: docs/developer/index.html · docs/en/developer/index.html · CHANGELOG.md
