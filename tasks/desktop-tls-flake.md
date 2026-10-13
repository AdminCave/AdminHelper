<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Backend: Tests, die einen abgelehnten Port brauchen, halten ihn, statt ihn freizugeben — Task-Ledger
Status: aktiv · Branch: feature/desktop-tls-flake · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; T2 bleibt drin; der Windows-Job der CI entscheidet T1, rot wird [?]; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0341 (Kurz-Ledger ohne Spec)
Heavy: none — nur Testcode im Desktop-Backend (`#[cfg(test)]`); kein Produktcode, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, `cargo fmt` und `cargo clippy -- -D warnings` sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13
angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@b57c2813. Alle Pfade unter `apps/desktop/src-tauri/`. Läufe des Desktop-Backends nur mit
totem Session-Bus (`DBUS_SESSION_BUS_ADDRESS=unix:path=<eigener Pfad>/no-bus`).

**Ursache.** Der Fehler liegt im Test, nicht im Produkt.
- `non_tls_network_errors_keep_the_raw_chain` (`src/error.rs:179-201`, „B“) bindet `127.0.0.1:0`, merkt sich den Port
  und gibt ihn frei (`:183-185`, „free the port again -> refused“). Danach erwartet er, dass dort niemand lauscht.
- Der Port ist danach sofort wieder vergebbar. Läuft parallel `unknown_issuer_maps_to_stable_code_and_names_the_setting`
  (`:152-177`, „A“), kann dessen `bind(0)` (`:158`) genau diesen Port ziehen. Dann spricht B mit dem TLS-Server von A.
- `serve_once` (`src/test_tls.rs:19-32`) nimmt genau eine Verbindung an. Nimmt es die von B an, liegt die von A noch in
  der Warteschlange. Mit dem Ende von `serve_once` schließt der Listener, und die Verbindung von A endet mit einem RST.
- So endet B mit `ERR_TLS_UNKNOWN_ISSUER` („False positive“) und A mit `Connection reset by peer (os error 104)`
  („Code fehlt“).
- `src/enrollment.rs:1468-1472` (`a_reset_with_the_server_out_of_reach_remembers_the_leaf_and_deletes_the_identity`)
  nutzt dasselbe Muster mit `std::net::TcpListener`.

### T1 — test_tls: `refused_port()` hält einen abgelehnten Port, und der Refused-Test in error.rs nimmt ihn (R-0341)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/test_tls.rs, apps/desktop/src-tauri/src/error.rs
Änderung:
- `src/test_tls.rs`: neue Funktion `pub fn refused_port() -> (tokio::net::TcpSocket, u16)`.
  - `tokio::net::TcpSocket::new_v4()` setzt kein `SO_REUSEADDR`. Der Socket wird an `127.0.0.1:0` gebunden und lauscht
    nie (kein `listen()`).
  - Solange er lebt, bekommt kein anderer Bind den Port, und ein Connect darauf wird abgelehnt.
  - Ein Kommentar nennt das Warum: Ein freigegebener Port kann einem parallelen `bind(0)` zufallen.
- Ein neuer Test in `test_tls.rs` prüft den Helfer, solange `_reserved` lebt:
  - `tokio::net::TcpListener::bind(("127.0.0.1", port))` scheitert mit `AddrInUse`;
  - `tokio::net::TcpStream::connect(("127.0.0.1", port))` scheitert mit `ConnectionRefused`.
- `src/error.rs`, B: `:183-185` werden zu `let (_reserved, port) = crate::test_tls::refused_port();`. Die Bindung muss
  benannt sein: `_` droppt den Socket sofort.
- B bekommt eine positive Assertion, vor `AppError::from(err)`: In der Kette von `err` (über `source()`) steht ein
  `std::io::Error` mit `kind() == ConnectionRefused`. Die Meldung zeigt `{err:?}`.
  - Die bestehende negative Assertion (`:197-200`) bleibt.
  - In der Probe (Linux) ist die positive Assertion grün.
- Unter Windows (CI-Job „Desktop-Backend (cargo test, Windows)“) ist nicht verifiziert, ob ein gebundener, nicht
  lauschender Socket ebenso `ConnectionRefused` liefert. Ist der Job dort rot, wird die Task `[?]` mit dem Befund, nicht
  still angepasst.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (intern, Testcode)
Beweis:
- CI-Lauf 38354712255 auf origin/main@b57c2813, Attempt 1, Job „Desktop-Backend“, `cargo test`: `152 passed; 2 failed`.
  - B: `panicked at src/error.rs:197:9: False positive: ERR_TLS_UNKNOWN_ISSUER: …`.
  - A: `panicked at src/error.rs:172:9: Code fehlt: error sending request for url (https://127.0.0.1:42141/): client
    error (Connect): Connection reset by peer (os error 104)`.
  - Attempt 2 ist grün (`154 passed`).
- Probe, nicht committet: das Test-Binary von origin/main@b57c2813, Filter `error::tests::`, `--test-threads=2`. Jeder
  Lauf läuft in einem frischen Netz-Namespace: `unshare -rn`, dann `ip link set lo up` und
  `echo "40000 40007" > /proc/sys/net/ipv4/ip_local_port_range`.
  - 21 von 200 Läufen sind rot, alle mit genau diesen zwei Meldungen (Port 40001 bzw. 40003).
  - Mit der Änderung oben sind 0 von 200 rot.
  - Ohne Verengung (32768–60999) sind auch vorher 0 von 200 rot. Ein frischer Namespace je Lauf ist nötig: Im selben
    Namespace erschöpft TIME_WAIT früherer Läufe die 8 Ports (`os error 98`/`99`), und das misst etwas anderes.
Orakel: mutation-sample — `refused_port` gibt den Socket wie bisher frei (binden, Port lesen, droppen): der neue Test
in `test_tls.rs` rot. Dazu die Wiederholung aus dem Beweis, vor und nach der Änderung je 200 Läufe: vorher mindestens
einer rot, nachher keiner.
Metrik: Tests im Desktop-Backend, die einen Port freigeben und dann annehmen, dass dort niemand lauscht: 2
(`error.rs:183-185`, `enrollment.rs:1468-1472`) → 1 nach T1, 0 nach T2.
Dedup-Key: bug:desktop-rs:error.rs:tls-test-server-race
HEAD: b57c2813
Semantik: `docs/developer/desktop.html:125`: „error.rs erkennt genau diesen Fall per Downcast durch die
reqwest-Quellenkette … und ersetzt die rohe rustls-Meldung durch den stabilen Code ERR_TLS_UNKNOWN_ISSUER samt
Handlungs-Hinweis.“ A und B prüfen beide Seiten von „genau diesen Fall“. Dafür muss B wirklich auf einen Port treffen, an
dem niemand lauscht.

### T2 — enrollment.rs: der Reset-Test ohne erreichbaren Server nimmt denselben Helfer (R-0341)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs
Abhängt von: T1
Änderung:
- `a_reset_with_the_server_out_of_reach_remembers_the_leaf_and_deletes_the_identity` (`:1458-1481`, `#[tokio::test]`):
  `:1467-1472` („Bound and let go again: nobody listens on the port.“, `std::net::TcpListener::bind` und
  `local_addr().port()`) werden zu `let (_reserved, port) = crate::test_tls::refused_port();`.
- Die Assertions des Tests bleiben unverändert. Der Kommentar sagt, dass der Port gehalten wird.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (intern, Testcode)
Beweis: origin/main@b57c2813, `enrollment.rs:1467-1472`: dasselbe Muster wie `error.rs:183-185`. Den freigegebenen Port
kann ein parallel laufender `serve_once` ziehen (`enrollment.rs:1319`, `:1346`; `tofu.rs:528`, `:536`, `:551`). Dessen
eine Verbindung nähme dann der HTTP-Aufruf von `reset_identity`.
- Nicht als Rot beobachtet: Die Probe aus T1 über das ganze Test-Binary (200 Läufe, 16 Ports je frischem Namespace)
  ergab 0 Fehlschläge.
Metrik: siehe T1 (1 → 0).
Dedup-Key: bug:desktop-rs:error.rs:tls-test-server-race
HEAD: b57c2813
Semantik: `docs/developer/desktop.html:125` wie in T1. Dazu der Test selbst (`enrollment.rs:1465`): „The identity is
sound; what fails is reaching the server.“ Das gilt nur, wenn an dem Port niemand lauscht.
