<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-9 — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-9 · Review: am Ende
Spec: docs/features/kern-ca-9.md (Roadmap R-1121)
Heavy: linux-full — Server-API und Desktop-Tunnel-Journey (tunnel-start startet den Visitor gegen frps)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@a17a8ae5`. Beide Code-Tasks liegen auf einem Risikopfad (FRP, PKI): `security` je Task, dazu je Task
ein `reviewer` trotz `Review: am Ende`. R-1054 fährt nicht mit (eigener Zug `tasks/kern-ca-10.md`, Frage an Kevin).

### T1 — Visitor-Bundle liefert den frps-Namen (R-1121)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/openapi.snapshot.json
Änderung: `VisitorBundleOut` bekommt `frps_tls_name: Optional[str]`; `gen_visitor_bundle` setzt es immer auf `frps.adminhelper.invalid` (Konstante mit Verweis auf `FRPS_TLS_NAME` im ca-issuer und `frpsTLSName` im Agent). Test: das Bundle trägt den Namen, die `visitor.toml` setzt weiter kein `serverName`; OpenAPI-Snapshot nachgezogen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_openapi_snapshot.py tests/test_response_shapes.py
Doku: → T3

### T2 — Desktop-Visitor setzt transport.tls.serverName aus dem Bundle (R-1121)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs
Änderung: `VisitorBundle` liest das optionale `frps_tls_name`; ist es da, schreibt der Desktop es nach `validate_visitor_table` als `transport.tls.serverName` in die Visitor-Konfiguration (nur mit `transport.tls`), ein anderer Wert als `frps.adminhelper.invalid` lehnt das Bundle ab. Ohne Feld bleibt alles wie bisher. Tests: mit Feld, ohne Feld, falscher Wert, Server-Text mit `serverName` weiter abgelehnt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc
Doku: → T3

### T3 — Doku DE+EN und Changelog (R-1121)  [ ]
Komponente: server · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-ca-9.md
Änderung: Tunnel-PKI: auch der Desktop-Visitor verlangt den Namen (ab einem Server, der ihn liefert); `visitor-bundle` liefert `{ toml, pki, frps_tls_name }`; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- 2026-11-04 Plan: Der Desktop nimmt nur genau `frps.adminhelper.invalid` an (Spec, Trade-offs): der Name ist fest, ein anderer Wert ist ein Fehler des Servers.
- 2026-11-04 Plan: R-1054 (Trust-Generation im Config-Hash) braucht einen API-Vertrag über ca-issuer, Server, Agent und Desktop (woher die Generation kommt, wie der Desktop sie erfährt); er fährt nicht in diesem Zug.
