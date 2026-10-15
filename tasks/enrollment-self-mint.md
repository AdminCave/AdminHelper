<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Self-Mint bleibt: Audit nennt das langlebige Leaf, die API-Referenz stimmt — Task-Ledger
Status: geplant · Branch: feature/enrollment-self-mint · Review: am Ende
Spec: Roadmap R-0204
Heavy: none — nur der Audit-Detailtext und Doku; Route, Schema, Token und Zertifikat bleiben unverändert, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-15: `POST /api/enrollment/token` bleibt mit beiden Zweigen; ein angemeldeter Benutzer darf ohne Admin
ein weiteres eigenes Gerät registrieren. Das Audit des Self-Mints wird an `/token/for` angeglichen. Risikopfad
(Enrollment): Branch-Review zusätzlich mit `security`.

### T1 — Self-Mint: Audit nennt das langlebige Leaf, API-Referenz beschreibt den Endpunkt richtig  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/router.py, apps/server/tests/test_enrollment_mint.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: Der Audit-Eintrag des Self-Mints (`router.py:70`, heute `browser={browser} (self)`) vermerkt bei `browser=true` dasselbe wie `/token/for` (`router.py:110`: langlebiges Leaf, widerrufbar nur unter `MTLS_ENFORCE=true`), weiterhin mit `(self)`; ein Test in `test_enrollment_mint.py` prüft den Detailtext wie `test_admin_mint_for_browser_flags_long_lived_leaf` (`:171`). Die API-Referenz DE+EN (`api-reference.html:157`) streicht „kein Cert nötig — Bootstrap-Tür“ (unter `MTLS_ENFORCE=true`, dem Standard, erreicht nur ein Gerät mit gültigem Client-Zertifikat den Endpunkt) und nennt den Zweck: ein weiteres eigenes Gerät ohne Admin registrieren; `?browser=true` für das langlebige Leaf des Browser-P12-Exports. CHANGELOG unter Changed.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_enrollment_mint.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html · CHANGELOG
Beweis: Opus-Review remove-enroll-device 2026-10-06 (feature/remove-enroll-device@7b55a8db, grep der Aufrufer); neu gegrept auf main@63b55121: einziger First-Party-Aufrufer `apps/desktop/src-tauri/src/enrollment.rs:434` mit `?browser=true`, Skripte nutzen `python -m app.cli mint-enroll-token`; Audit-Detail heute `router.py:70` ohne Hinweis auf das langlebige Leaf, `/token/for` mit (`router.py:110`)
Dedup-Key: ref:server:enrollment/router.py:token-nonbrowser
HEAD: 63b55121
Semantik: docs/developer/server.html:65 — „`POST /token` für den angemeldeten Benutzer (Selbstbedienung)“; dazu Kevins Entscheidung 2026-10-15 (Selbstbedienung gewollt)
