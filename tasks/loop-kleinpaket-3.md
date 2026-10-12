<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Kleinpaket 3: Server- und Desktop-Entwicklerdoku nach dem Zertifikats-Register — Task-Ledger
Status: bereit · Branch: feature/loop-kleinpaket-3 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0284, R-0285, R-0296, Loop-Futter aus Kevins Triage 2026-10-11; fuer den Builder-Loop geschnitten; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0284, R-0285, R-0296 (Kurz-Ledger ohne Spec)
Heavy: none — Doku unter docs/developer (DE+EN) und ein Docstring in den Server-Tests; kein Code, kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Doku DE+EN im selben Commit, Doku-Smoke und docs-pairs sauber, ruff sauber).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus drei Zeilen, die Kevin am 2026-10-11 als
Loop-Futter triagiert hat. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der
Aufsicht. Zeilenangaben origin/main@bf41e8d8. Jede Task ist für eine Bau-Session allein geschnitten: eine Komponente,
alle Fakten in der Task, das Verify zuerst, danach der Doku-Smoke.

Schon erledigt und nicht Teil des Pakets: `server.html:153` (DE und EN) nennt die Tabellen des Registers sowie
`EnrollmentToken` und `RevokedIdentity` seit Phase B. Von R-0285 bleibt die Router-Tabelle.

### T1 — server.html: der Drift-Test heißt richtig, der Enrollment-Router steht in der Tabelle, DE und EN (R-0284, R-0285)  [x]
Komponente: scripts · Dateien: docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b0d97213 2026-10-12T16:09:52+02:00
Review: approve (sonnet/high) · round 1
Änderung, in beiden Sprachen an denselben Stellen:
- `:146` und `:212` nennen `test_alembic_consistency.py`. Die Datei gibt es nicht. Den Abgleich von Modellen und
  Migrationen machen heute zwei Tests in `apps/server/tests/`:
  - `test_alembic_builtin.py`: die eingebauten Tests von pytest-alembic. Genau ein Head, jede Revision der Reihe nach,
    Modelle gleich DDL nach dem vollen Lauf, jede Revision übersteht Down und Up; dazu eine Datenmigration mit Daten.
  - `test_migrations_smoke.py`: `upgrade head` auf einer leeren Datenbank ergibt die Modelle.
  Beide Sätze nennen diese zwei statt der fehlenden Datei.
- Die Router-Tabelle (`:54-66`) bekommt eine Zeile für `/api/enrollment` (`modules/enrollment/router.py`, eingehängt in
  `app/main.py:290`), nach der Zeile `/api/servers/{id}/provision`. Funktion, wie die Docstrings der Routen sie
  beschreiben:
  - `POST /token`: Einmal-Token für den angemeldeten Benutzer (Selbstbedienung).
  - `POST /token/for`: Einmal-Token, das ein Admin für einen anderen Benutzer ausstellt (ADR 0003).
  - `POST /self/revoke`: Ein Gerät widerruft sich selbst, ausgewiesen durch sein Client-Zertifikat, ohne JWT.
- Die Zeile `/api/users` nennt dazu die Geräte eines Benutzers (`/{id}/devices`: auflisten, eines widerrufen; admin).
- `:52`: „11 Top-Level-Router“ (EN „Eleven top-level routers“) wird die Zahl der Zeilen in der Tabelle danach (12).
Neutral, nur die Funktion, wie in `docs/developer/api-reference.html`.
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --paths --env --strict
Doku: docs/developer/server.html + docs/en/developer/server.html (die Task ist die Doku)
Beweis: origin/main@bf41e8d8: `git grep -c test_alembic_consistency -- docs/developer/server.html
docs/en/developer/server.html` → je 2; `git ls-files apps/server/tests | grep -c test_alembic_consistency` → 0;
`app/main.py:290` hängt `enrollment_router` ein, die Router-Tabelle (`server.html:54-66`) hat keine Zeile dafür.
Metrik: Nennungen von `test_alembic_consistency.py` außerhalb von `CHANGELOG.md`, `git grep -c` (git 2.47.3): 5 → 1
(übrig `conftest.py`, T2); Zeilen der Router-Tabelle 11 → 12.
Dedup-Key: ref:docs:server.html:alembic-consistency-test
HEAD: bf41e8d8
Semantik: `apps/server/tests/test_alembic_builtin.py:5-12` (die vier eingebauten Prüfungen, darunter „do the models still
match the DDL after the full run“); `server.html:52`: „11 Top-Level-Router unter `apps/server/app/modules/`; jedes Modul
kapselt Models, Schemas und Routen.“

### T2 — Server-Tests: der Docstring von pg_engine nennt den richtigen Drift-Test (R-0284)  [x]
Komponente: server · Dateien: apps/server/tests/conftest.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @a4e93f62 2026-10-12T16:34:40+02:00
Review: approve (sonnet/high) · round 1
Änderung: Der Docstring der Fixture `pg_engine` (`conftest.py:120-129`) sagt, der Drift zwischen Modellen und Alembic
werde „separately against the models set in test_alembic_consistency.py“ geprüft. Er nennt künftig
`test_alembic_builtin.py` (pytest-alembic, unter anderem Modelle gleich DDL) und `test_migrations_smoke.py`. Nur der
Docstring; am Code der Fixture ändert sich nichts.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_alembic_builtin.py tests/test_migrations_smoke.py
Doku: keine (ein Docstring)
Beweis: origin/main@bf41e8d8: `git grep -n test_alembic_consistency -- apps/server` → `apps/server/tests/conftest.py:128`.
Metrik: Nennungen von `test_alembic_consistency.py` außerhalb von `CHANGELOG.md`, `git grep -c` (git 2.47.3): nach T1
1 → 0. Die Einträge im CHANGELOG sind Historie und bleiben.
Dedup-Key: ref:docs:server.html:alembic-consistency-test
HEAD: bf41e8d8
Semantik: `apps/server/tests/test_alembic_builtin.py:5-12`, wie in T1.

### T3 — desktop.html: Zurücksetzen widerruft zuerst am Server, DE und EN (R-0296)  [x]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @91fd810d 2026-10-12T17:00:46+02:00
Review: approve (sonnet/high) · round 1
Änderung: Der Punkt zu `reset_device_identity` (`desktop.html:129`, EN ebenso) beschreibt nur das Löschen. Der Ablauf
ist (`apps/desktop/src-tauri/src/enrollment.rs:262-330`):
- Zuerst widerruft der Client das Gerät am Server mit genau diesem Zertifikat: `POST /api/enrollment/self/revoke` über
  den mTLS-Client, ohne JWT (`revoke_on_server`, `:318`). Erst danach löscht er die Identität und den Pin.
- Das Ergebnis ist ein `ResetOutcome` (`:265`): `revoked` (der Server hat widerrufen oder das Zertifikat schon
  abgelehnt), `localOnly` (der Server hat nicht widerrufen, etwa weil er nicht erreichbar war) oder `notEnrolled`.
- Bei `localOnly` merkt sich der Client den Fingerprint des alten Zertifikats im Keyring (`enroll|replaces`, `:40`) und
  nennt ihn beim nächsten Registrieren als `replaces` (`:377`); die UI zeigt dazu den Hinweis „nur auf diesem Gerät“.
- Der Satz „nur sichtbar wenn registriert und angemeldet“ stimmt nicht mehr ganz: Der Login-Screen bietet das
  Zurücksetzen ebenfalls an, bei `ERR_CA_PIN_MISMATCH`, `ERR_CERT_USER_MISMATCH` und `ERR_CERT_REVOKED`
  (`apps/desktop/ui/src/components/Login.svelte:57-68`). Der Punkt nennt beide Orte.
Neutral, nur die Funktion, wie in `docs/admin/benutzer.html:108`.
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --paths --env --strict
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (die Task ist die Doku)
Beweis: origin/main@bf41e8d8: `git grep -c 'self/revoke' -- docs/developer/desktop.html docs/en/developer/desktop.html`
→ je 0; der Punkt `:129` beschreibt nur das Löschen.
Metrik: Nennungen von `self/revoke` in `docs/developer/desktop.html` und EN, `git grep -c` (git 2.47.3): 0 → je 1.
Dedup-Key: ref:docs:desktop.html:reset-revokes-server
HEAD: bf41e8d8
Semantik: `docs/admin/benutzer.html:108`: „„Geräte-Identität zurücksetzen“ (Desktop) widerruft das Gerät zuerst am
Server und löscht dann sein Zertifikat auf dem Gerät.“
