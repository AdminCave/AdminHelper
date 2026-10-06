<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tunnel-Hinweis ohne Login-Enrollment (R-0203) — Task-Ledger
Status: bereit · Branch: feature/desktop-enroll-hint · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (kleines Fund-Paket aus R-0203, von Kevin am 2026-10-06 in der Triage angenommen; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0203 (Kurz-Ledger ohne Spec)
Heavy: none — eine Fehlermeldung im Rust-Backend des Desktops; kein Journey-Pfad ändert sich (der Tunnel startet wie bisher nur mit einer Identität).
DoD je Task: CLAUDE.md (Tests grün, cargo fmt und clippy -D warnings sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac) aus R-0203, von Kevin in der Triage vom 2026-10-06 angenommen.
Seit ADR 0003 und R-0040 (#85) enrollt der Desktop nur noch mit einem Einmal-Token, den ein Admin ausstellt; der
Login enrollt nicht. Zeilenangaben main@3c1aac69.

### T1 — Die Meldung ohne Identität nennt den Einmal-Token-Weg (R-0203)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @655673c5 2026-10-06T14:47:24+02:00
Review: approve (opus, Review am Ende über den ganzen Diff)
Änderung: `export_identity` (`frpc.rs:118`) meldet ohne Identität „Kein mTLS-Zertifikat vorhanden — bitte zuerst am
Server anmelden (Enrollment), dann den Tunnel starten.“ (`:121`). Das legt nahe, der Login enrolle. Der neue Text
ist englisch (neue Code-Strings englisch, der deutsche Alt-Bestand bleibt) und nennt den Weg: das Gerät zuerst mit
einem Einmal-Token vom Admin registrieren, dann den Tunnel starten — etwa „No mTLS certificate on this device —
enroll it with a one-time token from your admin first, then start the tunnel.“ Ein Test in `frpc.rs` (`mod tests`,
`:350`) hält fest, dass die Meldung den Einmal-Token nennt und keinen Login verlangt; dafür die Meldung als
Konstante oder kleine Funktion herausziehen, die `export_identity` nutzt, statt den Keyring im Test anzufassen.
CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis: Roadmap R-0203 — Opus-Review von R-0040 (Worker A, 2026-10-06): `frpc.rs:121` auf
feature/remove-enroll-device@7b55a8db.
Semantik: `docs/developer/index.html` (DE) nach #85: „Desktop (mit einem Einmal-Token, den ein Admin ausstellt und
übergibt — ohne vorheriges Login, ADR 0003)“ — die Meldung muss dazu passen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md
