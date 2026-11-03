<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-6 — Task-Ledger
Status: aktiv · Branch: feature/kern-ca-6 · Review: pro Task
Spec: docs/features/kern-ca-6.md (Roadmap R-1053, R-1109)
Heavy: linux-full — `apps/server/app/core/identity.py` (Server-Identität hinter dem Gateway) und der mTLS-Client des Desktops: der Sammellauf über `main` fährt Stack und Desktop-Journeys. Kein `scenario`: kein FRP-Datenpfad, keine Install-Pfade. Kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@ba79469e`. Details nur in `tasks/private/sec-kern-ca-6-notes.md`.

### T1 — Desktop: Server-Zertifikat im registrierten Zustand wie der Agent prüfen (R-1053)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-ca-6.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @e8c2ff76 2026-11-03T15:27:35+01:00
Review: approve (.ah-out/review/kern-ca-6/T1.verdict.json)
Änderung: `CaPinVerifier` nimmt nach erfolgreicher Kettenprüfung (auch im Namensfall) nur ein Leaf an, dessen Aussteller-CN `AdminHelper Access Intermediate` ist oder damit plus Leerzeichen beginnt (wie `isAccessIntermediate` im Agent); sonst Fehler ohne `ERR_CA_PIN_MISMATCH`. Echt-Handshake-Test mit einem Leaf eines anderen Intermediates unter derselben Root (rot ohne Fix); die Rotations-Tests bleiben grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enrollment
Doku: docs/developer/desktop.html + EN · changelog.d/kern-ca-6.md

### T2 — Server: Client-Zertifikat außerhalb seiner Laufzeit gilt nicht (R-1109)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/tests/test_identity_source.py, changelog.d/kern-ca-6.md, apps/server/tests/test_certificate_check.py, apps/server/tests/test_identity_revocation.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8769a66b 2026-11-03T15:09:27+01:00
Review: approve (.ah-out/review/kern-ca-6/T2.verdict.json)
Änderung: `get_client_identity` gibt die unverifizierte Identität zurück, wenn die Uhr vor `not_valid_before` oder ab `not_valid_after` des weitergereichten Zertifikats steht. Test mit abgelaufenem und noch nicht gültigem Zertifikat bei `X-Client-Verify: SUCCESS` (rot ohne Fix) und einem gültigen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_source.py tests/test_certificate_check.py tests/test_identity_revocation.py
Doku: changelog.d/kern-ca-6.md

### T3 — Zweiter Teil von R-1053  [~] (verschoben nach R-1112: Entscheidung bei Kevin, eigener Zug)
Komponente: server · Dateien: keine (eigener Zug)
Änderung: als eigener Zug (R-1112); Details in `tasks/private/`.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (bis zur Antwort)

### T4 — Server: eine Uhrzeit je Anfrage für die Laufzeitprüfung (R-1109)  [ ]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/tests/test_identity_source.py, docs/features/kern-ca-6.md, tasks/kern-ca-6.md
Änderung: `get_client_identity` liest die Uhr einmal je Anfrage (`request.state`, wie `_from_gateway`), damit Scope-Prüfung und Bindung an den Nutzer dieselbe Antwort sehen. Test, der die Uhr zwischen beiden Lesern über `not_after` schiebt (rot ohne Fix). Spec und Ledger zum zweiten Teil von R-1053 neutral gefasst.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_source.py tests/test_certificate_check.py tests/test_identity_revocation.py
Doku: keine (Verhalten wie T2 dokumentiert)

## Entscheidungen
