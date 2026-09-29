<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web-Client: kein null bei unlesbarem 2xx-Body (R-0107) — Task-Ledger
Status: geplant · Branch: feature/web-client-null-body · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0107
Heavy: linux-full — nur `run.sh integration`, Schritt `web_live`: der Client wird strenger, erst der echte Stack belegt, dass kein vom Web genutzter Endpunkt ein 2xx ohne JSON liefert und Login, Seiten und CRUD grün bleiben. Den seltenen Flake beweist ein grüner Lauf nicht; den Mechanismus beweisen T1 und T2. e2e nicht nötig, das gemockte chromium-Projekt läuft in der PR-CI.
DoD je Task: CLAUDE.md (Tests grün, eslint/svelte-check sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-29 von der Aufsicht (adminhelper-ac) auf Kevins Wort („Probleme lösen oder Vorschläge machen“).
Befund: `apps/web/tests/live/smoke.live.spec.ts:51–52` ruft nach dem Hash-Wechsel sofort `page.reload()` auf; die
neue Seite hat ihren Listen-Request schon abgeschickt. `apps/web/src/lib/api/client.ts:108–113` fängt ein
fehlschlagendes `res.json()` ab und gibt bei `res.ok` still `null` als `T` zurück (`:123`). Users (`pages/Users.svelte:72`),
ApiKeys (`:73`), Hooks (`:132`) und Audit (`:111`, `:143`) lesen `.length` auf der Antwort ohne null-Prüfung; ohne
`svelte:boundary` wird daraus der `pageerror` `Cannot read properties of null (reading 'length')`. Alle fünf
Listen-Endpunkte haben ein `response_model=list[...]`, der Catch ist der einzige Weg zu `null`. Der Smoke bleibt
unverändert — er hat einen echten Nutzerpfad (F5 während des Ladens) gefunden.

### T1 — client.ts: ein 2xx mit unlesbarem Body wirft ApiError statt null  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts, CHANGELOG.md, docs/developer/webui.html, docs/en/developer/webui.html
Änderung: `request()` (client.ts:108–123) parst nur bei `!res.ok` tolerant; bei `res.ok` und fehlschlagendem `res.json()`
wirft es `ApiError(res.status, 'Invalid response body')` (englisch wie die übrigen Meldungen). 204 (`:106`) und ein
gültiges JSON-`null` bleiben wie bisher. Neuer Test in `client.test.ts` nach dem vorhandenen Muster (`importClient()`,
`vi.stubGlobal('fetch')`): ein 200 mit einem Stream, der per AbortError abbricht, und ein 200 mit leerem Body;
erwartet wird jeweils die Ablehnung mit `ApiError`. Doku: webui.html DE+EN `:75` ein Satz zum Fehlerverhalten; dazu
`:65` DE+EN korrigieren (der Access-Token liegt nur im Speicher, nicht in localStorage — falsche Doku, `.claude/rules/docs.md`).
Beweis: main@718e0901 plus nur der neue Test · `bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts` → dreimal identisch rot „expected null to be an instance of Error"
Orakel: contract — `request<T>` verspricht `T` und liefert `null`
Dedup-Key: bug:web:apps/web/tests/live/smoke.live.spec.ts:page-error-null-length
HEAD: 718e0901
Semantik: keine Stelle in docs/ — docs/developer/webui.html:75 beschreibt nur Token und Refresh, nichts zu einem 2xx mit unlesbarem Body (offene Frage am Gate)
Verify: bash scripts/dev/verify.sh web --strict
Doku: CHANGELOG `[Unreleased]` Fixed; docs/developer/webui.html + docs/en/developer/webui.html (`:75` Fehlerverhalten, `:65` Token nur im Speicher)

### T2 — Seiten-Test: die Admin-Seiten überstehen einen unlesbaren 2xx-Body  [ ]
Komponente: web · Dateien: apps/web/src/pages.load.test.ts
Änderung: Neue Datei (SPDX-Kopf `GPL-3.0-or-later`, Kevin Stenzel). Rendert Users, ApiKeys, Hooks und Audit mit einem
fetch-Stub (Listen-Endpunkt 200 mit abbrechendem Body, Auth-Pfade 200 mit JSON) und erwartet `.page-title`, den
EmptyState, einen Fehler-Toast im `notifications`-Store und keinen unbehandelten Fehler. Schließt die Lücke, die
`src/mount.smoke.test.ts:20–23` ausdrücklich offenlässt.
Beweis: main@718e0901 plus nur dieser Test · `bash scripts/dev/verify.sh web --strict -- src/pages.load.test.ts` → dreimal identisch rot: fehlender Toast, dazu „TypeError: Cannot read properties of null (reading 'length')" (wörtlich die Smoke-Meldung)
Orakel: crash — die Smoke-Meldung ohne Stack
Dedup-Key: bug:web:apps/web/tests/live/smoke.live.spec.ts:page-error-null-length
HEAD: 718e0901
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (intern)
Abhängt von: T1
