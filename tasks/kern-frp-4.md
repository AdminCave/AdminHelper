<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-frp-4 — Task-Ledger
Status: aktiv · Branch: feature/kern-frp-4 · Review: am Ende
Spec: docs/features/kern-frp-4.md (Roadmap R-1120)
Heavy: linux-full — `apps/agent` (frpc-Sync); der Sammellauf fährt Agent-Install und Tunnel-Sync
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Risikopfad (FRP): `security` prüft die Task und den Branch.

### T1 — TLS-Teil des Server-Texts nur in der Form des Generators (R-1120)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/apply_test.go, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-frp-4.md, apps/agent/internal/frpc/lock_test.go, apps/agent/internal/frpc/sync_windows_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c72a0acc 2026-11-04T06:48:14+01:00
Review: am Ende (Branch-Review)
Änderung: `checkServerConfig` (`servertoml.go:73`) verlangt `transport.tls.enable = true` und die drei Identitätspfade als Werte von `trustedCaFile`, `certFile`, `keyFile`, alle vier vorhanden, in Tabellen- wie in Wurzelform; der Fehler nennt Zeile und Schlüssel (fehlend: den Schlüssel), nie den Wert. Tests zuerst rot: je Schlüssel ein anderer Wert, je Schlüssel fehlend, `enable = "true"`, beide Formen; die Generator-Fixture besteht weiter. Testtexte ohne TLS-Teil (`servertoml_test.go`, `sync_flow_test.go`, `apply_test.go`) bekommen den Generator-Teil.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/developer/agent.html + EN · changelog.d/kern-frp-4.md

### T2 — Changelog-Fragment ohne Umlaute (R-1120)  [ ]
Komponente: scripts · Dateien: changelog.d/kern-frp-4.md
Änderung: Das Fragment schreibt „uebernimmt“ und „Identitaetspfade“; Fragmente sind umlautfrei (`.claude/rules/docs.md`, `changelog.d/README.md`). Fund der Abschlussprüfung.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: changelog.d/kern-frp-4.md

## Entscheidungen
- Plan: `serverAddr` bleibt frei (Spec, Trade-offs); der Titel der Zeile nennt „Ziel“, das deckt der feste TLS-Teil mit dem Namen, den der Agent setzt.
