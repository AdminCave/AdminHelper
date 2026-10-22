<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web-Stores: nach dem Anlegen nur die Felder der Liste halten — Task-Ledger
Status: geplant · Branch: feature/web-store-cleanup · Review: am Ende
Spec: docs/features/web-store-cleanup.md (Härtung, Kevin 2026-10-22)
Heavy: none — nur zwei Web-Stores, ihre Unit-Tests und ein Satz Entwickler-Doku; keine Route, kein Schema, keine Migration, kein Server-, Gateway-, PKI-, FRP-Datenpfad-, Compose- oder Install-Pfad (die FRP-Server-Konfiguration selbst ändert sich nicht, nur was die Seite nach dem Speichern behält); die Web-E2E mockt `/api/hooks` und `/api/frp/server-config` (`apps/web/tests/e2e/mocks.ts`) und läuft in der PR-CI
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Nach `create` und `update` hält der Hooks-Store je Hook genau die Felder von `Hook` (die der Listenantwort),
kein `token`, kein `script`; `create` gibt die ganze Antwort weiter an den Aufrufer. (2) Der FRP-Store hält die
Konfiguration nach `save` so, wie `GET` sie liefert: `authToken` und `dashboardPassword` `null`. Zeilenangaben:
origin/main@b1432223; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1, dann T2 (T2 schreibt den Doku-Satz und den CHANGELOG-Eintrag für beide Stores).
- Kein Pfad aus `scripts/dev/review-risk.txt`; `Review: am Ende` (ein Review über den Branch-Diff).
- Kein Server-Code, keine Änderung an `apps/web/src/lib/api/types.ts` (dort ändert hooks-followups `HookRunResult`).
- Parallel: web-fixes (R-0653, Leeren der Stores beim Abmelden) ändert dieselben Store-Dateien; wer später gemergt
  wird, merged `origin/main` vor dem Push und fährt beide Store-Tests.
- Neue Code-Kommentare englisch; Testwerte erkennbar unecht (`whk_s3cr3t`, `frp-s3cr3t-token`).

### T1 — Hooks-Store: Liste nur mit den Feldern von `Hook`  [ ]
Komponente: web · Dateien: apps/web/src/lib/stores/hooks.ts, apps/web/src/lib/stores/hooks.test.ts
Änderung: Neu in `hooks.ts`: eine Feldliste `HOOK_FIELDS` der `Hook`-Felder (`apps/web/src/lib/api/types.ts:93-104`: `id`, `name`, `description`, `hook_type`, `enabled`, `created_at`, `event_triggers`, `schedule_interval`, `last_run`, `next_run`) und eine Projektion `toListEntry(h: Hook): Hook`, die nur diese Felder übernimmt, und nur die, die die Antwort trägt (sonst überschriebe `update` einen vorhandenen Wert mit `undefined`). Die Feldliste ist typgeprüft: fehlt ihr ein Schlüssel von `Hook`, meldet `npm run check` einen Fehler (etwa `satisfies readonly (keyof Hook)[]` und eine Zuweisung, die nur bei `Exclude<keyof Hook, (typeof HOOK_FIELDS)[number]>` gleich `never` kompiliert). Ein Kommentar nennt das Warum: die Liste trägt nur, was `GET /api/hooks` liefert (`apps/server/app/modules/hooks/router.py:127`, `HookResponse`); `token` und `script` aus der Create- und Detail-Antwort gehören nicht hinein. `create` (`hooks.ts:24-29`) hängt `toListEntry(created)` an (`:27`) und gibt weiter `created` zurück (der Token wird über `HookModal.svelte:105-107` und `Hooks.svelte:62-69` einmal angezeigt); `update` (`:31-36`) merged `toListEntry(updated)` (`:34`). `refresh`, `remove` und `toggle` bleiben (die Antwort von `toggle` ist schon `HookResponse`, `router.py:302`). Tests in `hooks.test.ts` (Kopfkommentar `:5-6` anpassen): (a) `create` mit der Antwort `{ ...h('b'), script: 'print("s3cr3t-script")', token: 'whk_s3cr3t' }` → der Eintrag `b` hat weder `token` noch `script` als Schlüssel, `JSON.stringify(get(hooks))` enthält weder `whk_s3cr3t` noch `s3cr3t-script`, die Rückgabe trägt `token: 'whk_s3cr3t'`; (b) `update('a', …)` mit der Antwort `{ ...h('a'), name: 'renamed', script: 'print("s3cr3t-script")' }` → `a` heißt `renamed` und hat kein `script`, `b` ist unverändert; (c) Liste mit `{ ...h('a'), description: 'keep' }`, `update` mit einer Antwort ohne `description` → `description` bleibt `keep` (der Merge wie bisher). Zuerst rot: (a) und (b) auf HEAD. Die bestehenden Tests (`:46-52`, `:54-60`) bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/hooks.test.ts
Doku: keine (den Satz in `docs/developer/webui.html` und den CHANGELOG-Eintrag für beide Stores schreibt T2)
Beweis: Code-Lesung apps/web/src/lib/stores/hooks.ts:27, :34
Orakel: contract — ein Listeneintrag hat nur Schlüssel von `Hook`, und eine Feldliste ohne einen Schlüssel von `Hook` macht `npm run check` rot
HEAD: b1432223

### T2 — FRP-Store: Konfiguration ohne `authToken` und `dashboardPassword` halten  [ ]
Komponente: web · Dateien: apps/web/src/lib/stores/frp.ts, apps/web/src/lib/stores/frp.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Änderung: `save` (`apps/web/src/lib/stores/frp.ts:19-25`) setzt in der Antwort `authToken` und `dashboardPassword` auf `null`, legt dieses Objekt in den Store (`:23`) und gibt es zurück — so, wie `GET` und `PUT` die Konfiguration liefern (`apps/server/app/modules/frp/config_router.py:38`, `:189`; `apps/server/app/modules/frp/models.py:42-46`, `:53`, `:58`). Das gilt für beide Zweige, Anlegen und Ändern, damit der Store sich nicht auf die Maske des `PUT` verlässt. Ein Kommentar nennt das Warum: die Antwort auf das Anlegen trägt beide Werte im Klartext (`config_router.py:96`), und die Oberfläche liest sie nie (`apps/web/src/modals/FrpConfigModal.svelte:49-57`, `:85-96`, `:136`). `refresh` bleibt. Tests in `frp.test.ts`: (a) `save(INPUT, null)` mit der Antwort `{ ...cfg('new'), authToken: 'frp-s3cr3t-token', dashboardPassword: 'dash-s3cr3t' }` → `get(frpConfig)` hat `authToken` und `dashboardPassword` gleich `null` und sonst die Felder der Antwort, `JSON.stringify(get(frpConfig))` enthält keinen der beiden Werte, die Rückgabe von `save` ebenso; (b) dasselbe für `save(INPUT, cfg('1'))` über `updateConfig`. Zuerst rot: (a) und (b) auf HEAD. Die bestehenden Tests (`:37-51`, `:54-61`) bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/frp.test.ts
Doku: `docs/developer/webui.html:64` + `docs/en/developer/webui.html:64` (Abschnitt „Stores“, ein Satz nach dem ersten: die Daten-Stores halten nur, was die Listen- bzw. Leseantwort trägt; ein einmalig angezeigter Wert aus einer Create-Antwort, API-Key oder Webhook-Token, geht nur an den Aufrufer; `authToken` und `dashboardPassword` der FRP-Server-Konfiguration hält der Store als `null`, wie `GET` sie liefert) · CHANGELOG.md (`[Unreleased]`, neuer Abschnitt `### Changed`, umlautfrei: „**Web: Stores halten nach dem Anlegen nur die Felder der Liste:** Webhook-Token und Skript eines neuen oder bearbeiteten Hooks sowie Auth-Token und Dashboard-Passwort einer neuen FRP-Server-Konfiguration bleiben nicht bis zum Neuladen im Speicher der Seite; der Webhook-Token wird wie bisher einmal angezeigt. Doku: Web-UI fuer Entwickler (DE+EN).“)
Abhängt von: T1
Beweis: Code-Lesung apps/web/src/lib/stores/frp.ts:23, apps/server/app/modules/frp/config_router.py:96
Orakel: contract — der Store hält die FRP-Konfiguration in der Form der `GET`-Antwort
HEAD: b1432223
