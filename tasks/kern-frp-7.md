<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Ergebnis des Policy-Abgleichs nach Schlüssel-Erneuerung — Task-Ledger
Status: geplant · Branch: feature/kern-frp-7 · Review: am Ende
Spec: docs/features/kern-frp-7.md (Roadmap R-1437)
Heavy: none — additives Antwortfeld und UI-Hinweis; kein Stack-, Gateway- oder FRP-Datenpfad geändert
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: Rotation meldet policySynced  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/servers/router.py, apps/server/app/modules/servers/schemas.py, apps/server/tests/test_servers_frp_key_rotate.py, apps/server/tests/openapi.snapshot.json
Änderung: R-1437. `sync_policy` gibt `True`/`False` zurück; `rotate_frp_key` antwortet zusätzlich `policySynced`.
Test: Schreiben gelingt → `true`; `write_frps_policy` scheitert → `200`, Generation erhöht, `policySynced: false`.
OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_servers_frp_key_rotate.py tests/test_openapi_snapshot.py
Doku: → T3

### T2 — Desktop: Warnung bei nicht geschriebener Policy  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/frp.ts, apps/desktop/ui/src/components/infra/tabs/TunnelsTab.svelte, apps/desktop/ui/src/components/infra/tabs/TunnelsTab.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: R-1437. `rotateKey` liefert `{ generation, policySynced }`; bei `policySynced === false` eine Warnung
(DE+EN) statt der Erfolgsmeldung. Test für beide Fälle.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/TunnelsTab.test.ts
Doku: → T3
Abhängt von: T1

### T3 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, changelog.d/kern-frp-7.md
Änderung: Antwortfeld `policySynced` in der API-Referenz; ein Satz zur Warnung auf der Admin-Seite FRP-Tunnel;
Fragment unter `### Changed`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien
Task-Review: am Ende
Abhängt von: T2

## Entscheidungen
- Kevin 2026-11-14: Variante (a) `policySynced` plus Warnung in der UI.
