<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-5 — Task-Ledger
Status: geplant · Branch: feature/klein-ref-server-5 · Review: am Ende
Spec: docs/features/klein-ref-server-5.md (Roadmap R-1176)
Heavy: none — Server-Validierung, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1176: Servernamen CONIN$/CONOUT$ ablehnen  [ ]
Komponente: server · Dateien: apps/server/app/modules/servers/schemas.py, apps/server/tests/test_servers_name_windows.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/klein-ref-server-5.md
Review: am Ende (Branch-Review)
Beweis: security-Review kern-server-7 2026-11-06 · apps/server/app/modules/servers/schemas.py _WINDOWS_DEVICE_NAMES · python3.13 `ntpath.isreserved('CONIN$')` → True
Änderung: `conin$` und `conout$` kommen in `_WINDOWS_DEVICE_NAMES`, der Fehlertext nennt sie. Test zuerst rot: `POST` mit `CONIN$`, `conout$` und `conin$.lab` ergibt 422; `PUT`-Umbenennung ebenso; ein gespeicherter Name `CONIN$` bleibt editierbar. `api-reference.html` DE+EN nennt die zwei Namen in der Aufzählung, `changelog.d/klein-ref-server-5.md` ein Eintrag (Changed).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_servers_name_windows.py tests/test_servers_schemas.py
Doku: die Änderung selbst (api-reference DE+EN, changelog.d)
