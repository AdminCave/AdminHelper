<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Produkt-Folgen 3: der Keyring in Tests ohne Guard, das Löschen eines Servers neben einer Aktivierung — Task-Ledger
Status: erledigt · Branch: feature/product-followups-3 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0327, R-0322, Triage Kevin 2026-10-12; T2 als Fix mit anderer Sperr-Reihenfolge, R-0311 bleibt zu; Heavy linux-full nach Regel; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0327, R-0322 (Kurz-Ledger ohne Spec)
Heavy: linux-full — `run.sh integration`, weil T2 eine Server-Route ändert (`DELETE /api/servers/{id}`); T1 ändert nur Test-Builds der Desktop-Crate. Die Aktivierung über `:8444` bleibt, wie sie ist, daher kein Multibox.
DoD je Task: CLAUDE.md (Tests grün, cargo fmt und clippy -D warnings sauber, ruff check und ruff format sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat beide Zeilen am 2026-10-12
angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@b7ab9b6c. Jede Aussage über das heutige Verhalten ist mit einer Probe auf diesem Stand belegt
(nicht committet).

### T1 — keyring_store: ohne Guard antwortet ein Test-Build wie eine Plattform ohne Store (R-0327)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/keyring_store.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f134328c 2026-10-12T22:59:45+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve, Nits miterledigt
Änderung: In Test-Builds (`#[cfg(test)]`) gehen `set`, `get`, `try_get` und `delete` (`:26`, `:40`, `:49`, `:58`)
ohne Guard nicht mehr an `os_*`, sondern antworten wie die Fassung für Plattformen ohne Store (`:124-127` usw.):
`set` → `Err(AppError::Keyring(…))`, `get` → `None`, `try_get` → `Ok(None)`, `delete` → `Ok(())`. Mit Guard
(`memory()`) bleibt alles, wie es ist; Release-Builds ändern sich nicht. Die Modul-Doku (`:17-18`, „without the
guard tests reach the OS store as before“) sagt das Neue.
- In Test-Builds bleiben die `os_*`-Fassungen ungenutzt; das darf weder eine dead_code-Warnung unter
  `cargo clippy --all-targets -- -D warnings` noch auf Windows einen ungenutzten Import ergeben.
- Tests im selben Modul, am Ende von `mod tests`: ohne Guard ist `set` ein `Err` und `get` danach `None`, `try_get`
  eines Schlüssels `Ok(None)`, `delete` `Ok`.
- Die Tests über die 32 Aufrufe: Eine Probe hat in den vier Funktionen jeden Aufruf ohne Guard protokolliert
  (`eprintln!` mit dem Namen des Test-Threads, `cargo test -- --nocapture`). Genau ein Test greift ohne Guard auf
  den Keyring zu: `tofu::tests::forget_pin_clears_the_cache_under_the_normalized_identity` (`tofu.rs:425`, ein
  `delete`, das `forget_pin` ohnehin ignoriert). Mit der neuen Antwort laufen alle 153 Tests grün, clippy sauber.
- Proben dieser Task nur mit `DBUS_SESSION_BUS_ADDRESS=unix:path=<eigener Pfad>/no-bus`: Eine Fassung ohne die
  Änderung erreicht sonst auf einer Box mit Keyring-Dienst den echten Store.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (intern; nur Test-Builds)
Beweis: origin/main@b7ab9b6c, Probe (nicht committet, Session-Bus tot): protokollierte Aufrufe ohne Guard: 1
(`forget_pin_clears_the_cache_under_the_normalized_identity`, `delete`), `test result: ok. 153 passed`. Mit der
Antwort ohne Store: `153 passed`, `cargo clippy --all-targets -- -D warnings` ohne Warnung.
Metrik: Tests, die in `cargo test` den Store des Betriebssystems erreichen (Instrument wie im Beweis): 1 → 0.
Orakel: mutation-sample — ohne Guard wieder an `os_*`: der neue Test rot (bei totem Session-Bus ist `try_get` dann
ein `Err`, nicht `Ok(None)`).
Dedup-Key: ref:desktop-rs:keyring_store:fail-closed-in-tests
HEAD: b7ab9b6c
Semantik: keine Stelle in docs/ — `docs/developer/desktop.html:112-115` („Keyring-Secrets“) nennt nur die Stores im
Betrieb. Im Code beschreibt `keyring_store.rs:17-18` das heutige Verhalten, das diese Zeile ändert.

### T2 — Server löschen: erst die Zeile sperren, dann die Identität (R-0322)  [x]
Komponente: server · Dateien: apps/server/app/modules/servers/router.py, apps/server/app/modules/enrollment/models.py, apps/server/tests/test_provisioning.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @2c759eb0 2026-10-12T22:30:03+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `delete_server` (`servers/router.py:182`) liest die Server-Zeile ohne Sperre (`:188`), nimmt in
`revoke_identity` (`:194`) die Sperre der Identität und wartet erst bei `db.delete(server)` (`:195`) auf eine
Aktivierung, die die Zeile hält. Die Aktivierung hält sie von `provisioning/router.py:136` bis zum Commit (`:187`),
darin der Monitor-Call (`:173`, 5 s je Phase). So lange wartet jedes Enroll und jedes Erneuern dieses Agents auf die
Sperre der Identität, und der Issuer bricht ab, sobald `statement_timeout` (5000 ms, `ca-issuer/app/db.py:155`)
erreicht ist. Künftig sperrt `delete_server` die Zeile zuerst (`with_for_update()` an `:188`) und nimmt die Sperre
der Identität erst danach. Es wartet also auf die Aktivierung, ohne die Identität zu halten. An der Stelle sagt ein
Kommentar, warum die Reihenfolge so ist; bei `IDENTITY_LOCK_SQL` (`enrollment/models.py:102-106`) ein Satz dazu.
- **Kein Zyklus:** Die Sperre der Identität eines Servers nehmen Enroll und Erneuern am Issuer und die Übernahme
  (`admit_certificate`, im Request der Agent-Routen). Danach sperrt keiner von ihnen eine Server-Zeile: Die
  Agent-Routen (`frp/provision_router.py`, `monitoring_proxy/router.py`) lesen die Zeile nur, und Admin-Requests
  sperren die Identität eines Benutzers, nicht die eines Servers. Die Kaskaden des Löschens berühren keine Tabelle
  des Issuers (`enrollment_tokens` hat keinen Fremdschlüssel auf `servers`).
- **Der Monitor-Call vor die Sperre der Aktivierung**, wie in der Zeile gefragt: geprüft und nicht gewählt, weil er
  R-0311 wieder öffnet. Zwei Aktivierungen desselben Servers riefen den Monitor-Dienst dann in anderer Reihenfolge
  auf, als sie die Zeile sperren. Danach hielte die zuletzt committete Aktivierung den API-Key, die zuletzt rufende
  den gültigen Monitor-Key. Ebenso ein zweiter Request mit demselben Token: Er ruft den Monitor-Dienst, scheitert
  dann am Einlösen und hat den Monitor-Key der ersten Aktivierung schon ersetzt.
- Test in `test_provisioning.py`, am Dateiende, auf echten Postgres-Verbindungen wie
  `test_a_second_activation_waits_for_the_first_and_one_key_stays`:
  - Eine Aktivierung hält die Zeile (`with_for_update(key_share=True)` und ein `ApiKey`).
  - `DELETE /api/servers/{id}` über die Route wartet (`_waits_for`, `:388`).
  - Eine dritte Verbindung bekommt `pg_try_advisory_xact_lock` der Identität (`server_id`, `SCOPE_AGENT`) sofort.
  - Nach dem Commit der Aktivierung endet das Löschen mit 204, und die Identität ist widerrufen.
  - Die Zeilen des Tests werden am Ende entfernt.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern; ein seltener, vorübergehender Fehler, kein geändertes Verhalten nach außen)
Beweis: origin/main@b7ab9b6c, Probe (nicht committet, eigene Test-DB, dreimal identisch). Eine Aktivierung hält die
Zeile, das Löschen wartet auf sie, eine dritte Verbindung fragt `pg_try_advisory_xact_lock` der Identität: in der
heutigen Reihenfolge `identity_lock_free=False`; mit der Zeile zuerst `identity_lock_free=True`. Je Lauf `2 passed`.
Orakel: mutation-sample — die Zeile wieder ohne Sperre lesen: der neue Test rot.
Dedup-Key: bug:server:provisioning-router.py:lock-over-monitor-call
HEAD: b7ab9b6c
Semantik: keine Stelle in docs/ — gesucht nach `statement_timeout`, `IDENTITY_LOCK`, „Server löschen“. Im Code:
`enrollment/models.py:102-106`, „So revoking an identity and creating a line for it go one after the other“. Die
Sperre ordnet Widerruf und neue Linie, sie stellt eine neue Linie nicht hinter eine Aktivierung.
