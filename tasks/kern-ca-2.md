<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-2 — Task-Ledger
Status: geplant · Branch: feature/kern-ca-2 · Review: am Ende
Spec: docs/features/kern-ca-2.md (Roadmap R-0982, R-0945, R-0943)
Heavy: linux-full — `apps/ca-issuer` und `apps/agent` (Sammellauf: Stack mit Enrollment, `agent_monitoring`)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — Rotation: Uhrprüfung nur für ein Zwischenzertifikat des Scopes (R-0982)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/rotation.py, apps/ca-issuer/tests/test_rotation.py
Änderung: `_rotate` prüft notBefore nur, wenn `pki.intermediate_problem(old, scope, root)` nichts findet; ein fremdes `<scope>.crt` mit notBefore in der Zukunft wird ersetzt wie jedes fremde. Test: erst rot (RotationError mit Uhr-Meldung), dann grün; der Fall „eigenes Zwischenzertifikat in der Zukunft“ bleibt RotationError.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_rotation.py
Doku: keine (betrieb.html beschreibt die Uhrprüfung für Zwischenzertifikate des Scopes; das bleibt wahr)

### T2 — rotate-intermediates --compromised <scope> (R-0945)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/rotation.py, apps/ca-issuer/app/cli.py, apps/ca-issuer/tests/test_rotation.py, apps/ca-issuer/tests/test_cli.py, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-ca-2.md
Änderung: `rotate_intermediates(..., compromised=frozenset())`; für einen genannten Scope wird `<scope>-retired.pem` leer geschrieben und das abgelöste nicht behalten; unbekannte Scopes sind ein Fehler vor dem ersten Schreiben. CLI `--compromised SCOPE` (mehrfach, Auswahl aus `pki.SCOPES`), Ausgabe nennt je Scope, dass nichts abgelöst vertraut bleibt. Tests für Rotation und CLI.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_rotation.py tests/test_cli.py
Doku: docs/admin/betrieb.html#ca-rotation · docs/en/admin/operations.html#ca-rotation · changelog.d/kern-ca-2.md
Abhängt von: T1

### T3 — Agent: Server-Zertifikat nur vom access-Zwischenzertifikat (R-0943)  [ ]
Komponente: agent · Dateien: apps/agent/internal/httpclient/httpclient.go, apps/agent/internal/httpclient/httpclient_test.go, changelog.d/kern-ca-2.md
Änderung: `NewMTLS` setzt `VerifyConnection`: das Zertifikat nach dem Leaf in der geprüften Kette hat den CN `AdminHelper Access Intermediate` oder `AdminHelper Access Intermediate <Label>`; sonst Abbruch mit klarer Meldung. Tests mit einer Test-PKI: Gateway-artiges Leaf unter access → ok; Leaf unter tunnel → abgelehnt.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestNewMTLS
Doku: changelog.d/kern-ca-2.md

## Entscheidungen
