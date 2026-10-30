<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-3 — Task-Ledger
Status: aktiv · Branch: feature/kern-desktop-3 · Review: pro Task
Spec: docs/features/kern-desktop-3.md (Roadmap R-0962, R-0961, R-0984, R-0981)
Heavy: linux-full — Desktop-Journeys: Tunnel-Abgleich (Visitor-Bundle) und Geräte-Reset
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@2eac9b1d`, vor dem Schreiben neu greppen. Neue Code-Strings englisch,
CHANGELOG umlautfrei und neutral in `changelog.d/kern-desktop-3.md`. `security` zusätzlich bei T1 und T2 (SEC) und wo
`review.sh risk` es verlangt.

### T1 — Visitor-Bundle mit Lesegrenze (R-0962)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-desktop-3.md
Änderung: `bundle_from` (`frpc.rs:268-283`) liest wie `read_list` (`sync.rs:43-71`) höchstens 16 MiB: zuerst die angegebene Länge, dann chunkweise; Fehler ohne Zitat der Antwort. Test zuerst rot: eine Antwort über der Grenze wird abgewiesen (lokaler Test-Server wie in den bestehenden frpc-Tests, sonst ein Test der Lesefunktion).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc
Doku: docs/developer/desktop.html DE+EN (nur wenn die Seite Lesegrenzen nennt), changelog.d/kern-desktop-3.md

### T2 — Zurücksetzen: Keyring auf einem Blocking-Thread, Rollback-Fehler in der Meldung (R-0961, R-0984)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/commands.rs, changelog.d/kern-desktop-3.md
Änderung: `reset_identity` (`enrollment.rs:502-514`) ruft `leaf_fingerprint`, `clear_identity` und das Merken von `KEYRING_REPLACES` über einen Blocking-Thread auf (`tauri::async_runtime::spawn_blocking`, wie `blocking` in `commands.rs:594`), die Server-Abfrage bleibt async, `reset_with` unverändert. `enroll_with_token_in` (`commands.rs:239-243`) hängt einen Fehler des Zurücksetzens an die Meldung („the device identity stays, reset it in the settings: …“) statt ihn mit `let _` zu verwerfen. Test zuerst rot für R-0984 (ein scheiternder `reset` erscheint in der Meldung); R-0961 ist Plattform-Wiring (Thread-Wechsel), die bestehenden Reset-Tests bleiben grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enroll
Doku: changelog.d/kern-desktop-3.md (die Meldung steht in docs/ nicht wörtlich)

### T3 — Launcher-Tests ohne feste Obergrenze von 900 ms (R-0981)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/launcher.rs
Beweis: PR #326 CI 2026-10-30 · gh run view 40972646852 --job 123792900394: launcher.rs:2303 gave up after 1.9524272s · Dedup-Key: flaky:desktop:launcher.rs:open_gives_up_on_a_workspace_that_holds_no_lock_in_time
Änderung: `open_gives_up_on_a_workspace_that_holds_no_lock_in_time` (`launcher.rs:2282-2310`) und `delete_gives_up_on_a_purge_that_does_not_end_in_time` (`:2505-2533`) prüfen statt `< 900 ms` eine großzügige Obergrenze (Frist plus einige Sekunden: „hängt nicht“); Mindestwartezeit und Zahl der Blicke bleiben.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- launcher
Doku: keine (nur Tests)

## Entscheidungen
