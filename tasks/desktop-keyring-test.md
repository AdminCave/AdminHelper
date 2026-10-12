<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: ein Test-Backend für den Keyring, Tests für die Aufrufstellen von replaces_for — Task-Ledger
Status: bereit · Branch: feature/desktop-keyring-test · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0294, Triage Kevin 2026-10-11; Heavy e2e bleibt, weil T2 die Aufrufstellen in enrollment.rs umstellt; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0294 (Kurz-Ledger ohne Spec)
Heavy: linux-full — `run.sh e2e` (die Desktop-Enrollment-Journey `settings-enroll.live.js`), weil T2 die Aufrufstellen in `enrollment.rs` umstellt; das Verhalten bleibt, die Journey belegt es. Kein Stack- oder Gateway-Pfad, daher nur e2e.
DoD je Task: CLAUDE.md (cargo fmt, cargo clippy -D warnings, cargo test grün, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-11 als
Loop-Futter angenommen; gebaut wird sie außerhalb des Builder-Loops, weil dessen Clone das frpc-Sidecar nicht hat
(R-0325). Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@dba03852. Pfade relativ zu `apps/desktop/src-tauri/`.

Bestand: `src/keyring_store.rs` (113 Zeilen) hat für `set`, `get`, `try_get` und `delete` je eine Fassung für Unix
(`keyring`-Crate), Windows (`crate::password`) und andere Plattformen, aber keine für Tests. In `cargo test` ohne
Keyring-Dienst schlägt `set` fehl und `get` gibt `None`; was eine Funktion mit dem Keyring tut, lässt sich so nicht
prüfen. Getestet sind deshalb nur reine Teile: `replaces_for` (`src/enrollment.rs:251`, Tests `:993`, `:1003`) und
`reset_with` mit Closures (`:292`). Die Aufrufstellen nicht:
- `enroll_with_token` (`:367`): `replaces_for(EnrollmentKind::Device, leaf_fingerprint(),
  keyring_store::get(KEYRING_REPLACES))` (`:374-378`), nach gelungenem Speichern `keyring_store::delete(KEYRING_REPLACES)`
  (`:399`).
- `export_browser_p12` (`:735`): `replaces_for(EnrollmentKind::Browser, …)` (`:752-756`).
- `reset_identity` (`:278`): merkt sich bei `LocalOnly` den Fingerprint mit `keyring_store::set(KEYRING_REPLACES, …)`
  (`:284`) und löscht die Identität (`clear_identity`, `:344`).

### T1 — keyring_store: ein Speicher-Backend, das ein Test einschaltet (R-0294)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/keyring_store.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @adf773dc 2026-10-12T18:48:17+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Unter `#[cfg(test)]` ein Backend im Speicher, das ein Test ausdrücklich einschaltet, und nur dann: ein
Guard, etwa `let _keyring = keyring_store::memory();`, der für die Dauer seines Lebens `set`, `get`, `try_get` und
`delete` auf eine Map umleitet und beim Drop wieder zurückstellt. Die Map ist thread-lokal (`thread_local!`): jeder
`#[test]` und jeder `#[tokio::test]` (Standard: current_thread) läuft in seinem Thread, Tests teilen sich nichts. Ohne
Guard bleibt alles wie heute; die übrigen Tests, die über `keyring_store` gehen (32 Aufrufe in `src/`), merken nichts.
- Umsetzung: die vier öffentlichen Funktionen prüfen zuerst den Guard und rufen sonst die bisherigen Fassungen je
  Plattform, die dafür private Namen bekommen. Kein neues Crate.
- Tests im selben Modul: Rundlauf `set`/`get`/`try_get`/`delete`; `try_get` eines fehlenden Schlüssels ist `Ok(None)`;
  `delete` eines fehlenden ist `Ok`; nach dem Drop des Guards ist die Map leer; zwei Threads mit eigenem Guard sehen
  ihre Werte nicht gegenseitig.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (intern)
Beweis: origin/main@dba03852: `src/keyring_store.rs` hat keinen `#[cfg(test)]`-Zweig; `set` geht unter Unix immer an
`keyring::Entry` (`:22-28`); `src/validation.rs:102` erlaubt plain http nur auf Loopback.
Metrik: Tests, die eine Funktion samt Keyring-Zugriff prüfen, in `src/enrollment.rs`: 0 → mindestens 4 (nach T2).
Orakel: mutation-sample — der Guard leitet nicht um: die Rundlauf-Tests rot.
Dedup-Key: ref:desktop-rs:keyring_store.rs:test-backend
HEAD: dba03852
Semantik: `src/keyring_store.rs:5-9` (ein Backend für alle Sicherheitsmodule, damit sich Änderungen nicht über Kopien
verteilen); ein Test-Backend an derselben Stelle folgt dem.

### T2 — enrollment: die Aufrufstellen von replaces_for und das Merken beim Zurücksetzen sind getestet (R-0294)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @65b6da31 2026-10-12T18:51:51+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Die zwei Schritte der Enroll-Abläufe, die nur den Keyring berühren, werden kleine Funktionen und an beiden
Stellen benutzt; das Verhalten bleibt:
- `pending_replaces(kind)` = `replaces_for(kind, leaf_fingerprint(), keyring_store::get(KEYRING_REPLACES))`, in
  `enroll_with_token` (`:374-378`) und `export_browser_p12` (`:752-756`).
- `settle_replaces(&stored)` löscht `KEYRING_REPLACES` nur, wenn `stored` gelungen ist (heute `:397-400`).
Tests am Ende von `mod tests`, jeweils mit dem Guard aus T1 und echten Zertifikaten aus `rcgen` (schon eine Abhängigkeit,
`Cargo.toml:46`):
- Ein Gerät mit einem gespeicherten Leaf (`enroll|cert`) nennt dessen Fingerprint, auch wenn ein gemerkter da ist.
- Ohne Identität, mit gemerktem Fingerprint: der gemerkte.
- Ein Browser-Export nennt nichts, mit Leaf und mit gemerktem.
- `settle_replaces`: nach Erfolg ist `enroll|replaces` weg, nach einem Fehler bleibt er.
- `reset_identity` gegen eine Loopback-Adresse, an der niemand lauscht (`http://127.0.0.1:<freier Port>`; plain http ist
  auf Loopback erlaubt, `validate_server_url_secure`): Ergebnis `ResetOutcome::LocalOnly`, `enroll|replaces` hält den
  Fingerprint des alten Leafs, Key, Zertifikat und CA sind gelöscht.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (intern)
Abhängt von: T1
Beweis: origin/main@dba03852: die drei Aufrufstellen (`:374-378`, `:752-756`, `:284`) haben keinen Test; die Tests
`:993` und `:1003` prüfen `replaces_for` mit übergebenen Werten.
Orakel: mutation-sample — in `pending_replaces` die Werte vertauscht (gemerkt vor gehalten) oder `settle_replaces`
ohne Prüfung von `stored`: der jeweilige Test rot.
Dedup-Key: ref:desktop-rs:keyring_store.rs:test-backend
HEAD: dba03852
Semantik: `docs/admin/benutzer.html:108`: „Widerruft der Server es dabei nicht, etwa weil er nicht erreichbar ist, sagt
der Desktop, dass er nur lokal zurückgesetzt hat“; `:109`: „Registriert ein Desktop sich neu, löst das neue Zertifikat
das vorige dieses Geräts ab. Eine .p12 ist ein eigenes Gerät und löst nichts ab“.
