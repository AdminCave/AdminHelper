<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Identitätspfad im Desktop-frpc TOML-sicher einsetzen — Task-Ledger
Status: erledigt · Branch: feature/desktop-identity-path-escape · Review: am Ende
Spec: Roadmap R-0425
Heavy: linux-full + windows — Desktop-Tunnel (CLAUDE.md §5): der Sammellauf fährt die Desktop-Tunnel-E2E unter Linux (dort ändert sich nichts, der Pfad hat keine Backslashes); `windows`, weil der Fehler nur mit Windows-Pfaden auftritt: dort läuft `cargo test` nativ (CI-Job `rust-windows`) und, soweit die Windows-Lane es hergibt, `frpc.exe verify -c` auf einer mit einem echten `%APPDATA%`-Pfad erzeugten Config. Die Desktop-GUI unter Windows bleibt laut `.claude/rules/testing.md` „nicht verifiziert“.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: R-0402 (desktop-tunnel-refresh, aktiv in der anderen Session; `frpc.rs` wird dort umgebaut — `rewrite_identity_paths` wandert dort nach `:225` und wird in `frpc_config` (`:357`) vor einem `toml::from_str` aufgerufen; Zeilenangaben vor dem Bau frisch greppen). Erst nach dem Merge von R-0402 bauen.

### T1 — Desktop: Identitätspfad als TOML-Basic-String escapen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @e59eff5a 2026-10-17T06:40:23+02:00
Review: am Ende (Branch-Review)
Änderung: `rewrite_identity_paths` (origin/main `frpc.rs:121`, nach R-0402 `:225`) setzt den absoluten Identitätspfad nicht mehr roh ein, sondern TOML-escaped für einen Basic-String (der Server-Generator schreibt den Platzhalter ausschließlich in doppelt gequotete Werte, `apps/server/app/modules/frp/config_generator.py:91-93`): `\` → `\\`, `"` → `\"`, Steuerzeichen U+0000–U+001F (außer Tab) und U+007F → `\uXXXX` (toml.io v1.0.0, Abschnitt String). Kein Literal-String (`'…'`): ein Windows-Benutzername darf `'` enthalten, und Literal-Strings können `'` nicht darstellen. Kommentar fürs Warum an der Funktion (Basic-String-Kontext des Platzhalters, Kopplung an `_VISITOR_IDENTITY_DIR`). Tests zuerst rot, Namen mit `identity_path`: (a) Windows-Pfad `C:\Users\O'Brien Test\AppData\Roaming\com.admincave.adminhelper\identity` in eine Visitor-TOML mit `[transport.tls]` eingesetzt → `toml::from_str` liest sie, und `certFile`/`keyFile`/`trustedCaFile` ergeben genau `<pfad>/cert.pem` usw. (ohne Fix rot: `\U`/`\O` sind ungültige bzw. reservierte Escapes); (b) Unix-Pfad mit `"` und Leerzeichen → ebenso Round-Trip; (c) der bestehende Test `rewrites_identity_placeholder_to_absolute` bleibt unverändert grün (Pfad ohne Sonderzeichen ändert sich nicht).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- identity_path
Doku: CHANGELOG.md (Fixed: Desktop-Tunnel startet unter Windows wieder, Identitätspfad wird TOML-korrekt eingesetzt)
Beweis: feature/desktop-tunnel-refresh@edfab4a0 Code-Lesung: `rewrite_identity_paths` = `toml.replace(IDENTITY_DIR_PLACEHOLDER, abs_identity_dir)` (`frpc.rs:225-227`), danach `toml::from_str` in `frpc_config` (`:357-361`) → auf Windows Parse-Fehler; origin/main@0f43781a dieselbe Funktion (`frpc.rs:121-123`), dort ohne Vorab-Parse, frpc 0.69.1 liest die Datei strikt (go-toml/v2, `pkg/config/load.go`); toml.io v1.0.0: „All other escape sequences not listed above are reserved; if they are used, TOML should produce an error.“ Auf Windows nicht ausgeführt.
Orakel: contract — TOML v1.0.0 Basic-String-Escaping; Round-Trip über den `toml`-Parser
Dedup-Key: bug:desktop:frpc.rs:identity-path-toml-escape
HEAD: 0f43781a
Semantik: docs/developer/desktop.html:145 — „schreibt visitor.toml und die PKI-Dateien in das App-Data-Verzeichnis (relative pki/-Pfade werden auf absolute umgeschrieben, .key-Dateien mit 0600) und startet anschließend frpc -c <config> als Sidecar.“ (der Tunnel soll mit dem App-Data-Pfad starten; ein Plattform-Vorbehalt steht dort nicht)
