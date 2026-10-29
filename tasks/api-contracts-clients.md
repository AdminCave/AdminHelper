<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# API-Verträge: Antwortmodelle für Server und Monitoring, Client-Typen gegen den Snapshot (Teil clients) — Task-Ledger
Status: aktiv · Branch: feature/api-contracts-clients · Review: pro Task
Spec: docs/features/api-contracts.md (Roadmap R-0686, R-0687)
Heavy: none — Teil-Ledger von tasks/api-contracts.md (T18–T25); die schwere Prüfung (linux-full + scenario + windows) fährt das Vorhabens-Ledger vor dem Merge
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Jede JSON-Route des Servers außer den Nicht-Zielen der Spec deklariert ein `response_model`, das die heutige
Antwort Schlüssel für Schlüssel abbildet (R-0684). (2) Dasselbe für Monitoring außer `/health` und dem Agent-Report
(R-0685). (3) Web- und Desktop-`types.ts` werden je von einem Vertragstest gegen die Snapshots geprüft, die Drift ist
behoben, auch das fehlende Datum eines neuen API-Schlüssels (R-0686, R-0687). (4) Die Monitoring-Sektionen der
Desktop-UI lesen `state.details` über Narrowing-Funktionen statt über `as` (R-0687). Keine Antwort ändert sich;
`scripts/dev/openapi-breaking.sh` meldet je Task 0 ERR. Zeilenangaben: origin/main@b25c65a6; der builder greppt sie
vor dem Schreiben neu.

Für alle Tasks:
- Blöcke und Reihenfolge: A Server T1–T12 (T2 nach T1, T11 vor T12), B Monitoring T13–T17, C Web T18–T19, D Desktop-UI
  T20–T25. A und B sind unabhängig. T18 und T23 gehen jederzeit. T19 nach T2, T9, T10, T12. T20 nach Block A und T19.
  T21 und T22 nach Block B und T20. T24 und T25 nach T23. Eine Teilung in die Teil-Ledger `api-contracts-server`
  (T1–T12), `api-contracts-monitoring` (T13–T17) und `api-contracts-clients` (T18–T25) ist Kevins Wort (Spec,
  Trade-off 8).
- Hängt ab von `fehlervertrag` (freigegeben, eigener Branch). Geteilte Dateien: `CHANGELOG.md` (hier T12, T17, T18),
  `apps/web/src/lib/api/types.ts` (hier T18, T19; dort die Klasse `ApiError`); über Folgeänderungen möglich
  `apps/desktop/ui/src/lib/stores/monitoring.ts` und `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte`.
  Ist `fehlervertrag` gemergt, vor der ersten Task, die eine dieser Dateien berührt, `origin/main` hineinmergen.
- Antwortmodelle nach den Regeln 1–7 der Spec („Datenmodell“): Schlüssel wie der Produzent, Feldname = JSON-Schlüssel,
  Zeitstempel `str`/`Optional[str]`, kein Typ enger als Spalte und alle Schreiber, die es je gab (bei JSON in einer
  Textspalte belegt `git log -S` an der Validierung, seit wann sie gilt; älter als die Spalte → `list[str]`, sonst
  `list[Any]`), bedingte Schlüssel als Feld mit Default `None` plus `response_model_exclude_unset=True` an jeder Route,
  die das Modell auch verschachtelt liefert, keine Validatoren, keine Grenzen. Ein Routen-Docstring ist die
  OpenAPI-description und bleibt unverändert.
- Testmuster je Server- und Monitoring-Task in `tests/test_response_shapes.py` der Komponente (T1 bzw. T13 legt die
  Datei an, SPDX per `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`): (a) das
  2xx-Schema der Operation im laufenden `app.openapi()` verweist auf das neue Modell (rot auf HEAD); (b) Gleichheit über
  die echte Route, `resp.json() == jsonable_encoder(<Produzent>)`, mit einer vollen Zeile und einer dünnen (alle
  nullbaren Spalten `NULL`), Muster `TestConfigResponseShape` (`apps/server/tests/test_frp_config.py:581-680`);
  (c) jede bedingte Variante (Schlüssel fehlt / ist da). Danach den Snapshot neu schreiben
  (`pytest tests/test_openapi_snapshot.py --update-openapi-snapshot` im Komponenten-Verzeichnis) und
  `bash scripts/dev/openapi-breaking.sh <server|monitoring>` fahren: 0 ERR, Ausgabe-Zusammenfassung in den Commit-Body.
- `security` zusätzlich (`scripts/dev/review-risk.txt`): T1–T10, T12–T17, T19–T22.
- Platzhalter in Tests: Hosts unter `.example`, Adressen aus RFC 5737.

Teil-Ledger (Kevin 2026-10-23, Spec Trade-off 8): T18–T25 aus `tasks/api-contracts.md`, gemergt in `feature/api-contracts`. CHANGELOG-Einträge in `changelog.d/api-contracts-clients.md` statt `CHANGELOG.md` (Konvention seit dem Plan). Abhängigkeiten auf T1–T17: der Server- und der Monitoring-Teil werden vor T19/T20/T21 in `feature/api-contracts` gemergt und von dort hineingezogen.

### T18 — web: neuer API-Schlüssel zeigt sein Erstelldatum (R-0686)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/types.ts, apps/web/src/lib/stores/apikeys.ts, apps/web/src/lib/stores/apikeys.test.ts, changelog.d/api-contracts-clients.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @c7a3908b 2026-10-29T22:49:44+01:00
Review: approve (.ah-out/review/api-contracts-clients/T18.verdict.json)
Änderung: Zuerst der rote Test in `apikeys.test.ts` (neben `create returns the secret but never stores it in the list`, `:35`): `api.create` liefert `{ key, id, name, permission, created_at: '2026-01-02T03:04:05Z' }`; nach `apikeys.create(...)` trägt der neue Listeneintrag `created_at` mit genau diesem Wert und weiterhin kein `key`. Dann `ApiKeyCreateResult` (`apps/web/src/lib/api/types.ts:61-66`) um `created_at?: string | null` ergänzen (`ApiKeyCreatedResponse`, `apps/server/app/modules/api_keys/schemas.py:18-28`: nicht required, nullbar) und `ApiKey.created_at` (`:53`) ebenso auf `string | null`; der Store übernimmt es (`apps/web/src/lib/stores/apikeys.ts:33-36`). `formatDate` nimmt `null` schon (`src/lib/utils/datetime.ts:24`).
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/stores/apikeys.test.ts
Doku: changelog.d/api-contracts-clients.md (Fixed, umlautfrei: ein neu angelegter API-Schluessel zeigt sein Erstelldatum sofort, nicht erst nach dem Neuladen)
Beweis: origin/main@b25c65a6 · der neue Test aus `Änderung:` auf HEAD dreimal rot: Erwartung `created_at: '2026-01-02T03:04:05Z'`, Beobachtung `undefined` (`apikeys.ts:33-36` baut den Eintrag aus `id`, `name`, `permission`)
Orakel: contract — der Listeneintrag gegen die Antwort von `POST /api/api-keys`
Dedup-Key: ref:web:types.ts:handwritten-api-types
HEAD: b25c65a6

### T19 — web: Vertragstest `types.contract.test.ts` und Typ-Korrekturen (R-0686)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/types.contract.test.ts, apps/web/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/types.ts, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @56ed10db 2026-10-29T23:31:20+01:00
Review: approve (.ah-out/review/api-contracts-clients/T19.verdict.json)
Änderung: Neue Testdatei (SPDX) nach den Regeln der Spec („Client-Vertragstest“): `typescript` (devDependency) liest `types.ts` per `ts.createSourceFile`, der Test liest `apps/server/tests/openapi.snapshot.json` wie `mocks.contract.test.ts` (`deref`, `shapeOf`). Zuordnungstabelle für die Antwort-Interfaces (`LoginResponse`, `RefreshResponse`, `User`, `EnrollmentGrant`, `ApiKey`, `ApiKeyCreateResult`, `Server`, `Hook`, `HookDetail`, `HookCreateResult`, `HookTokenResult`, `FrpConfig`, `FrpStatusProxy`, `FrpStatus`, `AuditEntry`) und die Anfrage-Interfaces (`UserCreate`, `UserUpdate`, `ApiKeyCreate`, `HookCreate`, `HookUpdate`, `FrpConfigInput`), je mit `omit` und Grund; `HookRunResult` und `ApiError` sind ausgenommen (Nicht-Ziel bzw. kein Schema). Wächter: Paare existieren, Zahl gepinnt, Gegenprobe je Regel an einem synthetischen Paar. Korrekturen, die der Test verlangt, mindestens: `User.created_at` (`types.ts:21`) bekommt `| null` (Schema: required und nullbar, `apps/server/app/modules/users/schemas.py:80`), `FrpConfig.bindPort` (`:147`) `number | null` (`apps/server/app/modules/frp/schemas.py:299`; Leser `FrpConfigModal.svelte:47` hat schon `?? 7000`), `FrpStatusProxy` (`:172-182`) `tunnel` aufnehmen oder in `omit`. Die geteilten Symbole `FrpConfig`, `FrpStatus`, `FrpStatusProxy`, `Server` (`apps/desktop/ui/scripts/sync-from-web.sh:107`) im selben Commit gleich in der Desktop-`types.ts`; `svelte-check` beider Frontends muss grün bleiben.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/types.contract.test.ts  und bash apps/desktop/ui/scripts/sync-from-web.sh --check
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Abschnitt „Paritäts- und Contract-Gates“ / „Parity and contract gates“: Zeile „Web-Typen gegen den Server-Snapshot“ mit Datei und Regeln)
Abhängt von: T2, T9, T10, T12
Beweis: origin/main@b25c65a6 · Lese-Probe: `ApiKeyCreateResult` (`types.ts:61-66`) ohne `created_at`, `User.created_at?: string` ohne `null`, `FrpConfig.bindPort: number` gegen `Optional[int]`; kein Test liest `types.ts` gegen den Snapshot (`grep -rl openapi.snapshot apps/web/src` → nur `mocks.contract.test.ts`)
Orakel: contract — jedes zugeordnete Interface gegen sein Komponenten-Schema; jede Regel schlägt an ihrem synthetischen Paar an
Dedup-Key: ref:web:types.ts:handwritten-api-types
HEAD: b25c65a6

### T20 — desktop-ui: Vertragstest gegen den Server-Snapshot (R-0687)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @b9cf931c 2026-10-29T23:41:45+01:00
Review: approve (.ah-out/review/api-contracts-clients/T20.verdict.json)
Änderung: Neue Testdatei (SPDX), Helfer wie in T19 (Spec, Trade-off 3), liest `apps/server/tests/openapi.snapshot.json`. Zuordnung der Server-Interfaces in `apps/desktop/ui/src/lib/api/types.ts`: Antwort `Connection` (`:7-22`), `Server` (`:24-32`), `Playbook` (`:63-71`), `FrpConfig` (`:85-99`), `FrpTunnel` (`:104-120`), `FrpStatus` (`:150-154`), `FrpStatusProxy`, `FrpProvisionToken` (`:156-163`), `FrpProvisionTokenCreateResult` (`:165-170`), `NotificationItem` (`:557-569`), `NotificationSubscription` (`:572-582`), `NotificationPrefs` (`:584-588`); Anfrage `ServerInput` (`:34-40`) und die übrigen `…Input`-Typen mit Schema. Korrekturen, die der Test verlangt (u. a. `createdAt`, `frpTunnels` an `Server`, `extraConfig` an `FrpConfig`/`FrpTunnel`: aufnehmen oder `omit` mit Grund); die geteilten Symbole bleiben mit Web gleich (`sync-from-web.sh --check`). Aufrufer, die eine Korrektur bricht, per `ledger.sh set-files` aufnehmen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts  und bash apps/desktop/ui/scripts/sync-from-web.sh --check
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (Zeile „Desktop-Typen gegen beide Snapshots“; der Satz `:334-336` / EN entsprechend sagt künftig, dass Web- und Desktop-Typen gegen den Snapshot geprüft werden, der Agent nicht) · DEVELOPMENT.md (bei `sync-from-web.sh`, `:360-368`: eine geänderte Antwort zieht Modell, Snapshot und beide `types.ts` im selben Commit nach)
Abhängt von: T1 bis T12, T19
Beweis: origin/main@b25c65a6 · kein Test der Desktop-UI liest einen Snapshot (`grep -rl openapi.snapshot apps/desktop/ui/src` leer); `sync-from-web.sh:107` prüft vier von 63 Exporten
Orakel: contract — jedes zugeordnete Interface gegen sein Komponenten-Schema; jede Regel schlägt an ihrem synthetischen Paar an
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T21 — desktop-ui: Monitoring-Typen für Checks, Status, Alerts, Wartung (R-0685, R-0687)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/models/monitoring.ts, apps/desktop/ui/src/lib/models/monitoring.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a2681fd6 2026-10-29T23:52:38+01:00
Review: approve (.ah-out/review/api-contracts-clients/T21.verdict.json)
Änderung: Die Zuordnung liest zusätzlich `apps/monitoring/tests/openapi.snapshot.json`: `MonitorCheck` (`types.ts:442-460`), `MonitorCheckState` (`:435-440`), `MonitoringMetricsResponse` (`:507-510`), `AlertRule` (`:521-530`), `AlertLogEntry` (`:541-549`), `MaintenanceWindow` (`:479-492`) und die Anfrage-Typen mit Schema. Korrekturen: `AlertLogEntry.id` `string` → `number` (Spalte `Integer`, `apps/monitoring/app/models.py:188`; `MonitoringLog.svelte:17` nutzt sie nur als each-Key) und `alertRuleId`; `MonitorCheckState` mit `checkId`, `since`, `failCount`, `notifiedStatus` und `| null` an `message`, `lastCheck`, `details`; nullbares `enabled`. Aufrufer: `apps/desktop/ui/src/lib/models/monitoring.ts:196` (`return check.enabled && …` gibt bei `null` `null` zurück) wird `check.enabled === true && …` oder liefert explizit `boolean`; weitere Treffer von `svelte-check` per `ledger.sh set-files` (erwartet u. a. `MonitoringAlerts.svelte:41`, `AlertRuleModal.svelte:47`, `MaintenanceModal.svelte:76`). Die Darstellung gültiger Daten bleibt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts src/lib/models/monitoring.test.ts
Doku: keine
Abhängt von: T13, T14, T15, T20
Beweis: origin/main@b25c65a6 · `AlertLogEntry.id: string` (`types.ts:542`) gegen `id = Column(Integer, …)` (`apps/monitoring/app/models.py:188`), ausgegeben in `:203`
Orakel: contract — die Monitoring-Interfaces gegen den Monitoring-Snapshot
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T22 — desktop-ui: Monitoring-Typen für Templates (R-0685, R-0687)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/api/monitoring.ts
Änderung: Zuordnung für `MonitoringTemplateFull` (`types.ts:642-658`), `MonitoringTemplateAssignment` (`:629-634`), `MonitoringBuiltinUpdate` (`:674-679`), `TemplateSuggestion` (inline in `apps/desktop/ui/src/lib/api/monitoring.ts:31-36`, nach `types.ts` verschoben, damit der Test es findet) und `TemplateCheckDef`/`TemplateAlertDef` (`:608-627`) in Richtung Anfrage. Korrekturen: `createdAt`, `updatedAt`, `syncResult` an `MonitoringTemplateFull`, `id`, `templateId` an `MonitoringTemplateAssignment` (aufnehmen oder `omit` mit Grund). Aufrufer wie T21.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts src/lib/api/monitoring.test.ts
Doku: keine
Abhängt von: T17, T21
Beweis: origin/main@b25c65a6 · `MonitoringTemplateFull` (`types.ts:642-658`) ohne `createdAt`, `updatedAt`, `syncResult`, die `MonitorTemplate.to_dict` (`apps/monitoring/app/models.py:232-257`) bzw. die PUT-Route liefern
Orakel: contract — die Template-Interfaces gegen den Monitoring-Snapshot
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T23 — desktop-ui: Narrowing-Funktionen für `state.details` (R-0687)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/checkDetails.ts, apps/desktop/ui/src/lib/models/checkDetails.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0da44c2f 2026-10-29T22:58:39+01:00
Review: approve (.ah-out/review/api-contracts-clients/T23.verdict.json)
Änderung: Neue Dateien (SPDX). Je Checker-Form eine Funktion `unknown → <Typ> | null` (bzw. Liste leer) für `MonitorZfsDetails`, `MonitorSmartDetails` (kennt auch `{absent: <Grund>}`, `apps/monitoring/app/checkers/smart.py:97`), `MonitorResourceDetails`, `MonitorForecastDetails`, `MonitorServiceDetails`, `MonitorContainerDetails` (`apps/desktop/ui/src/lib/api/types.ts:424-433`). Ein Feld mit falschem Typ gilt als fehlend, gültige Daten kommen unverändert zurück; Vorbild für das Prüfen `SecSystem.svelte:67-97` (`LooseDetails`, `asFlag`, `asCount`). Tests je Funktion: gültige Form, `null`/`undefined`, Feld mit falschem Typ, SMART `absent`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/checkDetails.test.ts
Doku: keine
Beweis: origin/main@b25c65a6 · `grep -c ' as Monitor[A-Za-z]*Details' src/components/monitoring/section/*.svelte` (in `apps/desktop/ui`) → 9 Casts in sechs Dateien; `MonitorCheckDetails` endet mit `Record<string, unknown>` (`types.ts:433`), jeder Cast kompiliert
Orakel: contract — die Narrower gegen die Formen der Checker
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T24 — desktop-ui: SecZfs, SecSmart, SecForecast ohne Cast (R-0687)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte, apps/desktop/ui/src/components/monitoring/section/SecSmart.svelte, apps/desktop/ui/src/components/monitoring/section/SecForecast.svelte, apps/desktop/ui/src/components/monitoring/section/SecSmart.test.ts, apps/desktop/ui/src/components/monitoring/section/SecForecast.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @6295523f 2026-10-29T23:07:34+01:00
Review: approve (.ah-out/review/api-contracts-clients/T24.verdict.json)
Änderung: Die Casts `SecZfs.svelte:34`, `:38`, `SecSmart.svelte:28`, `SecForecast.svelte:22` werden Aufrufe der Narrower aus T23. Die Darstellung gültiger Daten bleibt; SMART `absent` wird typisiert, nicht angezeigt (eine Anzeige wäre sichtbares Verhalten). Neue Tests (SPDX) für SecSmart und SecForecast wie `SecZfs.test.ts`: gültige Daten rendern wie heute, `details` mit falschem Feldtyp rendert die leere Sektion statt zu werfen. Suite vor und nach dem Diff grün, beide Summary-Zeilen in den Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecZfs.test.ts src/components/monitoring/section/SecSmart.test.ts src/components/monitoring/section/SecForecast.test.ts
Doku: keine
Abhängt von: T23
Beweis: origin/main@b25c65a6 · Grep wie T23: 4 der 9 Casts in diesen drei Dateien
Orakel: metric — Casts `as Monitor…Details` in den drei Dateien
Metrik: `grep -c ' as Monitor[A-Za-z]*Details'` (GNU grep) über SecZfs, SecSmart, SecForecast: 4 → 0
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

### T25 — desktop-ui: SecLive, SecServices, SecDocker ohne Cast (R-0687)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecLive.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecDocker.svelte, apps/desktop/ui/src/components/monitoring/section/SecLive.test.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts, apps/desktop/ui/src/components/monitoring/section/SecDocker.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @7778b35d 2026-10-29T23:15:42+01:00
Review: approve (.ah-out/review/api-contracts-clients/T25.verdict.json)
Änderung: Die Casts `SecLive.svelte:79`, `:118`, `:129`, `SecServices.svelte:77`, `SecDocker.svelte:89` werden Aufrufe der Narrower aus T23. Je vorhandene Testdatei ein Fall mit falschem Feldtyp in `details` (leere bzw. Rückfall-Darstellung statt Wurf); die bestehenden Fälle bleiben unverändert grün. Suite vor und nach dem Diff grün, beide Summary-Zeilen in den Commit-Body.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecLive.test.ts src/components/monitoring/section/SecServices.test.ts src/components/monitoring/section/SecDocker.test.ts
Doku: keine
Abhängt von: T23
Beweis: origin/main@b25c65a6 · Grep wie T23: 5 der 9 Casts in diesen drei Dateien
Orakel: metric — Casts `as Monitor…Details` in den drei Dateien
Metrik: `grep -c ' as Monitor[A-Za-z]*Details'` (GNU grep) über SecLive, SecServices, SecDocker: 5 → 0
Dedup-Key: ref:desktop:types.ts:no-contract-test
HEAD: b25c65a6

## Entscheidungen
- 2026-10-29 T19: Web-Zuordnung `ServerSummary` → `ServerSummary` statt `Server` — das Web kennt seit R-0723 nur `ServerSummary`, `Server` steht nicht mehr in `types.ts` und nicht mehr in `sync-from-web.sh` (`CHECK_SHARED`).
- 2026-10-29 T19: `User` gegen zwei Schemas (`UserResponse`, `UserMe`) — `/api/auth/me` und die Nutzerliste teilen im Web einen Typ; ein Feld ist nur Pflicht, wo beide Schemas es verlangen. Kein neuer Typ, keine Umbenennung in Stores und Seiten.
- 2026-10-29 T19: Über die drei Pflicht-Korrekturen hinaus verlangte der Test `token_type?` in `LoginResponse`/`RefreshResponse` (Schema nicht required), `EnrollmentGrant.expiresAt: string | null` und `FrpStatus.error?: string | null` (geteilt, Desktop gleich); keine Leser betroffen (`formatDateTime` nimmt `null`, `status.error` wird nur auf Wahrheit geprüft). `FrpConfig.extraConfig` und `FrpStatusProxy.tunnel` stehen in `omit`: kein Client liest sie.
- 2026-10-29 T19: Zusätzlicher Wächter: jedes Interface in `types.ts` ist zugeordnet oder steht in `EXEMPT` (`HookRunResult`, `AuditQuery`) mit Grund — ein neues Interface muss eingeordnet werden. Eine `omit`-Angabe, die das Schema nicht (mehr) kennt oder die das Interface doch beschreibt, ist rot.
- 2026-10-29 T20: Die Desktop-Zuordnung trägt je Interface den Snapshot (`server`/`monitoring`); T20 ordnet die 18 Server-Interfaces zu, die Monitoring-Interfaces stehen bis T21/T22 mit diesem Grund in `EXEMPT` (T21/T22 ersetzen ihn durch die Zuordnung oder einen bleibenden Grund). `MonCheckSummary` bleibt ausgenommen (Ausschnitt von `MonitorCheck` für `computeSummary`).
- 2026-10-29 T20: `Server` nimmt `frpTunnels?` und `createdAt?` auf (der Typ beschreibt, was der Server sendet; `?` hält jeden Leser unverändert); `FrpTunnel.extraConfig` steht in `omit` wie `FrpConfig.extraConfig`. Nullbar geworden: `FrpTunnel.localIp`/`enabled`, `FrpProvisionToken.expiresAt`, `FrpProvisionTokenCreateResult.expiresAt`, `NotificationItem.createdAt`; `svelte-check` ohne Befund (`fmt`, `timeAgo` und `frpTunnel.ts:63` nehmen `null` schon), keine Datei außerhalb von `Dateien:`.
- 2026-10-29 T21: Bleibend ausgenommen: `MonitorCheckConfig`, `AlertChannelConfig` (frei geformte Konfiguration, im Schema `any`/`object`), `MonitoringMetricSeries` (eine VictoriaMetrics-Reihe im frei geformten `data`) und die zehn `Monitor…Details` (frei geformtes `state.details`, eingeengt in `models/checkDetails.ts`). Aufgenommen statt `omit`: `createdAt`/`updatedAt` an `MonitorCheck` und `AlertRule`, `templateId` an `AlertRule`, `checkId`/`checkType`/`period` an `MonitoringMetricsResponse`, alle optional. `svelte-check` traf nur `canRunManually` (über `MonitoringTab.svelte:397` und `MonCheckLine.svelte:56`); die in der Task erwarteten Treffer in `MonitoringAlerts.svelte`, `AlertRuleModal.svelte`, `MaintenanceModal.svelte` gab es nicht. `monitoring.test.ts` dazu (Test für `enabled: null`).
