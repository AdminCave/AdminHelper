<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Registrierungs-Token im Web-Panel — Task-Ledger
Status: bereit · Branch: feature/enroll-token-ui · Review: pro Task
Spec: docs/features/enroll-token-ui.md (Roadmap R-0396)
Heavy: linux-full — Server-API (`/api/enrollment/token/for`: neuer Parameter, neues Antwortfeld) und eine neue Web-Journey; `web-live`/`web-playwright` laufen im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: nur Web-Panel, Ablaufzeit vom Server (`expiresAt`), kein Browser-Token, Gültigkeit wählbar (10 min / 1 h / 24 h, API 1 bis 1440 Minuten). `mint_enrollment_token` (`service.py:29`) behält Signatur und Rückgabe; `apps/server/app/cli.py` bleibt unberührt (R-0397 baut dort).

### T1 — Server: `ttl_minutes` an `/token/for`, `expiresAt` in beiden Token-Antworten  [x]
Komponente: server · Dateien: apps/server/app/modules/enrollment/router.py, apps/server/app/modules/enrollment/service.py, apps/server/tests/test_enrollment_mint.py, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fc5c713e 2026-10-16T11:58:08+02:00
Review: approve (.ah-out/review/enroll-token-ui/T1.verdict.json)
Änderung: `EnrollmentTokenForRequest` (`router.py:88-90`) bekommt `ttl_minutes` (Ganzzahl 1 bis 1440, Standard 10; snake_case wie die übrigen Request-Felder, etwa `is_admin`); `mint_enrollment_token_for` mintet mit dieser TTL. `_mint_token` (`:36-52`) gibt zusätzlich `expiresAt` zurück: den gespeicherten `expires_at` der Token-Zeile als UTC mit `Z`, für `/token` und `/token/for`. Den Ablauf liefert eine neue Funktion neben `mint_enrollment_token` (oder die gespeicherte Zeile); deren Signatur bleibt. Das Audit-Detail von `enrollment.token.minted_for` nennt die TTL (`browser=False, ttl=60min`). Tests in `test_enrollment_mint.py`: Standard 10 min (`expiresAt` ≈ jetzt + 10 min, mit `Z`), `ttl_minutes: 60` und `1440` gespeichert und zurückgegeben, `0` und `1441` → 422, Audit-Detail mit TTL, `/token` liefert `expiresAt`. OpenAPI-Snapshot mit dem neuen Request-Feld nachziehen. API-Referenz DE+EN (`api-reference.html:158`): `ttl_minutes` und `expiresAt`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_enrollment_mint.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html

### T2 — Web-API: Token für einen Benutzer ausstellen  [x]
Komponente: web · Dateien: apps/web/src/lib/api/users.ts, apps/web/src/lib/api/types.ts, apps/web/src/lib/api/users.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @c8f0887f 2026-10-16T12:02:19+02:00
Review: approve (.ah-out/review/enroll-token-ui/T2.verdict.json)
Änderung: `mintEnrollToken(username, ttlMinutes)` in `users.ts` ruft `POST /api/enrollment/token/for` mit `{ username, ttl_minutes }`; Typ `EnrollmentGrant` (`token`, `subjectId`, `expiresAt`, …) in `types.ts`. Neuer Test `users.test.ts` (SPDX-Header) nach dem Muster von `audit.test.ts`: Pfad, Methode und Body.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/users.test.ts
Doku: keine (intern)
Abhängt von: T1

### T3 — Web-Oberfläche: Knopf in der Benutzerliste und Token-Dialog  [x]
Komponente: web · Dateien: apps/web/src/pages/Users.svelte, apps/web/src/modals/EnrollTokenModal.svelte, apps/web/src/modals/EnrollTokenModal.test.ts, apps/web/src/lib/i18n/dictionaries.ts, docs/admin/benutzer.html, docs/en/admin/users.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @85618c7a 2026-10-16T12:16:32+02:00
Review: approve (.ah-out/review/enroll-token-ui/T3.verdict.json)
Änderung: Je Zeile in `Users.svelte` (neben Bearbeiten/Löschen, `:104-110`) ein Knopf „Registrierungs-Token“. Er öffnet das neue `EnrollTokenModal.svelte` (SPDX-Header): zuerst die Gültigkeit wählen (10 min, 1 h, 24 h; voreingestellt 10 min) und „Ausstellen“; danach das Token genau einmal (Monospace), Kopieren wie in `KeyRevealModal.svelte`, „gültig bis <Ortszeit>“ aus `expiresAt` und der Hinweis, dass es einmalig ist und im Desktop unter „Gerät mit Token registrieren“ eingelöst wird. Ein Fehler der API erscheint als Fehler im Modal. Schließen verwirft das Token. Texte DE+EN in `dictionaries.ts`. Tests in `EnrollTokenModal.test.ts`: gewählte TTL geht an `mintEnrollToken`, Token und Ablaufzeit erscheinen, Kopieren schreibt das Token, ein API-Fehler wird angezeigt. Doku: Onboarding-Schritt 2 (`benutzer.html:91`, `users.html:85`) nennt den Knopf und die Gültigkeit; CHANGELOG unter `### Added`.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/EnrollTokenModal.test.ts
Doku: docs/admin/benutzer.html + docs/en/admin/users.html · CHANGELOG.md (Added)
Abhängt von: T2

### T4 — Playwright: Token ausstellen, einmal sehen  [x]
Komponente: web · Dateien: apps/web/tests/e2e/crud.spec.ts, apps/web/tests/e2e/mocks.ts, apps/web/tests/e2e/smoke.spec.ts-snapshots/users-chromium-linux.png, apps/web/src/lib/api/mocks.contract.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @d668276f 2026-10-16T12:28:04+02:00
Review: approve (.ah-out/review/enroll-token-ui/T4.verdict.json)
Änderung: Neuer Fall in `crud.spec.ts` nach dem Muster „API-Key anlegen -> Secret einmalig sichtbar“ (`:53`): Benutzerliste → „Registrierungs-Token“ → 1 h wählen → ausstellen → Token und Ablaufzeit sichtbar, der Request trug `ttl_minutes: 60` → schließen → Token nicht mehr im DOM. Mock für `POST enrollment/token/for` in `mocks.ts`; `mocks.contract.test.ts` prüft ihn gegen den OpenAPI-Snapshot aus T1. Die Playwright-Suite fährt die PR-CI (`ci.yml`, `npx playwright test`).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/mocks.contract.test.ts
Doku: keine (intern)
Abhängt von: T3
