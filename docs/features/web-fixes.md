<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: Theme-Skript unter der CSP, Frist des Hook-Laufs, Abmelden ohne Wettlauf, Selbst-Bearbeitung, gesperrter Seitenspeicher, confirmDialog ohne Sitzung

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/web-fixes.md`. Roadmap R-0654 (T1), R-0647 (T2, T3), R-0648 (T4), R-0653 (T5, T6), R-0652 (T7), R-0476 (T8).
Alles liegt in `apps/web`; Server, Gateway und ihre CSP-Header bleiben unverändert.

## Problem / Motivation

1. **Gesperrter Seitenspeicher lässt die App leer (R-0654).** `apps/web/src/lib/api/client.ts:13-14` ruft beim
   Modul-Import `localStorage.removeItem(…)` ohne `try`/`catch`, `apps/web/src/lib/i18n/index.ts:12-13` und `:23-24`
   prüfen vorher `typeof localStorage !== 'undefined'`. Sperrt der Browser den Seitenspeicher (Cookies/Website-Daten
   blockiert), wirft schon der Getter `window.localStorage` einen `SecurityError` (MDN, unten), und `typeof` auf den
   Bezeichner ruft diesen Getter. Der Import von `main.ts` scheitert, die Seite bleibt leer, auch ohne Login-Maske.
   Beleg (Probe, Node 22.23.1): mit einem Getter, der `DOMException('…', 'SecurityError')` wirft, ergibt
   `typeof localStorage` dreimal `throws SecurityError`, ebenso `localStorage.removeItem('x')`.
   `apps/web/src/lib/stores/theme.ts:36-40` und das Theme-Skript in `apps/web/index.html:9-16` fangen den Fall schon.

2. **Theme-Skript inline, die CSP verbietet Inline-Skripte (R-0647).** `apps/web/index.html:6-17` setzt
   `data-theme` vor dem ersten Paint per Inline-`<script>`. Der Server schickt für jede HTML-Antwort der SPA den Header
   `Content-Security-Policy: … script-src 'self'; …` (`apps/server/app/main.py:432-455`, `script-src` `:449`); ein
   Header gilt für das ganze Dokument, das Inline-Skript wird blockiert. Ohne Attribut liefert `initial()` in
   `apps/web/src/lib/stores/theme.ts:14-20` `'dark'`, der `subscribe` (`:24-41`) schreibt `'dark'` zurück nach
   `localStorage`: das helle Design übersteht keinen Reload, die Konsole zeigt einen CSP-Fehler. Beleg (Probe
   `npx vite build --outDir <scratch>`, Vite 8.0.16): das gebaute `index.html` trägt das Inline-Skript, und das
   Meta-CSP des Builds (`apps/web/vite.config.ts:14-35`) steht erst vor `</head>`, **hinter** dem Skript. Ein
   Meta-Element gilt nur für Inhalt, der ihm folgt (CSP3 §3.3, unten); deshalb fällt der Fehler weder unter
   `vite preview` noch unter `npm run dev` (ohne CSP, `vite.config.ts:29`) auf, und `apps/web/tests/e2e/theme.spec.ts`
   ist grün, weil Playwright gegen den Dev-Server läuft (`apps/web/playwright.config.ts:68-75`). Der Kommentar
   `vite.config.ts:16` („the Vite build emits no inline scripts (verified)“) stimmt für das Bundle, nicht für
   `index.html`. Die Zeile R-0735 (`neu`) beschreibt denselben Befund vom Kommentar aus.

3. **15-s-Frist auch für den manuellen Hook-Lauf (R-0648).** Jede Anfrage bricht nach `REQUEST_TIMEOUT_MS = 15_000`
   ab (`client.ts:20`, `:25-34`), auch `POST /api/hooks/{id}/run` (`apps/web/src/lib/api/hooks.ts:40-42`). Der Server
   führt den Hook synchron aus: bis 30 s Script (`apps/server/app/modules/hooks/script_runner.py:60`, `:192`), danach
   begrenzte Joins der Ausgabe-Threads (`:212-213`, `:224-225`), wenn ein Enkelprozess die Ausgabe offen hält. Läuft
   ein Hook 15–30 s, zeigt die UI „Request timed out“ (fest englisch, `client.ts:30`), das Ergebnis ist verloren, und
   `running.delete` (`apps/web/src/pages/Hooks.svelte:95-96`) gibt den Knopf (`:194`) frei, während der Hook auf dem
   Server weiterläuft; ein zweiter Klick startet ihn parallel (der Schutz aus `Hooks.svelte:32-33` greift nicht).

4. **Abmelden ohne Warten (R-0653).** `auth.logout()` (`apps/web/src/lib/stores/auth.ts:48-51`) ruft
   `authApi.logout()` ohne `await` und setzt den Zustand sofort auf abgemeldet. `authApi.logout()` löscht den
   Access-Token erst nach der Antwort (`apps/web/src/lib/api/auth.ts:16-25`, `clearTokens()` im `finally`), die
   Antwort löscht per `Set-Cookie` das Refresh-Cookie (`apps/server/app/modules/users/auth_router.py:242-275`).
   Meldet sich der Nutzer schneller wieder an, als die Abmeldung antwortet, löscht die späte Antwort den neuen
   Access-Token und das neue Refresh-Cookie: die neue Sitzung endet bei der nächsten Anfrage. Dasselbe gilt für die
   zwei anderen Wege zur Abmeldung (`auth.ts:36-38` in `hydrate`, `:58-61` im Auth-Failure-Handler). Außerdem leert
   die Abmeldung die Daten-Stores nicht (`apps/web/src/lib/stores/users.ts`, `hooks.ts`, `apikeys.ts`, `frp.ts`): die
   Listen der alten Sitzung bleiben im Speicher, bis die nächste Seite sie neu lädt.

5. **Selbst-Bearbeitung führt den Auth-Store nicht nach (R-0652).** `UserModal.svelte` speichert über
   `users.update` (`apps/web/src/modals/UserModal.svelte:66-99`) und fasst den Auth-Store nicht an. Ändert ein Admin
   sein **eigenes Passwort**, setzt der Server das Token-Wasserzeichen (`apps/server/app/modules/users/router.py:108-112`),
   das Access- und Refresh-Token gleichermaßen ungültig macht (`apps/server/app/core/auth.py:103-118`); die nächste
   Anfrage endet über den 401-Pfad in „Session expired“ (`client.ts:95-103`). Stuft er sich **selbst herab**, bleibt
   `isAdmin` wahr (`auth.ts:56`): Navigation (`apps/web/src/lib/components/layout/Sidebar.svelte:56`) und Router
   (`apps/web/src/lib/components/layout/Router.svelte:20`) zeigen weiter die Admin-Seiten, jede Aktion endet in 403.

6. **`confirmDialog` ohne Sitzung (R-0476).** `confirmDialog()` (`apps/web/src/lib/components/ui/ConfirmDialog.svelte:19-35`)
   öffnet eine Frage auch, wenn niemand angemeldet ist. Die Komponente bricht offene Fragen ab, sobald die Sitzung
   endet (`:68-78`), eine **nach** dem Ende gestellte Frage aber nicht. Heute ruft niemand `confirmDialog` ohne
   Sitzung (alle Aufrufer sind Admin-Seiten bzw. `FrpConfigModal.svelte:101`); Härtung.

## Ziel & Nicht-Ziele

Ziel:
- Ein gesperrter Seitenspeicher lässt die App starten (Login-Maske, Sprache aus dem Browser, Design dunkel); Lesen,
  Schreiben und Löschen im Seitenspeicher gehen durch einen Helfer, der nie wirft (T1).
- `index.html` trägt kein Inline-Skript; die Theme-Initialisierung ist `public/theme-init.js`, geladen als
  klassisches, blockierendes `<script src="/theme-init.js">` im `<head>`, erlaubt durch `script-src 'self'` (T2).
  Keine CSP wird gelockert, kein Hash, kein Header ändert sich.
- Ein Playwright-Projekt fährt `theme.spec.ts` gegen den Produktions-Build unter `vite preview`, der die CSP als
  Header schickt wie der Server; es ist auf `origin/main` rot und meldet jede CSP-Verletzung (T3).
- Der manuelle Hook-Lauf wartet 75 s statt 15 s; jede andere Anfrage behält 15 s; der Text eines Timeouts ist
  übersetzt (T4).
- Abmelden setzt den Zustand sofort zurück, leert `users`, `hooks`, `apikeys` und `frpConfig` und lässt eine neue
  Anmeldung warten, bis die Abmeldung beantwortet ist; dasselbe für die Abmeldung aus `hydrate` und aus dem
  Auth-Failure-Handler (T5, T6).
- Ändert ein Admin sein eigenes Passwort, meldet das Panel ihn sofort ab und sagt es ihm (Toast); ändert er sonst
  etwas an sich selbst (Admin-Recht, Server), übernimmt der Auth-Store die Antwort des Servers (T7).
- `confirmDialog()` ohne angemeldeten Nutzer liefert sofort `false` und öffnet nichts (T8).

Nicht-Ziele (YAGNI):
- Keine Änderung an Server, Gateway, CSP-Headern (`apps/server/app/main.py:443-453`) oder am Meta-CSP-Inhalt
  (`vite.config.ts:14-24`). Kein `'unsafe-inline'`, kein Hash.
- Die Position des Meta-CSP (vor `</head>`, `vite.config.ts:26-35`) bleibt; nach T2 steht davor nur Inhalt von
  `'self'`. Eine Verschiebung an den Anfang des `<head>` wäre eine eigene Härtung.
- Desktop (`apps/desktop/ui/index.html` trägt ein gleiches Inline-Skript unter der Tauri-CSP): nicht Teil dieses
  Vorhabens.
- Keine Server-API-Änderung für den Hook-Lauf (kein asynchroner Lauf, kein Polling); keine eigene Fehlermeldung für
  `HTTP 504` des Gateways.
- Kein nahtloses Weiterarbeiten nach eigenem Passwortwechsel (Wieder-Anmeldung mit dem neuen Passwort, Trade-off 6).
- Kein gemeinsamer Store-Baustein für das `refreshGen`-Muster (das plant R-0724); T5 fügt je Store nur `reset()` an.
- `theme.ts` behält seinen eigenen `try`/`catch` (`:36-40`); keine Übersetzung der übrigen festen Client-Texte
  („Session expired“, „Invalid response body“).
- Die Dateien des offenen PR #254 (`apps/web/src/lib/api/types.ts`, `apps/web/src/lib/api/hooks.test.ts`) fasst
  dieses Vorhaben nicht an.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | web | `apps/web/src/lib/utils/storage.ts` (neu), `apps/web/src/lib/utils/storage.test.ts` (neu), `apps/web/src/lib/api/client.ts`, `apps/web/src/lib/i18n/index.ts`, `CHANGELOG.md` |
| T2 | web | `apps/web/index.html`, `apps/web/public/theme-init.js` (neu), `apps/web/src/theme-init.test.ts` (neu), `apps/web/src/lib/stores/theme.ts`, `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` |
| T3 | web | `apps/web/vite.config.ts`, `apps/web/playwright.config.ts`, `apps/web/tests/e2e/theme.spec.ts`, `docs/developer/webui.html`, `docs/en/developer/webui.html` |
| T4 | web | `apps/web/src/lib/api/client.ts`, `apps/web/src/lib/api/hooks.ts`, `apps/web/src/lib/i18n/dictionaries.ts`, `apps/web/src/lib/api/client.test.ts`, `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` |
| T5 | web | `apps/web/src/lib/stores/users.ts`, `apps/web/src/lib/stores/hooks.ts`, `apps/web/src/lib/stores/apikeys.ts`, `apps/web/src/lib/stores/frp.ts`, `apps/web/src/lib/stores/reset.test.ts` (neu) |
| T6 | web | `apps/web/src/lib/stores/auth.ts`, `apps/web/src/lib/stores/auth.test.ts`, `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` |
| T7 | web | `apps/web/src/modals/UserModal.svelte`, `apps/web/src/lib/stores/auth.ts`, `apps/web/src/lib/i18n/dictionaries.ts`, `apps/web/src/modals/UserModal.test.ts` (neu), `docs/admin/benutzer.html`, `docs/en/admin/users.html`, `CHANGELOG.md` |
| T8 | web | `apps/web/src/lib/components/ui/ConfirmDialog.svelte`, `apps/web/src/lib/components/ui/ConfirmDialog.test.ts` |

Keine Datei steht auf `scripts/dev/review-risk.txt`. `docs/developer/webui.html` (DE+EN) ändern T2, T3, T4 und T6 an
verschiedenen Absätzen; die Tasks laufen nacheinander.

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Schema, kein Header. Der Server liefert `public/theme-init.js` nach dem Build aus
`frontend/` wie heute `logo.svg` über `spa_fallback` (`apps/server/app/main.py:501-517`, `FileResponse` errät
`text/javascript`; das Image läuft auf Python 3.12, `Dockerfile:14`); der Build kopiert `public/` nach `dist/`
(`Dockerfile:10-11`, `:40`). `http.post` bekommt einen optionalen dritten Parameter (`{ timeoutMs }`), alle bisherigen
Aufrufe bleiben gültig. `vite preview` schickt künftig die CSP als Header (`preview.headers`); `vite preview` dient
nur Tests, Produktion liefert der Server aus. Kein Vertrags-Drift zu Server, Desktop oder Agent.

## Externe Integrationen

- W3C CSP Level 3, §3.3 „The `<meta>` element“ (w3.org/TR/CSP3, gelesen 2026-10-22): „Authors are strongly
  encouraged to place meta elements as early in the document as possible, because policies in meta elements are not
  applied to content which precedes them.“
- MDN `Window.localStorage`, Exceptions (gelesen 2026-10-22): `SecurityError` wird geworfen, wenn „the request
  violates a policy decision. For example, the user has configured the browsers to prevent the page from persisting
  data.“
- MDN `AbortSignal.timeout(time)`: `time` in Millisekunden; „The signal aborts with a `TimeoutError` `DOMException`
  on timeout.“
- Vite, Preview Options (vite.dev/config/preview-options, gelesen 2026-10-22): `preview.headers` „Specify server
  response headers.“; `preview.port` Default 4173; `preview.strictPort` beendet statt auszuweichen;
  `preview.proxy` Default `server.proxy`.
- Playwright, Web server (playwright.dev/docs/test-webserver, gelesen 2026-10-22): „Multiple web servers (or
  background processes) can be launched simultaneously by providing an array of `webServer` configurations.“;
  `reuseExistingServer: false` wirft, wenn der Port belegt ist. Ob Playwright alle Server auch bei Auswahl eines
  einzelnen Projekts startet, sagt die Seite nicht (nicht verifiziert; T3 nimmt an, dass ja, und rechnet die
  Build-Zeit von etwa 3 s dazu).
- nginx: Ohne eigene Angabe gilt `proxy_read_timeout` 60 s; `apps/gateway/nginx.conf` setzt ihn nur für den
  SSE-Stream (`:114`), nicht für `location /` (`:121`, `:167`). Nur das Gateway veröffentlicht einen Port
  (`docker-compose.yml:186-187`).

## Trade-offs & Alternativen

1. **Theme-Initialisierung (T2).** (a) Datei `public/theme-init.js`, klassisches `<script src>` im `<head>` —
   **Empfehlung**: erlaubt durch `'self'` in beiden CSPs, keine CSP-Änderung, blockiert den Parser wie das Inline-Skript
   (kein `defer`/`async`/`type="module"`), Vite lässt ein Skript aus `public/` unangetastet (es schreibt nur den Pfad
   nach `base` um). Kosten: eine Anfrage mehr beim Laden. (b) `sha256`-Hash im Meta-CSP und im Server-Header —
   zwei Stellen, die bei jeder Änderung des Skripts mitziehen müssen, Server-Datei im Diff. (c) Skript weglassen —
   FOUC zurück.
2. **Beweis gegen den Build (T3).** (a) `vite preview` mit `preview.headers` (CSP aus der Konstante `CSP` in
   `vite.config.ts`) und ein Playwright-Projekt `chromium-build` — **Empfehlung**: läuft in der PR-CI im Job
   `frontend-e2e` (`npx playwright test` fährt alle Projekte), der Header wirkt wie der des Servers aufs ganze
   Dokument, `script-src` ist in beiden `'self'`. (b) Header per `page.route` im Test einspritzen — zweite Kopie der
   CSP im Test. (c) Prüfung im Projekt `live` gegen den echten Stack — nur im Sammellauf, nicht vor dem Merge.
3. **Frist des Hook-Laufs (T4).** 75 s, wie die Zeile vorschlägt: über 30 s Script plus einem Join-Durchgang
   (zusammen bis etwa 60 s) und über dem 60-s-Schnitt des Gateways; ein Lauf darüber endet in Produktion am Gateway
   mit 504, bevor der Client aufgibt. Die Frist gilt nur für `hooks.run` (dritter Parameter von `http.post`), damit
   ein hängender Upstream sonst weiter nach 15 s auffällt (`client.ts:22-24`). Alternative: Frist über der absoluten
   Grenze des Servers (bis etwa 150 s bei einem Enkel, der `killpg` entkommt) — nur über das Gateway erreichbar,
   das ohnehin bei 60 s schneidet.
4. **Übersetzter Timeout-Text (T4).** Im Client (`tNow('error.timeout')`) statt in `showError`: auch die Login-Maske
   zeigt `err.message` direkt (`apps/web/src/pages/Login.svelte:22-29`). `client.ts` importiert dafür `$lib/i18n`
   (das nur `./dictionaries` importiert, kein Zyklus).
5. **Abmelden (T6).** (a) Zustand sofort zurücksetzen, die laufende Abmeldung merken, `login()` wartet auf sie —
   **Empfehlung**: Abmelden bleibt sofort sichtbar, die Antwort samt `Set-Cookie` ist vor der neuen Anmeldung da;
   höchstens die 15-s-Frist lang. (b) `logout()` erst nach der Antwort abmelden — bei hängendem Server 15 s ohne
   Rückmeldung. (c) Generation im Client, die eine späte Antwort ignoriert — schützt den Access-Token, nicht das
   Cookie, dessen Löschung der Browser ausführt. Stores leeren: `auth.ts` ruft `reset()` der vier Stores (explizit);
   Alternative wäre, dass jeder Store `currentUser` abonniert — koppelt jeden Store an `auth.ts` und seine Tests.
6. **Eigener Passwortwechsel (T7).** (a) Sofort abmelden mit Hinweis — **Empfehlung**, nennt die Zeile; der Server
   beendet mit dem Wasserzeichen ohnehin alle Sitzungen des Kontos. (b) Mit dem eben eingegebenen Passwort neu
   anmelden — nahtlos, aber eine zweite Anmeldung im Hintergrund, die die Zeile nicht vorsieht. (c) `auth.hydrate()` —
   scheitert am ungültigen Refresh-Token und meldet ohne Hinweis ab. Übrige Selbst-Bearbeitung: Antwort des `PUT`
   (`UserResponse` trägt `id`, `username`, `is_admin`) in den Auth-Store statt eines weiteren `/me`.
7. **`confirmDialog` ohne Sitzung (T8).** Prüfung im Modul-Teil von `ConfirmDialog.svelte` vor dem Öffnen; die
   bestehenden Tests, die heute ohne Sitzung fragen (`ConfirmDialog.test.ts:36-111`), melden vorher an
   (`auth.hydrate()` mit den vorhandenen Mocks), keine Assertion entfällt.

## Risiken & Rollback

- T2: Ein Browser, der `/theme-init.js` nicht laden kann, startet dunkel (wie heute in Produktion). Die Datei ist
  öffentlich und ohne Hash im Namen; ein Cache kann nach einem Update kurz eine alte Fassung liefern — der Inhalt
  ändert sich selten und hat keinen Zustand.
- T3: Das Projekt `chromium-build` baut bei jedem Playwright-Lauf (auch `--project chromium`) einmal mit
  `vite build` nach `dist/` (gitignored, auch in `.dockerignore`), etwa 3 s. `reuseExistingServer: false` verhindert,
  dass ein stehengebliebener `vite preview` mit altem Build grün meldet.
- T4: Ein Hook über 60 s endet in Produktion weiter am Gateway (504, Text `HTTP 504`); der Knopf wird dann frei,
  während der Server-Thread den Lauf noch abschließt. Die Zahl gleichzeitiger Hooks begrenzt der Server
  (`script_runner.py:127-133`).
- T6: Eine Anmeldung wartet auf eine hängende Abmeldung höchstens die 15-s-Frist.
- T7: Ein Admin, der sein eigenes Passwort ändert, muss sich sofort neu anmelden (bisher: bei der nächsten Aktion
  mit „Session expired“).
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T2 (DE+EN): `docs/developer/webui.html:86` nennt ein Inline-Skript → `public/theme-init.js`, als Datei unter
`script-src 'self'` geladen; CHANGELOG (Fixed). T3 (DE+EN): `webui.html:89` nennt das Projekt `chromium-build`.
T4 (DE+EN): `webui.html:79` nennt die Fristen (15 s, Hook-Lauf 75 s); CHANGELOG (Fixed). T6 (DE+EN): `webui.html:68`
(Zeile `auth`) nennt Abmelden und das Leeren der Stores; CHANGELOG (Fixed). T7 (DE+EN): `docs/admin/benutzer.html:58`
/ `docs/en/admin/users.html:52`, eigener Passwortwechsel im Web-Panel meldet ab; CHANGELOG (Fixed). T1: CHANGELOG
(Fixed). T5, T8: keine (intern).

## Offene Fragen

Keine, die eine Task sperrt. Zur Kenntnis:
1. **Eigener Passwortwechsel (T7):** geplant ist „sofort abmelden mit Hinweis“ (Variante der Zeile). Wer nahtlos
   weiterarbeiten will (Trade-off 6b), ändert nur T7.
2. **R-0735** (`neu`) beschreibt denselben Befund wie R-0647; T2 und T3 erledigen ihn mit (T3 passt den Kommentar
   `vite.config.ts:16` an).
