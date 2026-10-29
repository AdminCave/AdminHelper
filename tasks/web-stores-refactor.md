<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: Store-Fabrik und Stale-Guards, Formular-Payloads, schlanke Serverliste, Kopier-Helfer, toter Code, Audit-Detail — Task-Ledger
Status: erledigt · Branch: feature/web-stores-refactor · Review: pro Task
Spec: docs/features/web-stores-refactor.md (Roadmap R-0722, R-0723, R-0724, R-0777, R-0779, R-0757)
Heavy: linux-full — T10 fügt die Server-Route `GET /api/servers/summary` hinzu (apps/server-API, CLAUDE.md §5), und `web-live` (`scripts/tests/web_live.sh`, `apps/web/tests/live/smoke.live.spec.ts:60-66`) öffnet den Benutzerdialog gegen den echten Stack; kein `scenario` (kein FRP-, PKI-, Install- oder Cross-Host-Pfad), kein `windows` (kein Desktop- oder Agent-Code). Entscheidet Kevin bei Frage 1 gegen T10 (Variante a oder d), setzt die Session `Heavy: none`: alles Übrige ist Web-Code, die Web-E2E mockt die API
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Ein Store-Baustein `listStore.ts` trägt den Stale-Guard von `users`, `hooks`, `apikeys`; Antworten aus
einer beendeten Sitzung schreiben in keinen Store, auch nicht über `frpConfig.save()` (R-0724, R-0777). (2) Ein 401
einer Anfrage aus einer früheren Sitzung beendet die laufende nicht (R-0779). (3) Die Payloads von Hook- und
Benutzerdialog entstehen in getesteten reinen Funktionen (R-0722). (4) Der Benutzerdialog lädt nur `id`, `name`,
`hostname` (R-0723, Frage 1). (5) Ein Kopier-Helfer mit einem übersetzten Fehlertext (R-0724, Frage 2), toter Code
weg (R-0724). (6) Die Audit-Ansicht zeigt `detail` (R-0757). Zeilenangaben: origin/main@b25c65a6; der builder
greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 → T2 → T3; T4 und T5 frei; T6 → T7; T8 → T9 → T11 (T11 auch nach T10); T13 → T14 (T14 auch nach
  T12); T15 und T16 frei; T17 nach T5 (gleiche Dateien); T18 nach dem Merge von PR #268 oder mit origin/main im
  Branch (audit-coverage ändert die Nachbarzeile `docs/admin/betrieb.html:132` und `docs/en/admin/operations.html`).
- `[?]`: T10, T11 (Spec, Frage 1) und T12, T14 (Frage 2). Die übrigen 14 Tasks hängen an keiner Frage.
- T10 berührt `apps/server/app/modules/servers/router.py` und `apps/server/app/modules/servers/schemas.py`
  (`scripts/dev/review-risk.txt`): zusätzlich `security`.
- Pin-Tasks (T1, T6, T8, T13) ändern keinen Produktionscode und sind auf HEAD grün; der Umbau danach ändert keine
  ihrer Assertions. Mutations-Stichproben und Revert-Proben laufen in einem eigenen Probe-Worktree, nie im
  Bau-Worktree (CLAUDE.md §5); vitest lädt mit verlinkten `node_modules` keinen Test, der Probe-Worktree braucht
  eine echte Kopie (`cp -al` auf demselben Dateisystem).
- Neue Code-Strings (Kommentare, Fehlermeldungen) englisch; neue i18n-Schlüssel DE und EN. Der Wächter
  `apps/web/src/lib/i18n/i18n.test.ts` prüft Parität und „no unused translation keys“ (er liest auch Testdateien):
  ein Schlüssel kommt mit seinem ersten echten Nutzer, ein Schlüssel ohne Nutzer geht.
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737, keine echten Token-Formate.
- Andere Vorhaben, die dieselben Dateien ändern: fehlervertrag (`apps/web/src/lib/api/client.ts`, `client.test.ts`,
  `types.ts`, `docs/{,en/}developer/webui.html`, `docs/{,en/}developer/api-reference.html`); auth-sessions
  (`client.ts`, `types.ts`, `apps/web/tests/e2e/mocks.ts`, `apps/server/tests/openapi.snapshot.json`,
  `apps/web/src/lib/i18n/dictionaries.ts`, `webui.html`, `api-reference.html`); audit-coverage, PR #268
  (`dictionaries.ts`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `api-reference.html`); docs-drift
  (`webui.html`, `betrieb.html`); server-hardening, server-fixes, agent-hardening (`api-reference.html`);
  ca-issuer-lifetime, ca-rotation, compose-hardening, install-restore, ops-scripts-hardening, smtp-hardening
  (`betrieb.html`, `operations.html`); alle `CHANGELOG.md`. Vor jedem Push origin/main hineinmergen.

### T1 — Stores: Stale-Guard je Mutationsweg pinnen (R-0724)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/refreshGuard.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @13e9a05c 2026-10-28T15:47:51+01:00
Review: approve (.ah-out/review/web-stores-refactor/T1.verdict.json)
Änderung: Neue Testdatei (SPDX wie `reset.test.ts`), `vi.mock` für `$lib/api/users` (`list`, `create`, `update`, `remove`), `$lib/api/hooks` (`list`, `create`, `update`, `remove`, `toggle`), `$lib/api/apikeys` (`list`, `create`, `remove`); `deferred()` wie `apps/web/src/lib/stores/reset.test.ts:26-30`; vor jedem Test `reset()` der drei Stores und `vi.clearAllMocks()` (die Stores sind Modul-Singletons). `describe.each` über die neun Mutationen (`users.create/update/remove`, `hooks.create/update/remove/toggle`, `apikeys.create/remove`), je mit Ausgangsliste, Aufruf und erwarteter Liste: (a) ein `refresh()`, dessen `list()` vor der Mutation startet und nach ihr mit der alten Liste ankommt, überschreibt das Ergebnis der Mutation nicht; (b) lehnt die API die Mutation ab, setzt ein laufendes `refresh()` seine Liste weiter (heute erhöht die Mutation die Generation erst nach dem `await`, `apps/web/src/lib/stores/users.ts:31-36`). Je Store: (c) zwei `refresh()`, das ältere kommt zuletzt an → der Store hält die Liste des neueren. Kein Produktionscode ändert sich; die Datei ist auf HEAD grün (Summary-Zeile in den Commit-Body).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/refreshGuard.test.ts
Doku: keine (nur Tests)
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/lib/stores/users.ts:11-49`, `hooks.ts:37-80`, `apikeys.ts:11-44`; heute pinnen den Guard nur `users.test.ts:71` (ein langsames `refresh()` gegen `users.remove`) und `reset.test.ts` (nur `reset()`); die Mutationen von `hooks`/`apikeys` und „das neuere `refresh()` gewinnt“ hat kein Test (`grep -n "it(" apps/web/src/lib/stores/{users,hooks,apikeys}.test.ts`)
Orakel: contract — der Guard, wie `apps/web/src/lib/stores/users.ts:11-13` ihn beschreibt
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T2 — Stores: Fabrik `listStore<T>` für users, hooks, apikeys (R-0724)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/listStore.ts, apps/web/src/lib/stores/users.ts, apps/web/src/lib/stores/hooks.ts, apps/web/src/lib/stores/apikeys.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @1a05af54 2026-10-28T16:49:36+01:00
Review: approve (.ah-out/review/web-stores-refactor/T2.verdict.json)
Änderung: Neu `listStore.ts` (SPDX): `listStore<T>(fetchList: () => Promise<T[]>)` liefert `{ subscribe, refresh, reset, mutate }`; `refresh()` und `reset()` wie heute (`users.ts:19-29`); `mutate<R>(call: () => Promise<R>, apply: (list: T[], result: R) => T[]): Promise<R>` wartet auf `call()`, erhöht danach die Generation, wendet `apply` an und gibt das Ergebnis zurück (eine Ablehnung erhöht nichts, wie heute). Der Kommentar `users.ts:11-13` zieht mit um. `users`, `hooks`, `apikeys` behalten ihre öffentliche Form (`subscribe`, `refresh`, `reset`, `create`, `update`, `remove`, `toggle`; Signaturen und Rückgaben unverändert) und rufen intern `mutate`; `HOOK_FIELDS`/`toListEntry` (`hooks.ts:11-35`) und die Projektion beim Anlegen eines Keys (`apikeys.ts:33-36`) bleiben im jeweiligen Store. `frp.ts` bleibt (T4). Kein Test ändert sich; die Verify-Dateien vor und nach dem Diff grün (beide Summary-Zeilen in den Commit-Body). Mutations-Stichprobe im Probe-Worktree, je allein an `listStore.ts`: M1 Erhöhung in `mutate` gestrichen → T1 (a) rot; M2 `refresh()` setzt ohne Generationsvergleich → T1 (c) rot; M3 Erhöhung vor dem `await` → T1 (b) rot. Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/refreshGuard.test.ts src/lib/stores/users.test.ts src/lib/stores/hooks.test.ts src/lib/stores/apikeys.test.ts src/lib/stores/reset.test.ts
Doku: keine (intern; der Satz zu `listStore.ts` in `docs/developer/webui.html` kommt mit T3)
Abhängt von: T1
Beweis: origin/main@b25c65a6 · `git grep -c refreshGen -- apps/web/src/lib/stores/users.ts apps/web/src/lib/stores/hooks.ts apps/web/src/lib/stores/apikeys.ts` → 7, 8, 6
Orakel: mutation-sample — M1–M3 wie in `Änderung:`; eine Stichprobe, kein Beweis der Äquivalenz
Metrik: Kopien des Guard-Musters (`git grep -c refreshGen`, git 2.47.3): users 7, hooks 8, apikeys 6 → je 0, nur noch `listStore.ts`
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T3 — Stores: eine Mutationsantwort nach dem Abmelden ändert keine Liste (R-0777)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/listStore.ts, apps/web/src/lib/stores/refreshGuard.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @ac86adde 2026-10-28T16:56:21+01:00
Review: approve (.ah-out/review/web-stores-refactor/T3.verdict.json)
Änderung: `listStore.ts` führt neben der Refresh-Generation eine Sitzungs-Epoche, die nur `reset()` erhöht. `mutate` merkt sie sich vor `call()`; hat sie sich bis zur Antwort geändert, gibt `mutate` das Ergebnis zurück, ohne die Generation zu erhöhen und ohne `apply`. Ein Kommentar nennt das Warum. Neue Tests in `refreshGuard.test.ts`, je über die neun Mutationen aus T1: (d) die Antwort kommt nach `reset()` → der Store bleibt leer; (e) nach `reset()` startet ein `refresh()` der neuen Sitzung, dann kommt die alte Antwort, dann die neue Liste `[X]` → der Store hält `[X]`. Zuerst rot auf dem Stand nach T2 (dreimal identisch, Summary-Zeilen in den Commit-Body): (d) für die drei `create` (die Liste trägt die alte Zeile), (e) für alle neun (die Erhöhung verwirft das neue `refresh()`). T1 (a)–(c) bleiben grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/refreshGuard.test.ts src/lib/stores/reset.test.ts
Doku: `docs/developer/webui.html:64` + `docs/en/developer/webui.html:64` (Abschnitt Stores): die Listen-Stores `users`, `hooks`, `apikeys` entstehen aus `listStore.ts`; eine Antwort, die nach einer neueren Änderung oder nach dem Abmelden ankommt, ändert die Liste nicht · CHANGELOG.md (Fixed, umlautfrei: eine Aenderung im Web-Panel, deren Antwort erst nach dem Abmelden ankommt, erscheint nicht mehr in der Liste und leert die erste Liste der naechsten Sitzung nicht mehr)
Abhängt von: T2
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/lib/stores/users.ts:31-36` (nach dem `await` ohne Prüfung `refreshGen++` und Anhängen), `:20-22` (das neue `refresh()` setzt nur bei gleicher Generation), `hooks.ts:56-80` und `apikeys.ts:30-44` gleich; `reset()` (`users.ts:26-29`) kennt die laufende Mutation nicht. Rot-Nachweis: (d), (e) vor dem Fix
Orakel: contract — eine Antwort aus einer beendeten Sitzung schreibt nicht in den Store
Dedup-Key: bug:web:stores/frp.ts:save-without-refreshgen
HEAD: b25c65a6

### T4 — Store `frpConfig`: `save()` gegen ein laufendes `refresh()` und nach dem Abmelden (R-0777)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/frp.ts, apps/web/src/lib/stores/frp.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @767e1206 2026-10-28T16:00:34+01:00
Review: approve (.ah-out/review/web-stores-refactor/T4.verdict.json)
Änderung: `frp.ts` bekommt die Regel aus T3 für ein Einzelobjekt: eine Epoche, die nur `reset()` erhöht; `save()` (`:30-41`) merkt sie sich vor dem API-Aufruf, erhöht nach der Antwort `refreshGen` und setzt den Store nur, wenn die Epoche gleich blieb; es gibt `saved` in jedem Fall zurück. Die Maskierung (`:34-38`) bleibt. Der Kommentar `:11-12` beschreibt die Regel selbst (heute „see users.ts“; nach T2 trägt `users.ts` den Guard nicht mehr). Neue Tests in `frp.test.ts` (`deferred()` wie `apps/web/src/lib/stores/reset.test.ts:26-30`, vorher `frpConfig.reset()`): (a) ein `refresh()` startet, `save(INPUT, cfg('1'))` gelingt, danach liefert `listConfigs` `[cfg('1', 'old')]` → der Store hält die gespeicherte Konfiguration; (b) `save()` antwortet nach `reset()` → der Store bleibt `null`, `save()` gibt die Konfiguration trotzdem zurück; (c) nach `reset()` lädt ein `refresh()` der neuen Sitzung `[cfg('2')]`, danach antwortet das alte `save()` → der Store hält `cfg('2')`. Zuerst rot auf HEAD (dreimal identisch): (a), (b), (c). Die bestehenden Tests (`frp.test.ts:27-97`) bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/frp.test.ts src/lib/stores/reset.test.ts
Doku: CHANGELOG.md (Fixed, umlautfrei: die gespeicherte FRP-Server-Konfiguration wird nicht mehr von einem noch laufenden Laden der Seite ueberschrieben)
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/lib/stores/frp.ts:30-41` (kein `refreshGen` in `save()`), `:19-21` (`refresh()` setzt bei unveränderter Generation); Rot-Nachweis (a)–(c) auf HEAD
Orakel: contract — der Guard aus `frp.ts:11-12` gilt auch für `save()`
Dedup-Key: bug:web:stores/frp.ts:save-without-refreshgen
HEAD: b25c65a6

### T5 — Client: ein 401 einer Anfrage aus einer früheren Sitzung beendet die neue nicht (R-0779)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @3d16f4d3 2026-10-28T17:06:27+01:00
Review: approve (.ah-out/review/web-stores-refactor/T5.verdict.json)
Änderung: `client.ts` führt eine Sitzungs-Generation (Modulvariable). Sie steigt in `clearTokens()` (`:54-58`) und in `setAccessToken()` (`:50-52`), wenn vorher kein Token gehalten wurde; ein Refresh mitten in der Sitzung (`tryRefresh`, `:86`) lässt sie stehen. `request()` (`:98-142`) und `requestRaw()` (`:164-181`) merken sie sich vor dem ersten Fetch. Bei einem 401: ist sie schon geändert, kein `tryRefresh`; nach `tryRefresh` erneut prüfen; bei geänderter Generation weder Wiederholung noch `onAuthFailure`, sondern wie heute `throw new ApiError(401, 'Session expired')`. Ein Kommentar nennt das Warum (der Handler beendet die Sitzung samt Refresh-Cookie, `apps/web/src/lib/stores/auth.ts:27-44`). Neue Tests in `client.test.ts` mit `importClient()` und gestubbtem `fetch` wie `:74-131`: (a) Anfrage mit `old-token` offen, dann `clearTokens()` und `setAccessToken('new-token')`, dann 401 → kein Aufruf von `/api/auth/refresh`, Handler nicht gerufen, Ablehnung `ApiError` 401 `Session expired`; (b) wie (a), aber `/api/auth/refresh` gelänge → keine Wiederholung mit `Bearer new-token` (Pfadfolge nur `['/api/servers']`); (c) 401 in der alten Sitzung, `/api/auth/refresh` offen, währenddessen `clearTokens()` und `setAccessToken('new-token')`, dann scheitert der Refresh → Handler nicht gerufen; (d) `requestRaw` wie (a); (e) Kontrolle: Anfrage mit `t1` offen, `setAccessToken('t2')` bei gehaltenem Token, dann 401 und gescheiterter Refresh → Handler genau einmal. Zuerst rot auf HEAD (dreimal identisch): (a)–(d); (e) ist auf HEAD grün und bleibt es (eine Erhöhung bei jedem `setAccessToken` machte (e) rot). Die bestehenden Tests bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts src/lib/stores/auth.test.ts
Doku: `docs/developer/webui.html:79` + `docs/en/developer/webui.html:79`, nach dem Satz zu `registerAuthFailureHandler()`: ein 401 auf eine Anfrage, die vor dem Ende der Sitzung startete, löst weder Refresh noch Abmeldung aus · CHANGELOG.md (Fixed, umlautfrei: eine Anfrage der vorigen Sitzung, die erst nach erneutem Anmelden mit 401 endet, meldet die neue Sitzung nicht mehr ab und wird nicht mit deren Token wiederholt)
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/lib/api/client.ts:110-118` und `:171-178` (kein Bezug zur Sitzung der Anfrage), `apps/web/src/lib/stores/auth.ts:100-102` → `endSession()` `:27-44` (leert die Stores; `authApi.logout()` löscht das Refresh-Cookie, `apps/web/src/lib/api/auth.ts:16-25`); `login()` wartet auf laufende Abmeldungen (`auth.ts:72-78`), nicht auf ein späteres 401. Rot-Nachweis (a)–(d) auf HEAD
Orakel: contract — `onAuthFailure` und die Wiederholung gelten nur für Anfragen der laufenden Sitzung
Dedup-Key: bug:web:stores/auth.ts:stale-auth-failure
HEAD: b25c65a6

### T6 — HookModal: Payload und Validierung pinnen (R-0722)  [x]
Komponente: web · Dateien: apps/web/src/modals/HookModal.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @c72a775d 2026-10-28T17:11:37+01:00
Review: approve (.ah-out/review/web-stores-refactor/T6.verdict.json)
Änderung: Neue Komponenten-Testdatei (SPDX, `@testing-library/svelte` wie `apps/web/src/modals/UserModal.test.ts:9-10`); `vi.mock('$lib/stores/hooks', …)` mit `create`/`update` als `vi.fn` (der Dialog ruft den Store, `HookModal.svelte:12`, `:94`, `:105`), Toasts über `$lib/stores/notifications`. Fälle, je mit genauem Payload (`toHaveBeenCalledWith`): (a) Webhook anlegen: Name `'  deploy  '` → `'deploy'`, Beschreibung nur Leerzeichen → `null`, weder `event_triggers` noch `schedule_interval`; die Antwort trägt `token` → `onClose({ token })`; (b) Event-Hook ohne Event → kein Aufruf, Toast `modal.hook.selectEvent`; (c) Event-Hook mit zwei Events → `event_triggers` in Klickreihenfolge; (d) Schedule-Hook mit Preset `6h` → `schedule_interval: '6h'`; (e) Schedule-Hook `custom` mit Cron `'  */5 * * * *  '` → getrimmt; (f) `custom` leer → kein Aufruf, Toast `modal.hook.selectInterval`; (g) Bearbeiten eines Schedule-Hooks mit `schedule_interval: '*/7 * * * *'` (kein Preset): das Formular zeigt `custom` und den Cron; geleerte Beschreibung → `update(id, { name, description: null, script, schedule_interval })` ohne `hook_type` und `event_triggers`; (h) Bearbeiten eines Event-Hooks → `event_triggers`, kein `schedule_interval`; (i) der Store wirft → `onClose` nicht gerufen. Kein Produktionscode ändert sich; die Datei ist auf HEAD grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/HookModal.test.ts
Doku: keine (nur Tests)
Beweis: origin/main@b25c65a6 · `git ls-files 'apps/web/src/modals/HookModal*'` → nur `HookModal.svelte`; Code-Lesung `apps/web/src/modals/HookModal.svelte:33-49`, `:72-118`
Orakel: contract — die Payloads nach `HookCreate`/`HookUpdate` (`apps/web/src/lib/api/types.ts:114-130`) und das heutige Verhalten des Dialogs; die leere Beschreibung als `null` ist der Fall aus R-0651
Dedup-Key: ref:web:modals:payload-logic-untested
HEAD: b25c65a6

### T7 — HookModal: Formular → Payload als reine Funktionen (R-0722)  [x]
Komponente: web · Dateien: apps/web/src/lib/utils/hookForm.ts, apps/web/src/lib/utils/hookForm.test.ts, apps/web/src/modals/HookModal.svelte
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @99ef641c 2026-10-28T17:16:36+01:00
Review: approve (.ah-out/review/web-stores-refactor/T7.verdict.json)
Änderung: Neu `hookForm.ts` (SPDX; nicht `apps/web/src/lib/utils/hooks.ts`, das audit-coverage ändert): `interface HookForm { name; description; hookType; script; events: string[]; interval; cron }`, `hookFormFrom(editing: HookDetail | null): HookForm` (heute das `$effect` `HookModal.svelte:33-49` samt Preset-Erkennung), `validateHookForm(form): 'modal.hook.selectEvent' | 'modal.hook.selectInterval' | null` (`:74-82`), `hookCreatePayload(form): HookCreate` und `hookUpdatePayload(form): HookUpdate` (`:85-103`). Der Dialog hält weiter seine `$state`-Felder und ruft die Funktionen; Toasts, `onClose` und das Token bleiben in der Komponente. `hookForm.test.ts`: die Fälle aus T6 (a)–(h) auf Funktionsebene, dazu `hookFormFrom(null)` (`webhook`, `1h`) und ein Preset beim Bearbeiten (`interval = '6h'`, `cron = ''`). `HookModal.test.ts` (T6) ändert sich nicht und ist vor und nach dem Diff grün (beide Summary-Zeilen in den Commit-Body). Mutations-Stichprobe im Probe-Worktree, je allein an `hookForm.ts`: M1 `name.trim()` → `name`; M2 `|| null` → `|| ''`; M3 `cron.trim()` → `cron`; M4 `event_triggers` auch bei `schedule` → erwartet je `HookModal.test.ts` und `hookForm.test.ts` rot.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/utils/hookForm.test.ts src/modals/HookModal.test.ts
Doku: keine (intern)
Abhängt von: T6
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/modals/HookModal.svelte:33-49`, `:72-118` (die Payload-Logik steht nur in der Komponente)
Orakel: mutation-sample — M1–M4 wie in `Änderung:`; eine Stichprobe, kein Beweis der Äquivalenz
Metrik: `wc -l apps/web/src/modals/HookModal.svelte`: 206 → weniger; Payload-Zweige mit Test auf Funktionsebene: 0 → alle (`hookForm.test.ts`)
Dedup-Key: ref:web:modals:payload-logic-untested
HEAD: b25c65a6

### T8 — UserModal: Anlegen, Server-Zuweisung und Ladefehler pinnen (R-0722)  [x]
Komponente: web · Dateien: apps/web/src/modals/UserModal.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @0c186c56 2026-10-28T17:22:20+01:00
Review: approve (.ah-out/review/web-stores-refactor/T8.verdict.json)
Änderung: Neue `describe`-Blöcke neben den Fällen zu R-0652 (`UserModal.test.ts:72-140`, bleiben unverändert). Der Mock von `$lib/api/servers` (heute `list: vi.fn(async () => [])`) liefert je Test zwei Server `{ id: 's1', name: 'web-01', hostname: 'web-01.example' }`, `{ id: 's2', name: 'db-01', hostname: 'db-01.example' }`; der Mock von `$lib/api/users` bekommt `create` (wie heute `update`). Die Hilfe `renderModal` nimmt an, die einzige Checkbox sei „Admin“; die neuen Tests suchen Server-Checkboxen über ihren Namen. Fälle: (a) Anlegen: Benutzername `'  alice  '`, Passwort, Klick auf `db-01` → `create({ username: 'alice', password, is_admin: false, server_ids: ['s2'] })`, Toast `toast.user.created`, `onClose`; (b) Anlegen ohne Passwort → kein Aufruf, Toast `modal.user.passwordRequired`; (c) einen anderen Benutzer mit `server_ids: ['s1']` bearbeiten, `s1` ab- und `s2` anwählen, Passwort leer → `update(id, { is_admin, server_ids: ['s2'] })` ohne Schlüssel `password`, Toast `toast.user.saved`; (d) die Liste zeigt Name und Hostname je Server; (e) `list()` wirft → Hinweis `page.users.serverLoadFailed` und eine Fehlermeldung; (f) leere Liste → `page.users.noServers`. Kein Produktionscode ändert sich; die Datei ist auf HEAD grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/UserModal.test.ts
Doku: keine (nur Tests)
Beweis: origin/main@b25c65a6 · `apps/web/src/modals/UserModal.test.ts:5-7` (nur das eigene Konto, R-0652); Code-Lesung `apps/web/src/modals/UserModal.svelte:45-57`, `:67-110`, `:152-169`
Orakel: contract — die Payloads nach `UserCreate`/`UserUpdate` (`apps/web/src/lib/api/types.ts:25-36`) und das heutige Verhalten des Dialogs
Dedup-Key: ref:web:modals:payload-logic-untested
HEAD: b25c65a6

### T9 — UserModal: Formular → Payload als reine Funktionen (R-0722)  [x]
Komponente: web · Dateien: apps/web/src/lib/utils/userForm.ts, apps/web/src/lib/utils/userForm.test.ts, apps/web/src/modals/UserModal.svelte
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @fa44ce50 2026-10-28T17:42:01+01:00
Review: approve (.ah-out/review/web-stores-refactor/T9.verdict.json)
Änderung: Neu `userForm.ts` (SPDX): `interface UserForm { username; password; isAdmin; serverIds: string[] }`, `validateUserForm(form, editing): 'modal.user.passwordRequired' | null`, `userCreatePayload(form): UserCreate`, `userUpdatePayload(form): UserUpdate` (Passwort nur, wenn gesetzt), `endsOwnSession(form, editing, currentUserId): boolean` (heute `ownPassword` in `onSubmit`, `UserModal.svelte:67-110`). Der Dialog ruft sie; Store-Aufrufe, `auth.logout()`/`auth.applySelfUpdate()`, Toasts und `onClose` bleiben in der Komponente. `userForm.test.ts`: die Fälle aus T8 (a)–(c) und die Regel aus R-0652 auf Funktionsebene (eigenes Konto mit Passwort → `true`; eigenes Konto ohne Passwort und fremdes Konto mit Passwort → `false`). `UserModal.test.ts` ändert sich nicht und ist vor und nach dem Diff grün. Mutations-Stichprobe im Probe-Worktree, je allein an `userForm.ts`: M1 `username.trim()` → `username`; M2 Passwort im Update immer mitsenden; M3 `endsOwnSession` ohne Vergleich der ID → erwartet je `UserModal.test.ts` und `userForm.test.ts` rot.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/utils/userForm.test.ts src/modals/UserModal.test.ts
Doku: keine (intern)
Abhängt von: T8
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/modals/UserModal.svelte:67-110` (die Payload-Logik steht nur in der Komponente)
Orakel: mutation-sample — M1–M3 wie in `Änderung:`; eine Stichprobe, kein Beweis der Äquivalenz
Metrik: `wc -l apps/web/src/modals/UserModal.svelte`: 182 → weniger; Payload-Zweige mit Test auf Funktionsebene: 0 → alle (`userForm.test.ts`)
Dedup-Key: ref:web:modals:payload-logic-untested
HEAD: b25c65a6

### T10 — Server: `GET /api/servers/summary` mit `id`, `name`, `hostname` (R-0723)  [x]
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4a7a4cc0 2026-10-28T17:55:00+01:00
Review: approve (.ah-out/review/web-stores-refactor/T10.verdict.json)
Entscheidung: Kevin 2026-10-23: Variante (c), neue Admin-Route GET /api/servers/summary.
Komponente: server · Dateien: apps/server/app/modules/servers/router.py, apps/server/app/modules/servers/schemas.py, apps/server/tests/test_servers_summary.py, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: `schemas.py`: `class ServerSummary(BaseModel)` mit `id: str`, `name: str`, `hostname: str` (Antwortmodell wie `HookResponse`, `apps/server/app/modules/hooks/schemas.py:57`). `router.py`: `@router.get("/summary", response_model=list[ServerSummary])` vor `get_server` (`:135`, sonst liest FastAPI `summary` als `server_id`), Abhängigkeiten wie `list_servers` (`:89-99`, `get_current_admin`), Abfrage `db.query(Server.id, Server.name, Server.hostname).order_by(Server.name, Server.id)`, ohne Pagination; ein Kommentar nennt das Warum (der Benutzerdialog braucht nur diese Felder; `GET /api/servers` lädt alle Verbindungen und Tunnel). Snapshot neu mit `pytest tests/test_openapi_snapshot.py --update-openapi-snapshot`; der Diff des Snapshots ist nur der neue Pfad und das neue Schema. Neue Tests `test_servers_summary.py` (SPDX; Fixtures `test_client`, `db_session`, `admin_user`, `normal_user` wie `apps/server/tests/test_servers_authz.py`): (a) Admin, zwei Server mit je einer Verbindung → je Server genau die Schlüssel `id`, `name`, `hostname`, sortiert nach Name; (b) leeres Inventar → `[]`; (c) Nicht-Admin → 403; (d) ohne Token → 401. Hosts unter `.example`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_servers_summary.py tests/test_openapi_snapshot.py tests/test_route_auth_gate.py tests/test_servers_authz.py
Doku: `docs/developer/api-reference.html:99` + `docs/en/developer/api-reference.html:99`: neue Zeile `GET /api/servers/summary` (admin; nur `id`, `name`, `hostname`, für die Server-Zuweisung im Benutzerdialog) · CHANGELOG.md (Added, umlautfrei)
Beweis: origin/main@b25c65a6 · Probe (Python 3.13.5, transiente ORM-Objekte, `Server.to_dict()` aus `apps/server/app/modules/servers/models.py:41-54`, 500 Server mit je 2 Verbindungen und 1 Tunnel, `json.dumps`, `gzip.compress(…, 6)`): voll 565 060 B / gzip 26 083 B, nur `id`/`name`/`hostname` 50 000 B / gzip 4 069 B; kein heutiger Endpunkt liefert einem Admin die Projektion (`apps/server/app/modules/users/router.py:242-244` nur eigene Server, `apps/server/app/modules/servers/router.py:69-86` nur intern)
Orakel: contract — Antwortschema `list[ServerSummary]` im OpenAPI-Snapshot und die Schlüsselmenge in Test (a)
Metrik: Bytes der Serverliste für den Dialog bei 500 synthetischen Servern (Probe wie im Beweis): 565 060 → 50 000 roh, 26 083 → 4 069 gzip
Dedup-Key: ref:web:UserModal.svelte:full-inventory-fetch
HEAD: b25c65a6

### T11 — Web: der Benutzerdialog lädt nur die Server-Zusammenfassung (R-0723)  [x]
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @302636c4 2026-10-28T18:00:01+01:00
Review: approve (.ah-out/review/web-stores-refactor/T11.verdict.json)
Entscheidung: Kevin 2026-10-23: Variante (c), der Dialog lädt die Zusammenfassung aus T10.
Komponente: web · Dateien: apps/web/src/lib/api/servers.ts, apps/web/src/lib/api/types.ts, apps/web/src/modals/UserModal.svelte, apps/web/src/modals/UserModal.test.ts, apps/web/tests/e2e/mocks.ts, apps/web/src/lib/api/mocks.contract.test.ts
Änderung: `types.ts:82-89`: `Server` wird `ServerSummary { id: string; name: string; hostname: string }` (Nutzer heute nur `servers.ts` und `UserModal.svelte:15`). `servers.ts:14-16`: `list()` wird `listSummaries(): Promise<ServerSummary[]>` → `GET /api/servers/summary`; der Kopfkommentar (`:5-9`) bleibt sinngemäß (einziger Server-Endpunkt des Web). `UserModal.svelte` ruft `listSummaries()`. `UserModal.test.ts`: der Mock von `$lib/api/servers` heißt `listSummaries` (die Fälle aus T8 bleiben, nur der Name ändert sich); neu: beim Öffnen genau ein Aufruf von `listSummaries`. `apps/web/tests/e2e/mocks.ts:297-299`: die Route wird `api('servers/summary')` (leere Liste wie heute); `MOCK_FIXTURES` (`:202`) bekommt `GET servers/summary` mit einer Zeile `{ id, name, hostname }`, damit `src/lib/api/mocks.contract.test.ts` die Form gegen `apps/server/tests/openapi.snapshot.json` prüft.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/UserModal.test.ts src/lib/api/mocks.contract.test.ts src/lib/utils/userForm.test.ts
Doku: keine (den CHANGELOG-Eintrag trägt T10; `docs/developer/webui.html:80` nennt `servers.ts` weiter „nur für die User↔Server-Zuweisung“)
Abhängt von: T9, T10
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/modals/UserModal.svelte:45-57` (`serversApi.list()`), `:152-169` (liest nur `id`, `name`, `hostname`); `git grep -nw Server -- 'apps/web/src/**/*.ts' 'apps/web/src/**/*.svelte'` → nur `types.ts:82`, `servers.ts:12-15`
Orakel: contract — `MOCK_FIXTURES` gegen den OpenAPI-Snapshot (`apps/web/src/lib/api/mocks.contract.test.ts`)
Dedup-Key: ref:web:UserModal.svelte:full-inventory-fetch
HEAD: b25c65a6

### T12 — Kopier-Helfer `copyToClipboard(text, okKey)` (R-0724)  [x]
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @10b3b282 2026-10-28T18:04:11+01:00
Review: approve (.ah-out/review/web-stores-refactor/T12.verdict.json)
Entscheidung: Kevin 2026-10-23: neuer Schlüssel toast.copyFailed „Kopieren fehlgeschlagen“ / „Copy failed“.
Komponente: web · Dateien: apps/web/src/lib/utils/clipboard.ts, apps/web/src/lib/utils/clipboard.test.ts, apps/web/src/lib/i18n/dictionaries.ts
Änderung: Neu `clipboard.ts` (SPDX): `async function copyToClipboard(text: string, okKey: string): Promise<boolean>` — `navigator.clipboard.writeText(text)` im `try`; bei Erfolg `showToast(tNow(okKey))` und `true`, sonst `showToast(tNow('toast.copyFailed'), 'error')` und `false` (`tNow` wie `apps/web/src/lib/api/client.ts:40`). `dictionaries.ts`: `toast.copyFailed` DE „Kopieren fehlgeschlagen“, EN „Copy failed“ (neben `toast.apikey.copied`, `:132` / EN `:421`). `clipboard.test.ts` (Toasts über den Store `toasts`, `apps/web/src/lib/stores/notifications.ts:20`): (a) Erfolg → `writeText` mit dem Text, ein Toast `success` mit dem Text des Schlüssels (im Test das vorhandene `toast.hook.tokenCopied`, damit kein Schlüssel nur im Test lebt), Rückgabe `true`; (b) `writeText` lehnt ab → ein Toast `error` „Kopieren fehlgeschlagen“, Rückgabe `false`; (c) kein `navigator.clipboard` (unsicherer Kontext) → wie (b), kein Wurf. Noch kein Dialog nutzt den Helfer (T14).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/utils/clipboard.test.ts src/lib/i18n/i18n.test.ts
Doku: keine (den CHANGELOG-Eintrag trägt T14)
Beweis: origin/main@b25c65a6 · `git grep -n "navigator.clipboard.writeText" -- 'apps/web/src/**/*.svelte'` → `KeyRevealModal.svelte:23`, `WebhookTokenModal.svelte:32`, `EnrollTokenModal.svelte:69`, `FrpConfigPreviewModal.svelte:24`; Fehlertexte `'Clipboard error'` (`KeyRevealModal.svelte:26`, `WebhookTokenModal.svelte:35`, `EnrollTokenModal.svelte:72`) und `error.generic` (`FrpConfigPreviewModal.svelte:27`)
Orakel: contract — ein übersetzter Fehlertext für alle Kopier-Knöpfe
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T13 — Kopier-Knöpfe der vier Dialoge pinnen (R-0724)  [x]
Komponente: web · Dateien: apps/web/src/modals/copyButtons.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @d0393d78 2026-10-28T18:08:33+01:00
Review: approve (.ah-out/review/web-stores-refactor/T13.verdict.json)
Änderung: Neue Testdatei (SPDX), `describe.each` über `KeyRevealModal` (Wert), `WebhookTokenModal` (Token), `EnrollTokenModal` (Token nach dem Ausstellen, wie `apps/web/src/modals/EnrollTokenModal.test.ts:94-104`) und `FrpConfigPreviewModal` (Inhalt): Klick auf den Kopier-Knopf → `navigator.clipboard.writeText` mit genau dem angezeigten Wert und ein Erfolgs-Toast mit dem heutigen Text („In Zwischenablage kopiert“ bzw. „Token kopiert“). Den Fehlerweg pinnt die Datei noch nicht (er ändert sich in T14). Props je Dialog aus der Komponente lesen; Platzhalter-Werte ohne echtes Token-Format. Kein Produktionscode ändert sich; auf HEAD grün.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/copyButtons.test.ts
Doku: keine (nur Tests)
Beweis: origin/main@b25c65a6 · `git ls-files 'apps/web/src/modals/*.test.ts'` → `EnrollTokenModal.test.ts` (Kopieren ohne Toast-Prüfung, `:94-104`), `FrpConfigModal.test.ts`, `UserModal.test.ts`; die Kopier-Wege von `KeyRevealModal`, `WebhookTokenModal`, `FrpConfigPreviewModal` hat kein Test (`git grep -n FrpConfigPreviewModal -- 'apps/web/src/**/*.test.ts'` leer)
Orakel: contract — kopiert wird der angezeigte Wert, der Erfolgstext bleibt
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T14 — Die vier Dialoge kopieren über den Helfer (R-0724)  [x]
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @608622c7 2026-10-28T18:14:11+01:00
Review: approve (.ah-out/review/web-stores-refactor/T14.verdict.json)
Entscheidung: Kevin 2026-10-23: wie T12.
Komponente: web · Dateien: apps/web/src/modals/KeyRevealModal.svelte, apps/web/src/modals/WebhookTokenModal.svelte, apps/web/src/modals/EnrollTokenModal.svelte, apps/web/src/modals/FrpConfigPreviewModal.svelte, apps/web/src/modals/copyButtons.test.ts, apps/web/src/lib/i18n/dictionaries.ts, CHANGELOG.md
Änderung: Jeder Kopier-Handler (`KeyRevealModal.svelte:21-27`, `WebhookTokenModal.svelte:30-36`, `EnrollTokenModal.svelte:66-74` mit seinem `if (!grant) return;`, `FrpConfigPreviewModal.svelte:22-29`) wird ein Aufruf von `copyToClipboard(<Wert>, <Schlüssel>)`; ein danach ungenutzter Import von `showToast` geht mit. Schlüssel: neu `toast.copied` (DE „In Zwischenablage kopiert“, EN „Copied to clipboard“) für KeyReveal, Enrollment und FrpConfigPreview; WebhookToken behält `toast.hook.tokenCopied`. `toast.apikey.copied` und `toast.frp.copied` (`dictionaries.ts:132`, `:291`, EN `:421`, `:579`) gehen, weil ohne Nutzer. `copyButtons.test.ts`: die Erfolgsfälle aus T13 bleiben unverändert; neu je Dialog der Fehlerweg (`writeText` lehnt ab → ein Toast `error` „Kopieren fehlgeschlagen“). Zuerst rot auf dem Stand vor dem Diff: der Fehlerweg in drei Dialogen („Clipboard error“) und in FrpConfigPreview („Fehler“). Sieben Dateien, je Dialog etwa fünf Zeilen.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/copyButtons.test.ts src/modals/EnrollTokenModal.test.ts src/lib/utils/clipboard.test.ts src/lib/i18n/i18n.test.ts
Doku: CHANGELOG.md (Changed, umlautfrei: scheitert das Kopieren in die Zwischenablage, melden alle Dialoge des Web-Panels uebersetzt „Kopieren fehlgeschlagen“ statt „Clipboard error“ oder „Fehler“)
Abhängt von: T12, T13
Beweis: wie T12
Orakel: contract — ein Helfer, ein Fehlertext
Metrik: eigene Kopier-Handler in Dialogen (`git grep -c "navigator.clipboard.writeText" -- 'apps/web/src/**/*.svelte'`, git 2.47.3): 4 → 0
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T15 — Router: tote Exporte `navigate`, `currentPath`, `segments` (R-0724)  [x]
Komponente: web · Dateien: apps/web/src/lib/router.ts, apps/web/src/lib/router.test.ts, docs/developer/webui.html, docs/en/developer/webui.html
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @00c2f526 2026-10-28T18:19:42+01:00
Review: approve (.ah-out/review/web-stores-refactor/T15.verdict.json)
Änderung: `navigate` (`router.ts:20-27`), `currentPath` (`:35-37`) und `segments` (`:39`) gehen; der Import (`:5`) wird `import { writable } from 'svelte/store';`. `path` und `replace` bleiben (Nutzer `apps/web/src/App.svelte:10`, `apps/web/src/lib/components/layout/Router.svelte:8`, `apps/web/src/lib/components/layout/Sidebar.svelte:11`). `router.test.ts`: 'readHash normalizes "#/servers" to "/servers" on init', 'defaults to /users when the hash is empty' und 'replace updates the store via replaceState (no history push)' lesen den Pfad über `get(path)` statt `currentPath()`; der Kopfkommentar (`:5-8`) verliert „navigate's manual store-set on the already-active hash“.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/router.test.ts src/lib/routeGuard.test.ts
Doku: `docs/developer/webui.html:60` + `docs/en/developer/webui.html:60`: statt „exportiert `navigate()`, `replace()`, `currentPath()` und einen `segments`-Derived-Store“ nun „exportiert den lesbaren Store `path` und `replace()`“
Test-Löschung: apps/web/src/lib/router.test.ts::navigate to a new hash writes location.hash (normalizing a missing leading slash) — toter Code navigate geht; apps/web/src/lib/router.test.ts::navigate on the already-active hash does not rewrite location.hash (the guard holds) — toter Code navigate geht; apps/web/src/lib/router.test.ts::segments splits the path and drops empty parts — toter Code segments geht
Beweis: origin/main@b25c65a6 · `git grep -nw -e navigate -e currentPath -e segments -- apps/web ':!apps/web/src/lib/router.ts' ':!apps/web/src/lib/router.test.ts'` → leer (Exit 1); außerhalb von `apps/web` nennen nur `docs/developer/webui.html:60` + EN die Exporte, die Desktop-UI hat ihren eigenen Router. Checkliste dynamischer Wege: kein `import.meta.glob` und kein `import(` mit Variable auf `router`, keine Nutzung über `window`, E2E und Live-Tests (`apps/web/tests/`) ohne Treffer
Orakel: analyzer — Wort-`grep` repo-weit (git 2.47.3); `npm run check` (svelte-check 4.6.0) und ESLint im Verify fangen einen übersehenen Import
Metrik: gelöschte Zeilen in `router.ts` (13 der 39) und drei Tests in `router.test.ts`
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T16 — Toter Code: `requireUser` und die Prop `size` von `Button` (R-0724)  [x]
Komponente: web · Dateien: apps/web/src/lib/stores/auth.ts, apps/web/src/lib/components/ui/Button.svelte
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @e6460176 2026-10-28T18:22:13+01:00
Review: approve (.ah-out/review/web-stores-refactor/T16.verdict.json)
Änderung: `requireUser` (`auth.ts:104-108`) geht; `get` und `User` bleiben genutzt (`:87`, `:15`, `:86`). In `Button.svelte` gehen der Typ `Size` (`:11`), die Prop `size` (`:16`, `:30`) und ihr Zweig in der Klasse (`:41`); die CSS-Klasse `.btn.small` bleibt (rohe `<button class="btn small">`).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/auth.test.ts src/lib/components/ui/ConfirmDialog.test.ts src/modals/FrpConfigModal.test.ts
Doku: keine (`git grep -n requireUser -- docs` leer; die Prop ist nicht dokumentiert)
Beweis: origin/main@b25c65a6 · `git grep -nw requireUser -- . ':!apps/web/src/lib/stores/auth.ts'` → leer (Exit 1); `git grep -nw size -- 'apps/web/src/**/*.svelte' ':!apps/web/src/lib/components/ui/Button.svelte'` → nur `apps/web/src/modals/HookModal.svelte:74` (`events.size`, ein `Set`). Checkliste dynamischer Wege: keine Props per Spread (`git grep -n "{\.\.\." -- 'apps/web/src/**/*.svelte'` leer), keine Nutzung über `window`
Orakel: analyzer — Wort-`grep` (git 2.47.3); `npm run check` (svelte-check 4.6.0) meldet eine übersehene `size=`-Prop als Typfehler
Metrik: gelöschte Zeilen: 5 in `auth.ts`, 4 in `Button.svelte`
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T17 — Toter Code: `getAccessToken` (R-0724)  [~] (verworfen (Kevin 2026-10-28): getAccessToken ist nicht tot, client.crosstab.test.ts nutzt ihn)
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts
Änderung: `getAccessToken` (`client.ts:46-48`) geht. Im Test 'retries the original request with the new token after a successful refresh' (`client.test.ts:74-104`) gehen `getAccessToken` aus dem Import (`:91`) und die Assertion `:101`; an ihre Stelle tritt eine Folgeanfrage: ein zweites `http.get` schickt `Authorization: Bearer new-token`, ohne erneuten Refresh. Der Test bleibt und prüft dasselbe (der gehaltene Token ist der neue).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts
Doku: keine (nicht dokumentiert)
Abhängt von: T5 (gleiche Dateien)
Beweis: origin/main@b25c65a6 · `git grep -nw getAccessToken -- . ':!apps/web/src/lib/api/client.ts' ':!apps/web/src/lib/api/client.test.ts'` → leer (Exit 1); Checkliste: kein `import(` mit Variable auf `client`, keine Nutzung über `window`, Desktop-UI ohne Treffer
Orakel: analyzer — Wort-`grep` (git 2.47.3)
Metrik: gelöschte Zeilen: 4 in `client.ts`
Dedup-Key: ref:web:copy-handler-and-dead-code
HEAD: b25c65a6

### T18 — Audit-Ansicht zeigt `detail` (R-0757)  [x]
Komponente: web · Dateien: apps/web/src/pages/Audit.svelte, apps/web/src/pages/Audit.test.ts, apps/web/src/lib/i18n/dictionaries.ts, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @23c0276a 2026-10-28T18:26:27+01:00
Review: approve (.ah-out/review/web-stores-refactor/T18.verdict.json)
Änderung: Neue Spalte zwischen Objekt (`Audit.svelte:120`, `:134`) und IP: Kopf `page.audit.col.detail` (DE „Detail“, EN „Detail“, neben `page.audit.col.object`, `dictionaries.ts:114` / EN `:403`), Zelle `{e.detail ?? '–'}` wie die IP (`:135`), CSS mit `overflow-wrap: anywhere`, damit ein langer Text die Tabelle nicht sprengt. Der Text bleibt Text (Svelte escaped, kein `{@html}`). Neue Testdatei `Audit.test.ts` (SPDX; `vi.mock('$lib/api/audit', …)` liefert zwei Einträge, einer mit `detail: 'is_admin, server_ids'`, einer mit `detail: null`): (a) die Tabelle hat die Spalte „Detail“, und die Zeile des ersten Eintrags zeigt `is_admin, server_ids`; (b) die des zweiten zeigt `–`; (c) ein `detail` `<b>x</b>` erscheint als Text, kein `<b>`-Element in der Tabelle. Zuerst rot auf HEAD: (a), (c).
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Audit.test.ts src/lib/i18n/i18n.test.ts
Doku: `docs/admin/betrieb.html:133` + `docs/en/admin/operations.html:92`: die Ansicht zeigt je Eintrag auch das Detail (etwa geänderte Felder) · CHANGELOG.md (Changed, umlautfrei: das Audit-Log im Web-Panel zeigt die Spalte Detail)
Beweis: origin/main@b25c65a6 · Code-Lesung `apps/web/src/pages/Audit.svelte:114-142` (sechs Spalten, kein `detail`), `apps/web/src/lib/api/types.ts:203` (`detail?: string | null`), `apps/server/app/modules/audit/models.py:52` (die Antwort trägt `detail`); Rot-Nachweis (a), (c) auf HEAD
Orakel: contract — was `GET /api/audit` je Eintrag liefert, zeigt die Ansicht
Dedup-Key: ref:web:Audit.svelte:detail-not-shown
HEAD: b25c65a6

### T19 — Lockstep-Check: `Server` ist kein gemeinsames Symbol mehr (R-0723)  [x]
Komponente: scripts · Dateien: apps/desktop/ui/scripts/sync-from-web.sh, scripts/tests/sync_check_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7eba6d71 2026-10-28T20:47:30+01:00
Review: approve (.ah-out/review/web-stores-refactor/T19.verdict.json)
Änderung: T11 benennt im Web `Server` in `ServerSummary` um (nur `id`, `name`, `hostname`); der Desktop behält sein volles `Server`. Der CI-Schritt „Shared API types in lockstep with the web frontend“ (`sync-from-web.sh --check`) ist deshalb auf PR #290 rot: `CHECK_SHARED` (`sync-from-web.sh:107`) verlangt `Server` auf beiden Seiten. Kevin 2026-10-28: Fix-Task. `Server` geht aus `CHECK_SHARED`, der Kommentar darüber nennt drei Symbole. In `sync_check_test.sh` zieht der Fall „ein gemeinsames Symbol verschwindet“ von `Server` auf `FrpStatus` um (gleich stark: ein einzelnes erwartetes Symbol fehlt auf einer Seite → Exit 1), die Kommentare nennen drei Symbole. Neuer Fall: `sync-from-web.sh --check` auf dem echten Checkout endet mit 0 — lokal fuhr bisher nur die CI diesen Check, darum fiel die Drift erst auf dem PR auf. Zuerst rot: der neue Fall auf HEAD.
Verify: bash scripts/dev/verify.sh scripts --strict -- sync_check_test
Doku: DEVELOPMENT.md (Abschnitt geteilte API-Typen: drei Symbole, Server-Beispiel historisch) + docs/developer/cicd.html und docs/en/developer/cicd.html (Absatz „Geteilte API-Typen“ / „Shared API types“); der Kommentar in `.github/workflows/ci.yml` nennt noch vier Typen: Workflow-Pfad, Kevin, Roadmap-Zeile
Beweis: PR #290, CI-Job „Desktop-UI (svelte-check + lint + vitest) + E2E lint“, Lauf 40747391035: „FEHLER: src/lib/api/types.ts: erwartete gemeinsame Symbole fehlen auf einer Seite: Server“; lokal `bash apps/desktop/ui/scripts/sync-from-web.sh --check` → Exit 1
HEAD: 60b12ad6

## Entscheidungen
- 2026-10-28 T4: save() erhoeht refreshGen nur, wenn die Epoche gleich blieb (die Task sagt: nach der Antwort immer) — ein Bump nach reset() verwuerfe das Laden der naechsten Sitzung; ein Kontrolltest in frp.test.ts haelt das fest.
- 2026-10-28 T8: UserModal.test.ts war von T2 (ac86adde) bis T8 rot: listStore liest api.list beim Laden des Moduls, der Mock von $lib/api/users hatte kein list; das Verify von T2 nannte die Datei nicht. T8 ergaenzt list im Mock; vor dem PR faehrt die Abschlusspruefung die ganze Web-Suite.
