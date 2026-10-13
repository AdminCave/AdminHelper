<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Builder-Profil: cargo und go aus dem HOME des Aufrufers, Caches im Builder-HOME — Task-Ledger
Status: erledigt · Branch: harness/builder-toolchains · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; T3 und das Restrisiko Toolchain-Tausch waehrend eines Loops auf Kevins Wort 2026-10-13; Fragen 2-4 wie empfohlen; Bau nach dem Merge von pg-url-helper; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0358 (Kurz-Ledger ohne Spec)
Heavy: none — `setup`, `status` und `setup_settings` in `scripts/dev/builder-home.sh` mit ihrem hermetischen Test; kein Stack-, Gateway-, PKI- oder Install-Pfad. Die Abnahme im echten Builder (`setup`, `status`, ein Messlauf) ist Kevins Schritt.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13 angenommen
und entschieden: Die Toolchains kommen read-only aus seinem HOME (`RUSTUP_HOME`, `GOROOT`), die Caches liegen im
Builder-HOME (`CARGO_HOME`, `GOPATH`, `GOCACHE`). Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt
kommt von der Aufsicht. Zeilenangaben origin/main@bef5d17e. `scripts/dev/builder-home.sh` und sein Test sind
Harness-Pfade; den PR merged Kevin oder die Aufsicht auf sein Wort.

**Befund.**
- `setup` schreibt den `.devenv.sh` des Builders (`setup_devenv`, `builder-home.sh:292-302`) mit einem festen PATH
  (`:297`): `export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"`. Darin sind weder cargo noch go.
- Die Umgebung des Loops entsteht nur daraus. `ledger-loop.sh start` startet unter
  `env -i HOME=<builder> PATH=/usr/local/bin:/usr/bin:/bin` (`ledger-loop.sh:136-137`). `runner-env.sh` sourct
  `$HOME/.devenv.sh` (`:63-66`) und fasst PATH sonst nicht an.
- Klon und Lane haben keine eigene `.devenv.sh`. `verify.sh` erbt deshalb die Umgebung des Loops.
- `status` prüft an der Datei nur den Modus 0600 (`:367`).
- `<KH>` heißt unten das HOME des Aufrufers von `setup` (Kevin). `$HOME` in der geschriebenen Datei ist das Builder-HOME.
  - Rust kommt über rustup-Proxies in `<KH>/.cargo/bin`, mit den Toolchains unter `<KH>/.rustup`.
  - Go liegt in `<KH>/sdk/go`.

### T1 — setup: der `.devenv.sh` des Builders nennt cargo und go des Aufrufers und eigene Caches (R-0358)  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ca46367c 2026-10-13T19:19:15+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Änderung:
- `setup_devenv` (`:292-302`) schreibt, je für eine Toolchain, die es unter `<KH>` gibt:
  - Der PATH bekommt `<KH>/.cargo/bin` und `<KH>/sdk/go/bin` hinter `$HOME/.local/bin` und vor die Systempfade. `<KH>`
    steht als fester Pfad in der Datei.
  - Für Rust kommen hinzu:
    - `RUSTUP_HOME="<KH>/.rustup"`. Ohne diese Variable wählt ein rustup-Proxy mit fremdem HOME keine Toolchain.
    - `RUSTUP_AUTO_INSTALL=0`. Ein Branch mit `rust-toolchain.toml` installiert damit nichts in `<KH>/.rustup`.
    - `CARGO_HOME="$HOME/.cargo"` für Registry und Git-Cache im Builder-HOME.
  - Für Go kommen hinzu:
    - `GOROOT="<KH>/sdk/go"`. Das ist derselbe Baum wie das go im PATH.
    - `GOPATH="$HOME/go"` und `GOCACHE="$HOME/.cache/go-build"`.
    - `GOTOOLCHAIN=local`, wie in der CI: Go lädt keine andere Toolchain nach.
- Fehlt eine Toolchain unter `<KH>`, gibt `setup` eine `note` aus, wie beim Sidecar (`:231`), und lässt ihre Zeilen weg.
  Prüfpunkte sind `<KH>/.cargo/bin/cargo` mit `<KH>/.rustup` bzw. `<KH>/sdk/go/bin/go`.
- Ein `<KH>` mit `"`, `$`, `\` oder einem Backtick beendet `setup` mit einer Meldung. Es stünde sonst in einem
  doppelt gequoteten Export.
- `write_if` hält `setup` idempotent. Eine Datei in der alten Vier-Zeilen-Form wird neu geschrieben.
- `builder_home_test.sh`: Das Fixture-HOME (`:30`) bekommt Attrappen der Toolchains:
  - `.cargo/bin/cargo`, die ausgibt, welche `RUSTUP_HOME`/`CARGO_HOME` sie sieht, und ohne `RUSTUP_HOME` scheitert wie
    ein Proxy;
  - `.rustup/`;
  - `sdk/go/bin/go` und `sdk/go/bin/gofmt`.

  Neue Fälle nach `:166-167`:
  - jede erwartete Zeile per `grep -qxF`;
  - die Sicht des Loops (`env -i HOME=$H PATH=/usr/local/bin:/usr/bin:/bin`, `.devenv.sh` sourcen) findet `cargo`, `go`
    und `gofmt`, und die cargo-Attrappe meldet `RUSTUP_HOME=<KH>/.rustup` und `CARGO_HOME=$H/.cargo`;
  - ohne Go im Fixture-HOME gibt es keine Go-Zeilen, dafür eine `note`;
  - ein HOME mit `"` führt zu rc 1;
  - der Fall mit der alten Builder-Datei (`:245-261`) wird auf die neue Form gebracht;
  - die Idempotenz (`snap`, `:175-183`) bleibt.
- `DEVELOPMENT.md:1219-1229` bekommt einen Satz: `setup` nimmt cargo und go read-only aus dem HOME des Aufrufers
  (`RUSTUP_HOME`, `GOROOT`) und legt die Caches ins Builder-HOME. rustup installiert dort nichts nach
  (`RUSTUP_AUTO_INSTALL=0`), Go bleibt bei der eigenen Toolchain (`GOTOOLCHAIN=local`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zu `setup`)
Beweis:
- Messlauf-8 (quinn-proto-0118), `fundament.log`:
  - `:2`: `docker=yes node=no go=no cargo=no display=no`;
  - `:13-14`: `SKIP cargo test (desktop) (cargo or frpc sidecar (…) missing)` und `strict-failed: cargo test (desktop) (SKIP)`.
  - Das Sidecar lag in der Lane, es fehlte cargo.
- Der `.devenv.sh` des Builders trägt genau `export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"`
  (`builder-home.sh:297`).
- Probe mit fremdem HOME (Attrappen-Crate und -Modul im Scratch):
  - Nur `<KH>/.cargo/bin` im PATH: `rustup could not choose a version of cargo to run … no default is configured`.
  - Mit `RUSTUP_HOME=<KH>/.rustup`: `cargo fmt --check`, `clippy -D warnings` und `test` sind grün, unter `<KH>` wird
    nichts geschrieben.
  - Nur `<KH>/sdk/go/bin` im PATH: `go env GOROOT` nennt den Baum selbst, `vet` und `test -race` sind grün.
Orakel: mutation-sample — die Zeile `RUSTUP_HOME` weggelassen: der Fall „Sicht des Loops findet cargo“ wird rot.
Dedup-Key: bug:scripts:builder-home.sh:path-toolchains
HEAD: bef5d17e
Semantik: `DEVELOPMENT.md:1219-1226`: `setup` „installiert die CLI … schreibt die Settings …, ein Tools-venv …, eine
eigene Test-DB … `.devenv.sh` (0600)“, also die Umgebung, in der der Loop baut. Kevins Entscheidung (Roadmap R-0358,
2026-10-13): „Toolchains read-only (RUSTUP_HOME/GOROOT aus Kevins Home), Caches eigen (CARGO_HOME/GOPATH/GOCACHE im
Builder-Home)“.

### T2 — status: fehlt im Builder eine Toolchain, die der Aufrufer hat, meldet `status` sie (R-0358)  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2611211c 2026-10-13T18:16:21+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Abhängt von: T1
Änderung:
- `do_status` (`:357-379`) bekommt eine Prüfung je Toolchain, die es unter `<KH>` gibt (dieselben Prüfpunkte wie in T1).
  - Sie läuft in der Umgebung, die der Loop sieht:
    `env -i HOME="$H" PATH=/usr/local/bin:/usr/bin:/bin bash -c '. "$H/.devenv.sh" && cargo --version'`, für Go mit
    `go version`.
  - Scheitert sie, meldet `status` „missing: cargo (go) in the builder's .devenv.sh — run setup“.
  - Das ist dasselbe Muster wie beim Sidecar (`:369-370`): Verlangt wird nur, was der Aufrufer selbst hat.
- `ledger-loop.sh start` fragt `status` vorher (`ledger-loop.sh:117-118`). Ein Builder ohne Toolchains endet so mit Exit
  74 in der Vorprüfung, statt im Fundament rot zu werden.
- `builder_home_test.sh`, im Abschnitt der Status-Fälle (`:192-241`):
  - eine alte Vier-Zeilen-Datei mit Toolchains unter `<KH>` → rc 1 und „missing: cargo …“, „missing: go …“;
  - nach `setup` → „complete“;
  - ohne Go unter `<KH>` → für Go wird nichts verlangt;
  - eine Datei ohne `RUSTUP_HOME` (die Attrappe scheitert wie ein Proxy) → „missing: cargo …“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (DEVELOPMENT.md nennt nach T1, was `setup` schreibt; `status` meldet wie bisher, was fehlt)
Beweis: origin/main@bef5d17e: `do_status` prüft an `$H/.devenv.sh` nur den Modus (`:367`). Mit der Datei aus dem Befund
meldete `status` „complete“, und Messlauf-8 lief bis ins Fundament.
Orakel: mutation-sample — die cargo-Prüfung in `do_status` entfernt: der Fall „alte Datei → missing: cargo“ wird rot.
Dedup-Key: bug:scripts:builder-home.sh:path-toolchains
HEAD: bef5d17e
Semantik: `builder-home.sh:12`: „status    what is missing; exit 1 if anything“.

### T3 — setup_settings: die Session des Builders darf die Toolchain-Bäume des Aufrufers nicht bearbeiten (R-0358)  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4d397123 2026-10-13T18:30:04+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Abhängt von: T1
Änderung:
- `setup_settings` (`:246-266`) hängt an die Sperren zu privaten Pfaden (`:254-258`) Edit-Sperren an:
  `Edit(/<KH>/.rustup/**)`, `Edit(/<KH>/.cargo/**)` und `Edit(/<KH>/sdk/**)`.
  - Lesen bleibt erlaubt.
  - Das Builder-eigene `CARGO_HOME` liegt unter `$H/.cargo` und ist davon nicht betroffen.
- Damit gilt „read-only“ für die Werkzeuge der Session. Für Prozesse unter derselben UID (ein `build.rs`, ein Test) bleibt
  es eine Konvention, bis die Sandbox kommt (R-0241). Das steht im Kommentar an der Stelle.
- `builder_home_test.sh`: Die drei Regeln stehen in der geschriebenen `settings.json`, nach dem Muster der Fälle für
  private Pfade. Die bestehenden Regeln bleiben.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; DEVELOPMENT.md nennt nach T1 „read-only“)
Beweis: origin/main@bef5d17e: `setup_settings` sperrt `.ssh`, `.config/gh`, `.claude`, `.config/adminhelper`,
`.local/share/keyrings` und `.gnupg` (`:254-258`), keinen Toolchain-Pfad. `harness-guard.sh` hält nur Harness-Pfade im
Checkout.
Orakel: mutation-sample — die neue Sperre auf `.rustup` entfernt: der Fall „Regeln in settings.json“ wird rot.
Dedup-Key: bug:scripts:builder-home.sh:path-toolchains
HEAD: bef5d17e
Semantik: Kevins Entscheidung (Roadmap R-0358, 2026-10-13): „Toolchains read-only“.
