<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: Theme-Skript unter der CSP, Frist des Hook-Laufs, Abmelden, Selbst-Bearbeitung, Seitenspeicher, confirmDialog — Task-Ledger
Status: erledigt · Branch: feature/web-fixes · Review: pro Task
Spec: docs/features/web-fixes.md (Roadmap R-0654, R-0647, R-0648, R-0653, R-0652, R-0476)
Heavy: none — nur `apps/web` und Doku; kein Server-, Gateway-, PKI-, FRP-, Compose- oder Install-Pfad, keine Route, kein Schema, kein CSP-Header (`apps/server/app/main.py:443-453` bleibt); die Web-E2E samt neuem Projekt `chromium-build` (T3) fährt die PR-CI im Job `frontend-e2e`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Ein gesperrter Seitenspeicher lässt die App starten. (2) Das Theme-Skript läuft als Datei unter
`script-src 'self'`, belegt gegen den Build. (3) Der manuelle Hook-Lauf wartet 75 s, der Timeout-Text ist übersetzt.
(4) Abmelden leert die Stores, und eine neue Anmeldung wartet auf die Antwort der Abmeldung. (5) Selbst-Bearbeitung
führt den Auth-Store nach; eigener Passwortwechsel meldet mit Hinweis ab. (6) `confirmDialog` ohne Sitzung liefert
`false`. Zeilenangaben: origin/main@b1432223; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 bis T8 nacheinander (ein Bauer). Echte Abhängigkeiten: T3 nach T2, T6 nach T5, T7 nach T6.
  T1 und T4 ändern beide `client.ts`, T6 und T7 beide `auth.ts`, T4 und T7 beide `dictionaries.ts`.
- Nicht anfassen: `apps/web/src/lib/api/types.ts` und `apps/web/src/lib/api/hooks.test.ts` (offener PR #254),
  `apps/web/src/modals/HookModal.svelte` (anderes Vorhaben), alles unter `apps/desktop/`.
- Neue Code-Strings englisch (Kommentare, feste Texte); UI-Texte über `dictionaries.ts` in DE und EN, die Parität
  prüft `src/lib/i18n/i18n.test.ts`. CHANGELOG-Einträge unter `## [Unreleased]`, umlautfrei, Gedankenstrich „—“.
- Neue Testdateien mit SPDX-Header wie `apps/web/src/lib/stores/users.test.ts:1-3`; Mocks per `vi.mock` wie dort.
  Ein Test, der den globalen `localStorage`-Getter ersetzt, merkt sich den Deskriptor
  (`Object.getOwnPropertyDescriptor(globalThis, 'localStorage')`) und stellt ihn im `afterEach` wieder her (vitest
  legt die jsdom-Globals als konfigurierbare Accessoren an).
- Revert-Proben nur in einem eigenen Probe-Worktree (CLAUDE.md §5), `node_modules` dort per `cp -al`, nicht als
  Symlink (vitest lädt sonst keinen Test), und nicht unter `/tmp`.

### T1 — Seitenspeicher: Zugriffe über einen Helfer, der nie wirft (R-0654)  [x]
Komponente: web · Dateien: apps/web/src/lib/utils/storage.ts, apps/web/src/lib/utils/storage.test.ts, apps/web/src/lib/api/client.ts, apps/web/src/lib/i18n/index.ts, CHANGELOG.md, apps/web/src/lib/i18n/translate.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @97f45c74 2026-10-22T10:26:54+02:00
Review: approve (.ah-out/review/web-fixes/T1.verdict.json)
Änderung: Neu `apps/web/src/lib/utils/storage.ts` (SPDX-Header): `storageGet(key): string | null`, `storageSet(key, value): void`, `storageRemove(key): void`, je ein `localStorage`-Zugriff in `try`/`catch` (Fehler → `null` bzw. nichts); ein Kommentar nennt das Warum: blockiert der Browser die Website-Daten, wirft schon der Getter `window.localStorage` einen `SecurityError`, auch unter `typeof`. `client.ts:13-14` ruft `storageRemove(…)` für beide alten Schlüssel; `i18n/index.ts` liest in `detect()` (`:11-18`) mit `storageGet` und schreibt im `subscribe` (`:22-29`) mit `storageSet`, die beiden `typeof localStorage`-Prüfungen entfallen. `theme.ts` bleibt (eigener `try`/`catch`, `:36-40`). Tests in `storage.test.ts`: (a) mit funktionierendem Speicher reichen die Helfer Lesen, Schreiben und Löschen durch; (b) mit einem Getter, der `new DOMException('denied', 'SecurityError')` wirft: `storageGet` → `null`, `storageSet`/`storageRemove` werfen nicht; (c) mit demselben Getter, nach `vi.resetModules()`: `await import('$lib/api/client')` und `await import('$lib/i18n')` werden erfüllt (nicht verworfen), `get(language)` ist die Sprache aus `navigator.language` (`'en'` oder `'de'`, wie `detect()` sie bildet). Zuerst rot: (b) und (c) auf HEAD (das Modul fehlt; der Import von `client` verwirft mit `SecurityError`). `client.test.ts` bleibt unverändert grün (es ersetzt `localStorage` per `vi.stubGlobal`).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/utils/storage.test.ts src/lib/api/client.test.ts src/lib/i18n
Doku: CHANGELOG.md (Fixed: Web-Panel startet auch bei gesperrtem Seitenspeicher — Login-Maske statt leerer Seite, Sprache aus dem Browser)
Beweis: origin/main@b1432223 · Probe (Node 22.23.1): `Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new DOMException('…', 'SecurityError') } })`, danach dreimal `typeof localStorage` → dreimal „throws SecurityError“, `localStorage.removeItem('x')` → „removeItem throws SecurityError“; Code-Lesung `apps/web/src/lib/api/client.ts:13-14`, `apps/web/src/lib/i18n/index.ts:12-13`, `:23-24` (laufen beim Modul-Import). Der Test (c) ist auf HEAD rot (der builder zeigt es dreimal identisch vor dem Fix)
Orakel: crash — der Import von `client` und `i18n` wirft unter gesperrtem Speicher nicht mehr
Dedup-Key: bug:web:client.ts:localstorage-unguarded-at-import
HEAD: b1432223
Semantik: `docs/developer/webui.html:83` — „Aktive Sprache wird in <code>localStorage.adminhelper_language</code> persistiert; Browser-Detect dient nur als initialer Fallback.“ Persistenz ist Komfort, keine Startbedingung (vgl. `apps/web/src/lib/stores/theme.ts:32-35`: „persistence is best-effort“).

### T2 — Theme-Initialisierung als Datei statt Inline-Skript (R-0647)  [x]
Komponente: web · Dateien: apps/web/index.html, apps/web/public/theme-init.js, apps/web/src/theme-init.test.ts, apps/web/src/lib/stores/theme.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @e7d3134f 2026-10-22T10:34:56+02:00
Review: approve (.ah-out/review/web-fixes/T2.verdict.json)
Änderung: Der Inhalt von `apps/web/index.html:6-17` zieht nach `apps/web/public/theme-init.js` (neu, SPDX-Header per `reuse annotate`, Logik unverändert: `ah-theme` lesen, nur `light`/`dark` übernehmen, jeder Fehler → dunkler Default; der Kommentar sagt, warum Datei: die CSP des Servers erlaubt nur `script-src 'self'`). An seiner Stelle steht `<script src="/theme-init.js"></script>` — klassisch, ohne `type="module"`, `defer` oder `async`, damit es vor dem ersten Paint läuft; Vite lässt ein Skript aus `public/` unangetastet. Der Kommentar `theme.ts:11-13` nennt `public/theme-init.js` statt „inline script in index.html“. Neue Testdatei `apps/web/src/theme-init.test.ts` (`/// <reference types="node" />` und Pfade wie `src/lib/i18n/i18n.test.ts:5-14`): (a) `index.html` mit `DOMParser` geparst: jedes `<script>` hat ein `src` und keinen Text; das Theme-Skript ist `/theme-init.js`, steht im `<head>`, ohne `type`, `defer`, `async`, und `public/theme-init.js` existiert; (b) `public/theme-init.js` per `new Function(code)()` ausgeführt: gespeichertes `light` → `data-theme="light"`, `dark` → `"dark"`, `x` → kein Attribut, ein `localStorage`-Getter, der `SecurityError` wirft → kein Wurf, kein Attribut (Attribut vor jedem Fall entfernen). Zuerst rot: (a) und (b) auf HEAD.
Verify: bash scripts/dev/verify.sh web --strict -- src/theme-init.test.ts src/lib/stores/theme.test.ts
Doku: docs/developer/webui.html:86 + docs/en/developer/webui.html:86 (statt „winziges Inline-Script im <head>“: das Skript `public/theme-init.js`, im `<head>` als Datei geladen, damit es unter der CSP `script-src 'self'` laufen darf) · CHANGELOG.md (Fixed: helles Design uebersteht einen Reload; das Theme-Skript lief inline und wurde von der CSP des Servers blockiert, mit CSP-Fehler in der Konsole)
Beweis: origin/main@b1432223 · Probe `cd apps/web && npx vite build --outDir <scratch>/dist` (Vite 8.0.16, rc 0): das gebaute `index.html` trägt das Inline-Skript an Zeile 6, das Meta-CSP (`script-src 'self'`) erst danach vor `</head>`; der Server sendet für `text/html` den Header `Content-Security-Policy: … script-src 'self'; …` (`apps/server/app/main.py:441-453`), der fürs ganze Dokument gilt (CSP3 §3.3: Meta gilt nur für Folgendes). Test (a) ist auf HEAD rot (Inline-`<script>` ohne `src`); den Browser-Beweis trägt T3
Orakel: contract — `index.html` hat kein Inline-Skript, das Theme-Skript ist eine Datei unter `'self'`
Dedup-Key: bug:web:index.html:inline-theme-script-blocked-by-csp
HEAD: b1432223
Semantik: `docs/developer/webui.html:86` — „Ein winziges Inline-Script im <code>&lt;head&gt;</code> setzt <code>data-theme</code> bereits <em>vor</em> dem ersten Paint (FOUC-frei), damit Light-User beim Laden nicht kurz Dark sehen.“ (EN `:86`); `apps/web/tests/e2e/theme.spec.ts:34` — „the FOUC script must re-apply the persisted light theme before paint“.

### T3 — E2E: Theme-Journey gegen den Build unter CSP-Header (R-0647)  [x]
Komponente: web · Dateien: apps/web/vite.config.ts, apps/web/playwright.config.ts, apps/web/tests/e2e/theme.spec.ts, docs/developer/webui.html, docs/en/developer/webui.html
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @b0060d31 2026-10-22T10:48:26+02:00
Review: approve (.ah-out/review/web-fixes/T3.verdict.json)
Änderung: `vite.config.ts`: `preview: { headers: { 'Content-Security-Policy': CSP } }` mit Kommentar (Warum: `vite preview` liefert den Build wie der Server mit der CSP als Header aus, der anders als das Meta-Element vor `</head>` das ganze Dokument erfasst, CSP3 §3.3; `script-src` gleicht dem Server, `apps/server/app/main.py:449`); der Kommentar `:16` sagt, dass auch `index.html` kein Inline-Skript trägt (Theme-Init in `public/theme-init.js`). `playwright.config.ts`: außer im Live-Modus ein zweites Projekt `chromium-build` (`testMatch` nur `theme.spec.ts`, `baseURL` `http://localhost:4173`, Geräte wie `chromium`) und `webServer` als Array: der bisherige Dev-Server unverändert plus `npx vite build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort` mit `url` `http://localhost:4173`, `reuseExistingServer: false` (Kommentar: ein stehengebliebener Preview mit altem Build meldete sonst grün), `timeout` 120 000. `theme.spec.ts`: Kommentare `:8-12` und `:34` nennen `public/theme-init.js`; vor `page.goto` sammelt `page.on('console', …)` Meldungen vom Typ `error`, deren Text „Content Security Policy“ enthält; nach dem Reload `expect(violations).toEqual([])`. Zusätzlich zum Verify fährt der builder `cd apps/web && npx playwright test --project=chromium-build` im Bau-Worktree (grün) und dieselbe Spec in einem Probe-Worktree auf origin/main b1432223 mit nur diesem Diff (rot: nach dem Reload `data-theme` nicht `light` und eine Meldung „Refused to execute inline script …“); beide Summary-Zeilen in den Commit-Body. Läuft die App unter dem Header mit weiteren CSP-Verletzungen (nicht verifiziert), ist das ein Fund: `[?]` statt den Test aufzuweichen.
Verify: bash scripts/dev/verify.sh web --strict -- src/theme-init.test.ts
Doku: docs/developer/webui.html:89 + docs/en/developer/webui.html:89 (ein Satz: das Projekt `chromium-build` fährt `theme.spec.ts` gegen `vite build` + `vite preview`, das die CSP als Header schickt wie der Server)
Abhängt von: T2
Beweis: origin/main@b1432223 · Code-Lesung `apps/web/playwright.config.ts:68-75` (E2E nur gegen `npm run dev`, ohne CSP, `apps/web/vite.config.ts:29`) und Probe aus T2 (Meta-CSP hinter dem Inline-Skript, deshalb auch unter `vite preview` ohne Header grün); der rote Lauf entsteht im Probe-Worktree wie in `Änderung:`
Orakel: contract — die Theme-Journey hält gegen den Build unter `script-src 'self'` als Header, ohne CSP-Meldung
Dedup-Key: bug:web:index.html:inline-theme-script-blocked-by-csp
HEAD: b1432223
Semantik: wie T2

### T4 — Hook-Lauf: eigene Frist von 75 s, übersetzter Timeout-Text (R-0648)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/hooks.ts, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/lib/api/client.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @f6fe941e 2026-10-22T10:57:13+02:00
Review: approve (.ah-out/review/web-fixes/T4.verdict.json)
Änderung: `client.ts`: `export interface RequestOptions { timeoutMs?: number }`; `fetchWithTimeout(input, init, timeoutMs = REQUEST_TIMEOUT_MS)` (`:25-34`); `request(method, path, body?, opts?)` gibt `opts?.timeoutMs` an beide Fetches (`:93`, `:99`); nur `http.post` (`:170`) bekommt den optionalen dritten Parameter. Der Timeout-Text (`:30`) wird `tNow('error.timeout')` (Import aus `$lib/i18n`), Status bleibt 0. `hooks.ts`: `run()` (`:40-42`) übergibt `{ timeoutMs: RUN_TIMEOUT_MS }` mit `RUN_TIMEOUT_MS = 75_000` und Kommentar (Warum: der Server führt den Hook synchron aus, bis 30 s Script, `apps/server/app/modules/hooks/script_runner.py:60`, plus begrenzte Joins, `:212-213`; das Gateway schneidet eine stille Antwort nach 60 s, nginx-Default, `apps/gateway/nginx.conf` setzt `proxy_read_timeout` nur für SSE, `:114`; 75 s liegen über beidem). `dictionaries.ts`: `'error.timeout'` in DE („Zeitüberschreitung: Der Server hat nicht rechtzeitig geantwortet.“) und EN („Request timed out: the server did not answer in time.“) neben `'error.generic'` (`:14`, `:302`). `Hooks.svelte` bleibt: der Knopf ist schon bis zum Ende des Aufrufs gesperrt (`:84-98`, `:194`). Tests in `client.test.ts` mit `vi.spyOn(AbortSignal, 'timeout')` (im `afterEach` zurücksetzen): (a) `http.post('/api/x', {}, { timeoutMs: 75_000 })` → `AbortSignal.timeout` mit 75 000, `http.get('/api/x')` → mit 15 000; (b) `run('h/1')` aus `./hooks` (nach `vi.resetModules()` frisch importiert) postet an `/api/hooks/h%2F1/run` und ruft `AbortSignal.timeout` mit 75 000; (c) der bestehende Test `:281-296` prüft zusätzlich: `message` ist `tNow('error.timeout')` aus demselben frisch importierten `$lib/i18n`, nicht `'Request timed out'`. Zuerst rot: (a) (dritter Parameter fehlt, `npm run check`), (b) (15 000), (c) (fester englischer Text).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts src/lib/i18n/i18n.test.ts
Doku: docs/developer/webui.html:79 + docs/en/developer/webui.html:79 (ein Satz: jede Anfrage bricht nach 15 s mit `ApiError(0, …)` und übersetztem Text ab; der manuelle Hook-Lauf `hooks.run` wartet 75 s) · CHANGELOG.md (Fixed: manueller Hook-Lauf zwischen 15 und 30 s endet nicht mehr mit „Request timed out“; das Web wartet 75 s, der Knopf bleibt bis zum Ende gesperrt; Timeout-Meldung uebersetzt)
Beweis: origin/main@b1432223 · Code-Lesung: `apps/web/src/lib/api/client.ts:20`, `:27` (eine Frist von 15 s für jede Anfrage), `apps/web/src/lib/api/hooks.ts:40-42` (keine eigene Frist), `apps/server/app/modules/hooks/script_runner.py:60`, `:192`, `:212-213` (synchron bis 30 s plus Joins), `apps/web/src/pages/Hooks.svelte:95-96` (gibt den Knopf beim Timeout frei). Test (b) ist auf HEAD rot
Orakel: contract — `hooks.run` bekommt 75 s, jede andere Anfrage 15 s
Dedup-Key: bug:web:client.ts:global-timeout-shorter-than-hook-run
HEAD: b1432223
Semantik: `docs/developer/hooks.html:112` — „Sobald der Lauf endet, zeigt ein Dialog das Ergebnis als JSON“; `docs/developer/hooks.html:87` — „<strong>Timeout</strong>: Default 30&nbsp;s.“

### T5 — Daten-Stores: `reset()` mit Schutz gegen späte Antworten (R-0653)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/users.ts, apps/web/src/lib/stores/hooks.ts, apps/web/src/lib/stores/apikeys.ts, apps/web/src/lib/stores/frp.ts, apps/web/src/lib/stores/reset.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @f543618c 2026-10-22T11:10:40+02:00
Review: approve (.ah-out/review/web-fixes/T5.verdict.json)
Änderung: `users`, `hooks`, `apikeys` bekommen `reset(): void` — `refreshGen++` (damit ein laufendes `refresh()` sein Ergebnis verwirft, wie nach einer Mutation, `users.ts:11-14`) und die Liste leer. `frpConfig` (`frp.ts:11-26`) bekommt einen eigenen `refreshGen`, den `refresh()` wie `users.ts:19-23` prüft, und `reset()` mit `refreshGen++` und `null`. Neue Testdatei `apps/web/src/lib/stores/reset.test.ts` (die vier API-Module per `vi.mock` wie `users.test.ts:12-17`): je Store (a) befüllt über `refresh()`, nach `reset()` leer bzw. `null`; (b) ein `refresh()`, dessen `list` erst nach `reset()` erfüllt wird (Deferred), lässt den Store leer bzw. `null`. Zuerst rot: (a), (b) auf HEAD (`reset` fehlt).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/
Doku: keine (intern; die Doku und den CHANGELOG trägt T6)
Beweis: origin/main@b1432223 · Code-Lesung: `apps/web/src/lib/stores/auth.ts:48-51` leert keinen Store; `users.ts`, `hooks.ts`, `apikeys.ts`, `frp.ts` haben keinen Weg zum Leeren. Test (a) ist auf HEAD rot
Orakel: contract — nach `reset()` ist jeder Store leer, auch wenn eine ältere Liste später ankommt
Dedup-Key: bug:web:auth.ts:logout-race-clears-new-session
HEAD: b1432223

### T6 — Abmelden: Stores leeren, neue Anmeldung wartet auf die Abmeldung (R-0653)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/auth.ts, apps/web/src/lib/stores/auth.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @ff58c4db 2026-10-22T11:32:09+02:00
Review: approve (.ah-out/review/web-fixes/T6.verdict.json)
Änderung: In `auth.ts` ein modul-privates `endSession(): Promise<void>`: setzt den Zustand auf `{ user: null, ready: true }`, ruft `reset()` von `users`, `hooks`, `apikeys`, `frpConfig` (T5), startet die Abmeldung als `(async () => { await authApi.logout(); })()` (verträgt auch einen Mock, der `undefined` liefert) und merkt sie in `pendingLogout`, bis sie erfüllt ist. `logout()` (`:48-51`) gibt `endSession()` zurück (Rückgabetyp `Promise<void>`; `Sidebar.svelte:109` bleibt); der 401/403-Zweig in `hydrate` (`:36-38`) und der Auth-Failure-Handler (`:58-61`) gehen ebenfalls über `endSession()`. `login()` (`:43-46`) wartet zuerst auf ein offenes `pendingLogout`. Ein Kommentar nennt das Warum: `authApi.logout()` löscht den Access-Token erst nach der Antwort (`apps/web/src/lib/api/auth.ts:20-24`), und deren `Set-Cookie` löscht das Refresh-Cookie; käme sie nach einer neuen Anmeldung an, endete die neue Sitzung. Tests in `auth.test.ts` (die vier Stores per `vi.mock` mit `reset: vi.fn()`): (a) `authApi.logout` liefert ein Deferred; `auth.logout()`, dann `auth.login('admin', 'pw')`: vor dem Erfüllen ist `authApi.login` nicht aufgerufen, danach einmal, der Nutzer ist gesetzt; (b) dasselbe nach dem Auth-Failure-Handler und (c) nach `hydrate` mit 401 aus `/me`; (d) jeder der drei Wege ruft alle vier `reset()`; (e) `auth.logout()` liefert ein Promise, das erst mit der Abmeldung erfüllt ist. Die bestehenden Tests bleiben. `ConfirmDialog.test.ts` (ruft `auth.logout()` und den Handler, `:113-128`) bleibt unverändert grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/auth.test.ts src/lib/components/ui/ConfirmDialog.test.ts
Doku: docs/developer/webui.html:68 + docs/en/developer/webui.html:68 (Zeile `auth`: Abmelden setzt den Zustand sofort zurück und leert die Daten-Stores; eine neue Anmeldung wartet, bis die Abmeldung beantwortet ist) · CHANGELOG.md (Fixed: eine schnelle Neuanmeldung nach dem Abmelden wird nicht mehr von der spaeten Abmelde-Antwort beendet; Abmelden leert Benutzer-, Hook-, API-Key- und FRP-Daten im Browser)
Abhängt von: T5
Beweis: origin/main@b1432223 · Code-Lesung: `apps/web/src/lib/stores/auth.ts:48-51` (kein `await`), `apps/web/src/lib/api/auth.ts:16-25` (`clearTokens()` im `finally`), `apps/server/app/modules/users/auth_router.py:242-275` (`_clear_refresh_cookie` in der Antwort). Test (a) ist auf HEAD rot (`authApi.login` sofort aufgerufen)
Orakel: contract — eine Anmeldung startet erst nach der Antwort der vorigen Abmeldung
Dedup-Key: bug:web:auth.ts:logout-race-clears-new-session
HEAD: b1432223
Semantik: keine Stelle in docs/ zur Reihenfolge — gesucht: `docs/developer/webui.html:68`, `:79` (Logout, Refresh, Auth-Failure-Handler); Maßstab ist die Absicht in `apps/web/src/lib/api/client.ts:7-11` (Access-Token nur im Speicher, Refresh-Token im Cookie) und `apps/web/src/lib/components/ui/ConfirmDialog.svelte:68-72` („A question belongs to the session it was asked in“).

### T7 — Selbst-Bearbeitung: Auth-Store nachführen, eigenes Passwort meldet ab (R-0652)  [x]
Komponente: web · Dateien: apps/web/src/modals/UserModal.svelte, apps/web/src/lib/stores/auth.ts, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/modals/UserModal.test.ts, docs/admin/benutzer.html, docs/en/admin/users.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @3ba2c881 2026-10-22T11:42:52+02:00
Review: approve (.ah-out/review/web-fixes/T7.verdict.json)
Änderung: `auth.ts`: `applySelfUpdate(updated: User): void` — ist `updated.id` die des angemeldeten Nutzers, übernimmt der Store `id`, `username`, `is_admin` aus `updated`, sonst nichts. `UserModal.svelte` (`onSubmit`, Zweig `editing`, `:71-78`): behält das Ergebnis von `users.update`; ist `editing.id` die des angemeldeten Nutzers (`currentUser`) und ist ein Passwort gesetzt: Modal schließen, `await auth.logout()`, dann `showToast($t('toast.user.ownPasswordChanged'), 'info', 8000)` statt „Benutzer gespeichert“; ohne Passwort: `auth.applySelfUpdate(updated)`, dann wie bisher. Fremde Nutzer: unverändert. `dictionaries.ts`: `'toast.user.ownPasswordChanged'` DE („Eigenes Passwort geändert – bitte mit dem neuen Passwort anmelden.“) und EN („Your password was changed – sign in with the new password.“) neben `toast.user.saved` (`:91`, `:379`). Neue Testdatei `apps/web/src/modals/UserModal.test.ts` (Muster `EnrollTokenModal.test.ts`; Mocks: `$lib/api/users` `update`, `$lib/api/servers` `list` → `[]`, `$lib/api/client` und `$lib/api/auth` wie `ConfirmDialog.test.ts:18-26`, `logout` async; vorher `auth.hydrate()` als Admin `id: 1`): (a) eigener Nutzer mit Passwort → `authApi.logout` einmal, `get(auth).user` ist `null`, ein Toast `info` mit dem Text des neuen Schlüssels; (b) eigener Nutzer, Haken „Admin“ entfernt, ohne Passwort → `get(isAdmin)` ist `false`, `authApi.logout` nicht aufgerufen; (c) fremder Nutzer (`id: 2`) mit Passwort → keine Abmeldung, `get(auth).user` unverändert. Zuerst rot: (a) und (b) auf HEAD.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/UserModal.test.ts src/lib/stores/auth.test.ts src/lib/i18n/i18n.test.ts
Doku: docs/admin/benutzer.html:58 + docs/en/admin/users.html:52 (ein Satz nach dem Zurücksetzen fremder Passwörter: ändert ein Admin im Web-Panel sein eigenes Passwort, beendet der Server alle Sitzungen des Kontos, das Panel meldet sofort ab; stuft er sich selbst herab, verschwinden die Admin-Seiten sofort) · CHANGELOG.md (Fixed: bearbeitet ein Admin im Web-Panel sich selbst, zeigt das Panel sofort die neuen Rechte; nach eigenem Passwortwechsel meldet es mit Hinweis ab statt bei der naechsten Aktion mit „Session expired“)
Abhängt von: T6
Beweis: origin/main@b1432223 · Code-Lesung: `apps/web/src/modals/UserModal.svelte:66-99` (kein Zugriff auf den Auth-Store), `apps/server/app/modules/users/router.py:108-112` (Passwort setzt `tokens_valid_after`), `apps/server/app/core/auth.py:103-118` (Token vor dem Wasserzeichen ungültig, auch das Refresh-Token), `apps/web/src/lib/stores/auth.ts:56` (`isAdmin` aus dem gespeicherten Nutzer). Test (b) ist auf HEAD rot (`isAdmin` bleibt `true`)
Orakel: contract — nach Selbst-Bearbeitung entspricht der Auth-Store der Antwort des Servers
Dedup-Key: bug:web:UserModal.svelte:self-edit-stale-auth
HEAD: b1432223
Semantik: `apps/server/app/modules/users/router.py:110-111` — „Revoke all existing JWTs for this user (password reset invalidates sessions)“; `docs/admin/benutzer.html:58` — „Admins können jederzeit fremde Passwörter zurücksetzen.“ (zum eigenen Passwort im Web-Panel keine Stelle in docs/).

### T8 — confirmDialog: ohne angemeldeten Nutzer sofort `false` (R-0476)  [x]
Komponente: web · Dateien: apps/web/src/lib/components/ui/ConfirmDialog.svelte, apps/web/src/lib/components/ui/ConfirmDialog.test.ts, apps/web/src/modals/FrpConfigModal.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @34a53d07 2026-10-22T11:58:59+02:00
Review: approve (.ah-out/review/web-fixes/T8.verdict.json)
Änderung: `confirmDialog()` (`ConfirmDialog.svelte:19-35`) liefert `Promise.resolve(false)` und öffnet nichts, wenn `get(currentUser)` `null` ist; der Import von `currentUser` zieht dafür vom Instanz-Teil (`:43`) in den Modul-Teil (`:7-8`), der Effekt `:73-78` bleibt. Kommentar: dieselbe Regel wie `:68-72` für eine Frage, die erst nach dem Ende der Sitzung gestellt wird. `ConfirmDialog.test.ts`: im `describe` (`:35`) ein `beforeEach(async () => { await auth.hydrate(); })`, damit die Tests `:36-111` mit Sitzung fragen (keine Assertion entfällt); neuer Test: Sitzung beenden (Auth-Failure-Handler wie `:115`), dann `confirmDialog('x')` → erfüllt mit `false`, kein `.btn.danger` im gerenderten Dialog. Zuerst rot: der neue Test auf HEAD (die Frage öffnet, das Promise bleibt offen).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/components/ui/ConfirmDialog.test.ts src/modals/FrpConfigModal.test.ts
Doku: keine (intern; heute ruft niemand `confirmDialog` ohne Sitzung)
Beweis: origin/main@b1432223 · Code-Lesung `apps/web/src/lib/components/ui/ConfirmDialog.svelte:19-35` (keine Prüfung der Sitzung) und `:73-78` (bricht nur offene Fragen ab); Aufrufer `apps/web/src/pages/Users.svelte:53`, `ApiKeys.svelte:52`, `Hooks.svelte:74`, `:102`, `apps/web/src/modals/FrpConfigModal.svelte:101` (alle hinter dem Login). Der neue Test ist auf HEAD rot
Orakel: contract — ohne angemeldeten Nutzer öffnet keine Frage
Dedup-Key: ref:web:confirm:null-user
HEAD: b1432223

### T9 — Merge-Folge: `hooks.test.ts` erwartet die 75-s-Frist des Hook-Laufs (R-0648)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/hooks.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @63dc1c2e 2026-10-22T12:14:46+02:00
Review: approve (.ah-out/review/web-fixes/T9.verdict.json)
Änderung: Fund des Branch-Reviews (blocker). Der Test `apps/web/src/lib/api/hooks.test.ts:21` kam mit #254 über den Merge 3dfa4ddf auf den Branch und erwartet `http.post` mit zwei Argumenten; seit T4 übergibt `run()` dazu `{ timeoutMs: 75_000 }`. Die Assertion wird `expect(http.post).toHaveBeenCalledWith('/api/hooks/a%2Fb/run', {}, { timeoutMs: 75_000 })` — gewollte Verhaltensänderung aus T4, keine Assertion entfällt, sonst nichts an der Datei.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/hooks.test.ts src/lib/api/client.test.ts
Doku: keine (Test-Anpassung; Doku und CHANGELOG trägt T4)
Beweis: feature/web-fixes@3dfa4ddf · `bash scripts/dev/verify.sh web --strict` → `Tests 1 failed | 275 passed (276)`, FAIL `src/lib/api/hooks.test.ts > hooks api > posts a manual run to the encoded hook id and returns the response unchanged` (Received mit drittem Argument `{ "timeoutMs": 75000 }`)
Orakel: contract — `hooks.run` postet mit der Frist von 75 s
HEAD: 3dfa4ddf

### T10 — UserModal: Fehlerpfad beim eigenen Passwortwechsel und Reihenfolge PUT vor Abmeldung (R-0652)  [x]
Komponente: web · Dateien: apps/web/src/modals/UserModal.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @d71ca116 2026-10-22T12:24:00+02:00
Review: approve (.ah-out/review/web-fixes/T10.verdict.json)
Änderung: Fund des testers (wichtig), nur Tests. In `UserModal.test.ts` Test (a) zusätzlich: `users.update` läuft vor `authApi.logout` (`mock.invocationCallOrder`). Neuer Test (d): eigener Nutzer mit Passwort, `update` verwirft mit `new ApiError(422, …)` (wie der Server bei einem Passwort unter 8 Zeichen, `apps/server/app/modules/users/schemas.py:68`) → `authApi.logout` nicht aufgerufen, `get(auth).user` weiter gesetzt, `onClose` nicht aufgerufen, kein Info-Toast mit dem Text von `toast.user.ownPasswordChanged`, ein Fehler-Toast. Zeigt der Code (`UserModal.svelte:78-86`, `:105-106`) dabei ein anderes Verhalten, `[?]` statt den Test anzupassen. Mutationsprobe nur in einer Kopie unter dem eigenen Scratch-Verzeichnis, nicht im Bau-Worktree: `auth.logout()` vor `users.update` → (a) rot; eine Abmeldung auch im `catch` → (d) rot; beide Ergebnisse in den Commit-Body.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/UserModal.test.ts
Doku: keine (nur Tests)
Beweis: feature/web-fixes@3dfa4ddf · tester-Urteil `.ah-out/review/web-fixes/tester.verdict.json`, Fund 1 · Code-Lesung `apps/web/src/modals/UserModal.svelte:78-86` (Fehlerpfad ohne Test, Reihenfolge nicht festgelegt)
Orakel: contract — scheitert der PUT des eigenen Passworts, bleibt die Sitzung bestehen und es erscheint kein Hinweis „Passwort geändert“
HEAD: 3dfa4ddf
