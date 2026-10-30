<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-desktop-1 — Desktop: Nachzügler aus Härtung und Reviews

Roadmap R-0856, R-0873, R-0875, R-0937. Alle vier ändern interne Prüfungen, Aufräumpfade und Tests, kein sichtbares
Verhalten. `overlap.sh` ohne Treffer. R-0872 (`tofu.rs`) fährt nicht mit, siehe unten.

## Problem / Motivation
- **R-0856:** `head_left_behind` (`apps/desktop/src-tauri/src/frpc.rs`) liest `run/visitor.toml`, bevor
  `empty_run_dir` einen Symlink oder eine Junction als Laufordner ablehnt. Nicht ausnutzbar (gelesen wird nur, der Inhalt
  muss ein gültiger Desktop-Kopf sein), aber die Reihenfolge ist falsch. Soll: dieselbe `symlink_metadata`-Vorprüfung
  vor dem Lesen.
- **R-0875:** `cargo clippy --all-targets` meldet `type_complexity` im Test
  `the_first_reconciliation_stops_nothing_behind_a_head_that_is_not_the_desktops`. Soll: Typalias im Test.
- **R-0873** (`ansible.rs`): `create_run_dir` deklariert `let mut builder`, was unter Windows `unused_mut` ergibt;
  `linux_run_script` löscht das rohe Elternverzeichnis der übergebenen Inventarpfads statt des von `confined_run_dir`
  geprüften kanonischen; die Tests `scratch()` und `stub_ansible_playbook` legen feste Namen unter `/tmp` an.
- **R-0937** (`ui/src/lib/utils/shell.ts`): `SAFE` lässt `%` ungequotet; ältere fish-Versionen expandieren ein Wort
  `%self` zur PID. Heute nicht ausnutzbar (gequotet werden URL, UUID, Fingerprint), aber die Funktion verspricht ein
  Wort, das alle Shells wörtlich lesen.

## Ziel & Nicht-Ziele
- Vorprüfung vor dem Lesen, Typalias, `mut` nur unter `cfg(unix)`, kanonischer Pfad im Aufräumskript, `%` nicht mehr
  bare, Tests im eigenen Verzeichnis statt festem `/tmp`-Namen.
- Nicht-Ziel: eine Eigentümerprüfung in `confined_run_dir` (Entscheidung unten), neue Abhängigkeiten.

## R-0872 fährt nicht mit
Der Code ist schon behoben: `dd1f9b01` (`KeyringPinStore::forget` leert Cache und löscht den Keyring unter dem
Identitäts-Lock, `load` liest unter demselben Lock) mit den Tests `forgetting_waits_for_a_load_that_is_reading` und
`forgetting_waits_for_a_first_contact_that_is_storing`. Die Zeile braucht Kevins Wort (ablehnen als erledigt).

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/frpc.rs`, `apps/desktop/src-tauri/src/ansible.rs`,
`apps/desktop/ui/src/lib/utils/shell.ts`, `shell.test.ts`.

## Trade-offs
- **Eigentümerprüfung (R-0873):** ein Vergleich mit der eigenen uid bräuchte `libc` als direkte Abhängigkeit. Ein
  fremder Nutzer mit 0700 ist ohnehin nicht traversierbar (`canonicalize` scheitert), nur root könnte hinein: kein
  Gewinn, der eine Abhängigkeit trägt. Die Task lässt sie aus und begründet das im Ledger.
- **`%` (R-0937):** ganz aus `SAFE` nehmen (wie die Zeile sagt) statt nur führend; einfacher, Kosten: eine URL mit
  `%2B` erscheint im kopierten Befehl in Quotes.

## Risiken & Rollback
Gering; jede Task ist ein Commit und einzeln zurücknehmbar. Plattform: `unused_mut` und Junctions werden nur unter
Windows sichtbar, dort „nicht verifiziert" (nur die CI `rust-windows` fährt `cargo test`).

## Doku-Impact
Keine: interne Prüfungen und Tests; kein dokumentiertes Verhalten ändert sich.

## Offene Fragen
R-0872 ablehnen? Empfehlung: ja, mit Notiz „behoben durch dd1f9b01".
