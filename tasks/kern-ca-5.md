<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-5 — Task-Ledger
Status: geplant · Branch: feature/kern-ca-5 · Review: am Ende
Spec: docs/features/kern-ca-5.md (Roadmap R-1026)
Heavy: linux-full — Server-Identität hinter dem Gateway (mTLS); der Stack-Test öffnet den Stream mit Zertifikat
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@8c4fe2f5`, vor dem Bauen neu greppen. Neue Code-Strings englisch, CHANGELOG umlautfrei.
`security` bei T1; Details zu R-1026 nur in `tasks/private/`.

### T1 — Stream-Neuprüfung: Client-Zertifikat ganz neu prüfen (R-1026)  [ ]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/modules/notifications/stream.py, apps/server/tests/test_stream.py, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-ca-5.md
Änderung: `ClientIdentity` behält das Zertifikat vom Connect (ohne `repr`/Vergleich); `_stream_reauth_ok` (`stream.py:45`) rechnet die Prüfung, die `get_client_identity` beim Connect macht und die vom Stand der Vertrauensdateien abhängt, vor `_is_revoked` neu. Test (erst rot): ein Stream, dessen Zertifikat beim Connect besteht und nach einer Änderung der Vertrauensdatei nicht mehr, endet bei der Neuprüfung.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_stream.py tests/test_identity_issuer.py
Doku: docs/developer/server.html, docs/en/developer/server.html (Absatz „Push (SSE)“), changelog.d/kern-ca-5.md

## Entscheidungen
