<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Entwickler-Doku Desktop nennt jeden registrierten Command — Task-Ledger
Status: geplant · Branch: feature/desktop-command-docs · Review: am Ende
Spec: Roadmap R-0383
Heavy: none — Doku und ein statischer vitest-Abgleich; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Baut erst nach dem Merge von R-0240 (`device-identity-status`): beide sind `desktop-ui`, und R-0240 trägt
`device_identity` in dieselbe Tabelle ein.

### T1 — Command-Tabelle vollständig, Zahlen raus, Abgleich im IPC-Inventar  [ ]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/developer/index.html, apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts
Änderung: Die Command-Tabelle (`desktop.html:82` ff., DE+EN) nennt jeden Command aus `generate_handler!` (`apps/desktop/src-tauri/src/main.rs`), heute fehlen `pinned_ca_fingerprint`, `enroll_with_token`, `export_browser_p12`, `generate_diagnostics`, `start_notification_stream`, `stop_notification_stream`. Die festen Zahlen, die schon veraltet sind, fallen weg: „invoke_handler mit 24 Commands“ (`desktop.html:41`, DE+EN) und „32 Tauri-Commands“ (`docs/developer/index.html:78`). `ipc.inventory.test.ts` (liest `generate_handler!` schon, `:42-44`) prüft zusätzlich, dass jeder registrierte Command in beiden `desktop.html` als `<code>name</code>` vorkommt; der Abgleich ist vor der Doku-Korrektur rot, das zeigt der builder.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/bridge/ipc.inventory.test.ts
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html, docs/developer/index.html (EN-Gegenstück nennt keine Zahl)
Beweis: main@c18098a4 · `for c in pinned_ca_fingerprint enroll_with_token export_browser_p12 generate_diagnostics start_notification_stream stop_notification_stream; do grep -c "$c" docs/developer/desktop.html apps/desktop/src-tauri/src/main.rs; done` → Doku 0, `main.rs` 2 je Command; `grep -n "24 Commands" docs/developer/desktop.html`, `grep -n "32 Tauri-Commands" docs/developer/index.html` → je ein Treffer
Orakel: contract — Abgleich `generate_handler!` ↔ Command-Tabelle der Doku
Dedup-Key: bug:docs:desktop.html:command-table
HEAD: c18098a4
Semantik: docs/ ist hier selbst der Fehler; das Soll ist `generate_handler!` in `main.rs` und `.claude/rules/docs.md` — „Falsche Doku ist ein Bug“
