<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop meldet frpc-terminated nur für die laufende Generation — Task-Ledger
Status: bereit · Branch: feature/frpc-stale-terminated · Review: am Ende
Spec: Roadmap R-0247
Heavy: none — nur ob ein UI-Event gesendet wird; FRP-Konfiguration, Visitor-TOML und Datenpfad bleiben unberührt, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-15: Rust-Fix an der Ursache. Baut in der Desktop-Spur nach R-0240, R-0383 und R-0028.

### T1 — frpc-terminated nur für die laufende Generation senden  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @1017889e 2026-10-15T16:59:05+02:00
Review: am Ende (Branch-Review)
Änderung: `reconcile_terminated` (`frpc.rs:66`) gibt zurück, ob das Ereignis zur laufenden Generation gehört; der Log-Task (`:284-296`) sendet `frpc-terminated` (`:295`) nur dann, ein vergifteter Lock meldet weiter wie heute. Heute geht das Ereignis einer alten Generation trotzdem ans UI (`AppShell.svelte:142` → `stores/tunnel.ts:72-74` → „Tunnel getrennt“), obwohl die neue Generation läuft. Neuer cargo-Test `stale_terminated_is_not_announced_while_a_newer_frpc_runs`: Ereignis der alten Generation → nicht melden, Zustand bleibt; Ereignis der laufenden → melden. Der bestehende Test `reconcile_terminated_clears_state_only_for_the_current_generation` (`:440`) bleibt. Auf HEAD scheitert der neue Test am Kompilieren (es gibt keine Entscheidung vor dem Senden); dass er die Entscheidung prüft, belegt nach dem Fix eine Mutations-Stichprobe (Bedingung entfernt → rot). Doku: ein Satz bei den Events (`desktop.html:144`, DE+EN), dass nur die laufende Generation `frpc-terminated` meldet.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- stale_terminated
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:144`)
Beweis: main@c18098a4 · `sed -n 284,296p apps/desktop/src-tauri/src/frpc.rs` → `guard.reconcile_terminated(my_gen)` ohne Rückgabe, danach ohne Bedingung `app_handle.emit("frpc-terminated", payload.code)`; `stop_frpc` (`:314-322`) erhöht die Generation nicht, `start_frpc` (`:268-269`) schon
Orakel: mutation-sample — nach dem Fix macht das Entfernen der Generationsbedingung den neuen Test rot
Dedup-Key: bug:desktop:frpc.rs:terminated-old-generation
HEAD: c18098a4
Semantik: docs/developer/desktop.html:144 — „Der Sidecar-Prozess emittiert die Tauri-Events <code>frpc-terminated</code> und <code>frpc-error</code>; der Tunnel-Store (<code>stores/tunnel.ts</code>) hört darauf und speist die Statusanzeige (<code>TunnelIndicator.svelte</code>)“; zu alten Generationen keine Stelle in docs/
