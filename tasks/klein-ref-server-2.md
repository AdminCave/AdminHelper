<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-2 — Task-Ledger
Status: geplant · Branch: feature/klein-ref-server-2 · Review: am Ende
Spec: docs/features/klein-ref-server-2.md (Roadmap R-0869)
Heavy: none — interne Schema-Konfiguration und ein Test, keine Journey, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — UserMe ohne from_attributes, Test für den ADMIN_PASSWORD-Admin (R-0869)  [ ]
Komponente: server · Dateien: apps/server/app/modules/users/schemas.py, apps/server/tests/test_user_token_watermark.py
Änderung: `UserMe` verliert `model_config = {"from_attributes": True}`; `GET /api/auth/me` baut die Antwort aus Einzelwerten. Neuer Test: `_ensure_admin` mit gesetztem `ADMIN_PASSWORD` legt einen Admin an, dessen `tokens_valid_after` gesetzt und auf die ganze Sekunde gekürzt ist; ein Token mit `iat` eine Sekunde davor gilt nicht, eines ab dem Wasserzeichen gilt.
Beweis: Code-Lesung apps/server/app/modules/users/schemas.py:56, auth_router.py:318
Dedup-Key: ref:server:schemas.py:userme-from-attributes
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_user_token_watermark.py tests/test_openapi_snapshot.py
Doku: keine (interne Schema-Konfiguration, kein dokumentiertes Verhalten)
