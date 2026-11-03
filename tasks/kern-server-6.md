<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-6 — Task-Ledger
Status: bereit · Branch: feature/kern-server-6 · Review: am Ende
Spec: docs/features/kern-server-6.md (Roadmap R-1059)
Heavy: none — eine Bedingung in der Neuprüfung des Streams; kein Stack-, Gateway-, PKI- oder Install-Pfad ändert sich, und die schweren Suiten lassen kein Zertifikat während eines offenen Streams ablaufen
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Stream-Neuprüfung beachtet den Ablauf des Zertifikats (R-1059)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/stream.py, apps/server/tests/test_stream.py, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-server-6.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @df30ae5f 2026-11-03T02:38:01+01:00
Review: am Ende (Branch-Review)
Änderung: `_stream_reauth_ok` gibt `False` zurück, wenn die Identität verifiziert ist und ihr `not_after` (naive UTC) vor der aktuellen Zeit liegt; der offene Stream gibt `not_after` über `identity` schon mit. Tests: abgelaufen → False, gültig → True, nicht verifiziert ohne `not_after` → True; Gegenprobe ohne die Bedingung rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_stream.py
Doku: docs/developer/server.html, docs/en/developer/server.html (Absatz „Push (SSE)“) · changelog.d/kern-server-6.md

## Entscheidungen
