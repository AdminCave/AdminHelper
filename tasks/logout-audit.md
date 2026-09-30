<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Logout: Audit nur, wenn eine Sitzung endet (R-0105) — Task-Ledger
Status: bereit · Branch: feature/logout-audit · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0105
Heavy: none — nur die Bedingung um den Audit-Aufruf; Antwort, Status, Cookie-Verhalten, Security-Schema (R-0054) und Gateway bleiben gleich, pytest deckt jeden Zweig ab.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac); Entscheidung Kevin 2026-09-30: nur echte Sperrung protokollieren,
kein Rate-Limit am Gateway oder im Server. Zeilenangaben main@8224e84c.
Befund: `logout` (`apps/server/app/modules/users/auth_router.py:224–249`) sperrt einen mitgesendeten Bearer und den
Refresh-Token aus Body oder Cookie (`blacklist_token`, `app/core/auth.py:120–143`, liefert `True` nur bei einem neuen
Eintrag) und schreibt danach bedingungslos `audit.record("auth.logout", …)` (`:242–248`). Ein Logout, der nichts
beendet — kein oder ein ungültiger Token, ein abgelaufener Access-Token allein, dieselben Tokens ein zweites Mal —
schreibt so trotzdem einen Eintrag; ein Logout nur mit Cookie trägt keinen Benutzernamen. Heute prüft kein Test das
Logout-Audit (`tests/test_audit_wiring.py` kennt nur Login, `:88`/`:99`).

### T1 — `auth.logout` wird nur protokolliert, wenn der Logout einen Token gesperrt hat  [x]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/tests/test_audit_wiring.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @2c70c43e 2026-09-30T14:51:38+02:00
Review: am Ende (Kurz-Ledger, Gesamt-Review nach T1)
Änderung: In `logout` beide `blacklist_token`-Aufrufe immer ausführen und ihre Rückgaben zu `revoked` verbinden (kein
Kurzschluss wie `revoked = revoked or blacklist_token(…)`, sonst bliebe der Refresh-Token ungesperrt); `audit.record`
nur bei `revoked`. Wurde der Refresh-Token gesperrt und fehlt `uname`, kommt der Name aus
`username_from_token_unverified(refresh)`. Antwort (`{"detail": "Abgemeldet"}`, 200), Cookie-Löschung und Docstring
bleiben (der Docstring ist die OpenAPI-Beschreibung, `tests/openapi.snapshot.json`); das Warum steht als Kommentar.
Tests in `test_audit_wiring.py` neben `:88`: ohne Token, mit `Bearer garbage` und 50-mal ohne Token → 200, Cookie
gelöscht, 0 Einträge `auth.logout`; nur abgelaufener Access-Token (`create_access_token(…, expires_delta=timedelta(minutes=-5))`)
→ 0 Einträge; dieselben Tokens ein zweites Mal → kein weiterer Eintrag; nur Cookie → 1 Eintrag mit `object_label`
„admin“; Bearer plus Body → genau 1 Eintrag, Actor „admin“ (heute schon grün, Wächter gegen das stille Verschwinden
aller Logout-Einträge). Vor dem Fix rot: die ersten vier.
Beweis: main@8224e84c · Probe der Aufsicht (Explorer, 2026-09-30) gegen die Test-DB: ohne Token, mit `Bearer garbage`, mit nur abgelaufenem Access-Token und beim zweiten Aufruf mit denselben Tokens je 200 und ein Eintrag `auth.logout`; nur Cookie → Eintrag mit Label None
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_audit_wiring.py tests/test_auth.py tests/test_route_auth_gate.py
Doku: docs/developer/api-reference.html DE+EN (:60, ein Satz: protokolliert wird der Logout nur, wenn er einen Token gesperrt hat); docs/admin/betrieb.html:127 und docs/en/admin/operations.html:87 („Logout“ → „Logout, der eine Sitzung beendet“); CHANGELOG (Changed)
HEAD: 8224e84c
Semantik: docs/admin/betrieb.html:127 — „Sicherheits- und änderungsrelevante Aktionen werden in einem append-only Audit-Trail protokolliert … Erfasst werden u. a. … Logins (Erfolg/Fehlschlag), Logout …“; ein Logout, der keinen Token beendet, ist keine solche Aktion.
