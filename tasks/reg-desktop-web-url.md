# Web-Tunnel-URL ohne Pfad bleibt ohne Pfad — Task-Ledger
Status: bereit · Branch: feature/reg-desktop-web-url · Review: am Ende
Spec: Roadmap R-1665
Heavy: linux-full — Desktop-Journey über den Tunnel; Beweis vor dem Merge: bash scripts/tests/run.sh all --strict --step "desktop_e2e_connect_tunnel"
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1665: to_visitor behält eine URL ohne Pfad ohne Schrägstrich  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, changelog.d/reg-desktop-web-url.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @fddf95068 2026-11-20T09:58:49+01:00
Review: am Ende (Branch-Review)
Änderung: `to_visitor` setzt Host und Port über `Url`, dessen `to_string()` einen leeren Pfad als `/` schreibt. Hatte die gespeicherte URL keinen Pfad, bleibt das Ergebnis ohne `/` (`http://127.0.0.1:<port>`), mit Pfad unverändert. Der Unit-Test `stcp_web_keeps_scheme_path_and_query_of_the_url` bekommt den Fall „URL ohne Pfad“, erst rot.
Beweis: main@cc77b6d18 `tunnel.rs` to_visitor; `apps/desktop/e2e/test/specs/tunnel-connect.live.js:164` erwartet `http://127.0.0.1:<port>`, Step-Lauf desktop_e2e_connect_tunnel 2026-11-20 13 passed, 4 failed (url mit `/`)
HEAD: e8e3ff038
Dedup-Key: reg:desktop:tunnel.rs:web-url-trailing-slash
Semantik: docs/features/kern-frp-8.md:16-17 „ersetzt der Desktop nur Host und Port einer gespeicherten URL durch `127.0.0.1:<lokaler Port>`. Schema, Pfad und Query bleiben.“
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tunnel::tests::stcp_web_keeps_scheme_path_and_query_of_the_url
Doku: keine (Regression nie veröffentlicht, T2)

### T2 — Abschlussprüfung: Changelog-Fragment streichen  [x]
Komponente: desktop-rs · Dateien: changelog.d/reg-desktop-web-url.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @84aab4075 2026-11-20T10:12:04+01:00
Review: am Ende (Branch-Review)
Änderung: Der Verursacher cc77b6d18 ist in keinem Release (nicht in v0.47.0); der Fix ändert also kein veröffentlichtes Verhalten. Das Fragment, das eine „Regression aus 0.47.0“ nennt, fällt weg.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tunnel::tests::stcp_web_keeps_scheme_path_and_query_of_the_url
Doku: keine (Regression nie veröffentlicht)
Task-Review: am Ende
