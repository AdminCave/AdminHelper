<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# API-Verträge: Antwortmodelle für Server und Monitoring, Client-Typen gegen den Snapshot geprüft

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand; bei Routen ist es die
`def`-Zeile des Handlers. Ledger: `tasks/api-contracts.md`. Roadmap R-0684 (T1–T12), R-0685 (T13–T17, T21, T22),
R-0686 (T18, T19), R-0687 (T20, T23–T25). Das Vorhaben baut nach `fehlervertrag` (geteilte Dateien unter „Risiken“).

## Problem / Motivation

1. **Der Server beschreibt die Hälfte seiner Antworten nicht (R-0684).** Probe (AST über `apps/server/app`, alle
   Routen-Decorators mit ihren `response_model`/`response_class`): 83 Routen, eine davon ohne Schema
   (`main.py:501`); der Snapshot `apps/server/tests/openapi.snapshot.json` hat 82 Operationen, 21 mit einem 2xx-Schema,
   das Felder nennt, 11 ohne Body, 50 mit `{}` oder einem Objekt ohne Felder. 33 JSON-Routen haben weder `response_model` noch `response_class`, sechs weitere nur `dict[str, Any]`
   (`audit/router.py:25`, `connections/router.py:95`, `:110`, `:138`, `:173`, `notifications/router.py:48`). Im
   Snapshot steht für sie `{}` oder ein Objekt mit `additionalProperties: true` ohne Felder. Ihre Antworten bauen
   handgeschriebene `to_dict()` (`servers/models.py:41-55`, `connections/models.py:66-90`, `ansible/models.py:25`,
   `audit/models.py:39-53`, `notifications/models.py:68`, `:104`, `provisioning/models.py:49-57`) oder Dict-Literale
   (`enrollment/router.py:44-65`, `provisioning/router.py:209-226`, `frp/generate_router.py:159`,
   `frp/provision_router.py:89`, `:92`, `hooks/router.py:334`). Darunter stehen die Antworten, die Agent und Desktop
   lesen: Activate (Agent), `config-hash` (Agent), Tunnels, `visitor-bundle` und Enrollment-Grant (Desktop).
   Für die Tunnel-Routen gibt es das passende Modell schon (`FrpTunnelOut`, `frp/schemas.py:312`), die Routen
   (`frp/tunnel_router.py:26`, `:67`, `:153`, `:161`) nutzen es nicht. Die Schreibweise der Antworten ist gemischt
   (hooks/users snake_case, servers/frp/connections camelCase).
2. **Monitoring beschreibt keine Antwort (R-0685).** Alle 37 JSON-Antworten der 44 Operationen in
   `apps/monitoring/tests/openapi.snapshot.json` haben das Schema `{}`; die übrigen sieben sind 204. Kein Monitoring-Router
   setzt `response_model`. Der einzige Leser ist die Desktop-UI über den Server-Proxy, und ihre Typen sind gedriftet:
   `AlertLogEntry.id: string` (`apps/desktop/ui/src/lib/api/types.ts:542`) gegen `id = Column(Integer, …)`
   (`apps/monitoring/app/models.py:188`), so ausgegeben in `models.py:203`. Weitere Drift (Explore-Lauf an
   `b25c65a6`): `MonitorCheckState` (`types.ts:435-440`) fehlen `checkId`, `since`, `failCount`, `notifiedStatus`,
   und `message`, `lastCheck`, `details` fehlt `| null` (`models.py:125-135`); `MonitorCheck` (`:442-460`) fehlen
   `createdAt`, `updatedAt`; `AlertRule` (`:521-530`) fehlen `templateId`, `createdAt`, `updatedAt`;
   `AlertLogEntry` fehlt `alertRuleId`; `MonitoringMetricsResponse` (`:507-510`) fehlen `checkId`, `checkType`,
   `period`; `MonitoringTemplateFull` (`:642-658`) fehlen `createdAt`, `updatedAt`, `syncResult`;
   `MonitoringTemplateAssignment` (`:629-634`) fehlen `id`, `templateId`. Die Entwickler-Doku nennt den Snapshot
   den Vertrag, „den Web-Frontend, Desktop-UI und Agent benutzen, ohne gegen ihn kompiliert zu werden“
   (`docs/developer/cicd.html:334-336`): geprüft wird keiner der Leser.
3. **Die Web-Typen sind handgeschrieben und gedriftet (R-0686).** `ApiKeyCreateResult`
   (`apps/web/src/lib/api/types.ts:61-66`) fehlt `created_at`, obwohl `POST /api/api-keys` es schickt
   (`apps/server/app/modules/api_keys/schemas.py:18-28`). Der Store baut den neuen Listeneintrag daraus ohne Datum
   (`apps/web/src/lib/stores/apikeys.ts:33-36`); die Seite zeigt für den neuen Schlüssel bis zum Neuladen „-“
   (`apps/web/src/pages/ApiKeys.svelte:96`). Dazu: `User.created_at?: string` (`types.ts:21`) gegen
   `created_at: Optional[str]` ohne Default, also immer da und nullbar (`users/schemas.py:80`);
   `FrpConfig.bindPort: number` (`types.ts:147`) gegen `bindPort: Optional[int]` (`frp/schemas.py:299`);
   `FrpStatusProxy` (`types.ts:172-182`) fehlt `tunnel` (`frp/schemas.py:349`); `Server` (`types.ts:82-89`) ist eine
   Teilmenge.
4. **Die Desktop-Typen haben kein Gate (R-0687).** `apps/desktop/ui/src/lib/api/types.ts` hat 686 Zeilen und 63
   Exporte. `sync-from-web.sh --check` prüft nur die Schnittmenge mit den Web-Typen, heute genau vier Symbole
   (`apps/desktop/ui/scripts/sync-from-web.sh:107`), und das als Zeilen-Teilmenge. Kein Test der Desktop-UI liest
   einen der beiden Snapshots; der Transport prüft nichts zur Laufzeit (`src/lib/api/request.ts:31-49` →
   `bridge.apiProxy` → `serde_json::Value` in `apps/desktop/src-tauri/src/commands.rs:238-245`). Die
   Monitoring-Sektionen casten `state.details` per `as` (`SecZfs.svelte:34`, `:38`, `SecSmart.svelte:28`,
   `SecLive.svelte:79`, `:118`, `:129`, `SecForecast.svelte:22`, `SecServices.svelte:77`, `SecDocker.svelte:89`, alle
   unter `src/components/monitoring/section/`); weil die Union `MonitorCheckDetails` mit `Record<string, unknown>`
   endet (`types.ts:424-433`), kompiliert jeder Cast. Beleg für die Drift dahinter: der SMART-Checker schreibt
   `{"absent": reason}` (`apps/monitoring/app/checkers/smart.py:97`), das `MonitorSmartDetails` nicht kennt.

Proben an `b25c65a6` (Scratch, nicht versioniert):
- **oasdiff 1.32.0:** ein 2xx-Schema von `{}` auf ein typisiertes Objekt heben ergibt nur INFO
  (`response-body-type-specialized`, `response-required-property-added`, `response-optional-property-added`), 0 ERR;
  ebenso `dict[str, Any]` → typisiert. Das Hinzufügen der Modelle bricht `scripts/dev/openapi-breaking.sh` also nicht;
  danach ist das Entfernen eines Feldes ERR.
- **TypeScript-Compiler-API** (`typescript` 6.0.3, devDependency beider Frontends): `ts.createSourceFile` liest beide
  `types.ts` mit Namen, `?` und Typtext jedes Felds (Web 23 Interfaces, Desktop 50). Ein Vertragstest braucht damit
  keine neue Abhängigkeit.

## Ziel & Nicht-Ziele

**Ziel**
1. Jede JSON-Route des Servers, die keine der Ausnahmen unten ist, deklariert ein `response_model`, das die heutige
   Antwort Schlüssel für Schlüssel abbildet. Die Antwort zur Laufzeit bleibt gleich; je Route belegt das ein
   Gleichheitstest über die echte Route (Muster `TestConfigResponseShape`, `apps/server/tests/test_frp_config.py:581-680`).
2. Dasselbe für die JSON-Routen von Monitoring außer `/health` und dem Agent-Report.
3. Web- und Desktop-`types.ts` werden gegen die Snapshots geprüft (Schlüsselmengen, optional/nullbar, primitive
   Typen), ohne neue Abhängigkeit.
4. Die Drift aus Problem 2 bis 4 ist behoben, auch der sichtbare Fehler beim Datum eines neuen API-Schlüssels.
5. Die Monitoring-Sektionen lesen `state.details` über Narrowing-Funktionen in `src/lib/models/` statt über `as`.

**Nicht-Ziele**
- **Schreibweise vereinheitlichen** (snake_case/camelCase): jede Umbenennung entfernt ein Feld, oasdiff meldet ERR,
  alle Leser brechen. Die Modelle bilden die heutige Schreibweise ab.
- **Hook-Läufe** `POST /api/hooks/trigger`, `/trigger/{token}`, `/{id}/run` (`hooks/router.py:229`, `:244`, `:337`):
  die Antwort bestimmt das Skript des Admins (`script_runner.py:257-266`, `script_worker.py:186-198`, `result` und
  `logs` frei); ein exaktes Modell wäre `Any`. Der Web-Typ `HookRunResult` stimmt seit R-0562.
- **Nicht-JSON-Routen:** `generate/frps-toml`, `frpc-toml`, `visitor-toml`, `bulk-zip`
  (`frp/generate_router.py:65`, `:76`, `:107`, `:163`), `provision/{id}/config` (`frp/provision_router.py:61`),
  `connections/export` (`connections/router.py:224`, `response_class=Response`), der Monitoring-Proxy
  (`monitoring_proxy/router.py:72`, `:116`) und der Notification-Stream (`notifications/stream.py:94`). Ein Medientyp
  im Schema wäre eine eigene Entscheidung.
- **Monitoring `/health`** (`apps/monitoring/app/main.py:158`) und **`POST /agent/{id}/report`**
  (`routers/agent.py:74`): kein Client spiegelt sie, der Agent verwirft die Antwort
  (`apps/agent/internal/monitor/report.go:186`).
- **Agent-Seite:** JSON-Schema des Agent-Reports und die Go-Spiegel von Activate und Bundles gehören zu R-0688
  (der Agent ist mit anderen Vorhaben belegt). T6 gibt Activate ein Modell; die Go-Seite prüft es nicht.
- **Rust-Leser** (`desktop-rs`: Tunnels, `visitor-bundle`, Enrollment, Auth): ein Vertragstest der serde-Structs gegen
  den Snapshot wäre der nächste Schritt; die Dateien ändert `fehlervertrag` (T5–T9). Vorschlag für eine Folgezeile.
- **Generierte Typen** (`openapi-typescript`, Vorschlag in R-0686): ersetzt durch den Vertragstest, Trade-off 2.
- **Laufzeitprüfung** der Antworten in den Clients (`request.ts`, zod o. ä.): nein.
- Fremder Kommentar mit veralteten Zahlen: `sync-from-web.sh:31-32` nennt 25 Web- und 58 Desktop-Exporte (heute 26
  und 63). Die Aussage „genau vier Symbole“ (`:33-34`) stimmt; der Kommentar bleibt.

## Betroffene Komponenten & Dateien

| Komponente | Dateien | Tasks |
|---|---|---|
| server | `app/modules/{connections,servers,ansible,notifications,users,hooks}/schemas.py`, neu `{audit,enrollment,provisioning}/schemas.py`, die Router der Module (`connections`, `servers`, `frp/tunnel_router.py`, `frp/generate_router.py`, `frp/provision_router.py`, `frp/schemas.py`, `ansible`, `provisioning`, `notifications`, `users/auth_router.py`, `users/router.py`, `hooks`, `enrollment`, `audit`), neu `tests/test_response_shapes.py`, `tests/openapi.snapshot.json` | T1–T10, T12 |
| web | `tests/e2e/mocks.ts`, `src/lib/api/mocks.contract.test.ts` (T10–T12), `src/lib/api/types.ts`, `src/lib/stores/apikeys.ts` (+Test), neu `src/lib/api/types.contract.test.ts` | T10–T12, T18, T19 |
| monitoring | `app/schemas.py`, `app/routers/{checks,alerts,maintenance,admin,templates}.py`, neu `tests/test_response_shapes.py`, `tests/openapi.snapshot.json`, `tests/test_templates_router.py` | T13–T17 |
| desktop-ui | `src/lib/api/types.ts`, neu `src/lib/api/types.contract.test.ts`, `src/lib/api/monitoring.ts`, `src/lib/models/monitoring.ts`, neu `src/lib/models/checkDetails.ts` (+Test), `src/components/monitoring/section/Sec{Zfs,Smart,Forecast,Live,Services,Docker}.svelte` (+Tests) | T19 (Gleichschritt), T20–T25 |
| Doku | `CHANGELOG.md`, `docs/developer/cicd.html` + `docs/en/developer/cicd.html`, `DEVELOPMENT.md` | T12, T17–T20 |

Auf `scripts/dev/review-risk.txt` stehen `apps/server/app/modules/*/schemas.py`, `apps/monitoring/app/schemas.py`,
`enrollment/*`, `users/*`, `notifications/*`, `servers/router.py`, `frp/*` und `apps/desktop/ui/src/lib/api/types.ts`:
T1–T10, T12–T17 und T19–T22 bekommen zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration. OpenAPI: neue Komponenten-Schemas `…Out`, die 2xx-Antworten verweisen darauf; oasdiff meldet nur INFO
(Probe oben). Die Antworten ändern sich nicht.

**Regeln für die Antwortmodelle** (Präzedenz R-0043, `FrpServerConfigOut`/`FrpTunnelOut`, `frp/schemas.py:288-329`):
1. Schlüssel für Schlüssel wie der Produzent; Feldnamen sind die JSON-Schlüssel (camelCase, wo `to_dict` camelCase
   schreibt), kein Alias.
2. Zeitstempel bleiben `str`/`Optional[str]` (die Strings aus `iso_utc`, `apps/server/app/core/time.py:47-55`;
   `UtcDatetime` würde neu serialisieren; Kommentar zu R-0064 in `users/schemas.py:78-79`).
3. Kein Typ enger als die Spalte und alle Schreiber, die es je gab: nullbare Spalte → `Optional`; JSON in einer
   Textspalte ohne durchgehende Validierung → `list[Any]`/`dict[str, Any]` (Verbindungen: die Import-Validierung kam
   mit v0.36.0, Commit `84d4eaa8`; ältere Zeilen können Tags mit Nicht-Strings und Arten außer ssh/rdp/web tragen);
   frei geformte Felder (`config`, `details`, `channelConfig`, `extraConfig`, Template-Definitionen, Metrik-Serien)
   → `Any`/`dict[str, Any]`. Monitoring: `enabled`, `consecutive_fails`, `fail_count`, `cooldown_minutes` und alle
   Zeitstempel sind nullbare Spalten.
4. Bedingte Schlüssel (`serverId` einer Verbindung ohne Server, `connections/models.py:66-90`; `state` eines Checks
   ohne Zustandszeile, `apps/monitoring/app/models.py:77-100`; `assignments`, `tagAssignments`, `syncResult` eines
   Templates): Feld mit Default `None` und `response_model_exclude_unset=True` an jeder Route, die das Modell
   (auch verschachtelt) liefert. Ein fehlender Schlüssel bleibt weg, ein vorhandenes `null` bleibt `null`.
5. Offene Dicts (Verbindungen mischen `extra_data` ein, `connections/models.py:66-90`):
   `model_config = ConfigDict(extra="allow")`.
6. Keine Validatoren, keine Grenzen (`ge`, `max_length`), keine Defaults außer Regel 4: ein Antwortmodell beschreibt.
7. Ein zu strenges Modell wird zur 500 (`ResponseValidationError`). Darum je Produzent ein Gleichheitstest mit einer
   vollen und einer dünnen Zeile (alle nullbaren Spalten `NULL`); in der PR-CI prüft schemathesis jede deklarierte
   Antwort gegen echte Antworten (`response_schema_conformance`, `apps/server/tests/test_schemathesis.py`,
   `apps/monitoring/tests/test_schemathesis.py:120-126`).

**Regeln für den Client-Vertragstest** (Web T19, Desktop T20–T22): eine Zuordnungstabelle im Test nennt je TS-Interface
den Snapshot (server/monitoring), das Komponenten-Schema, die Richtung (Antwort/Anfrage) und optional `omit` (Felder,
die der Client bewusst nicht beschreibt, je mit Grund). `extends` und Typ-Aliase derselben Datei werden aufgelöst.
- Antwort: (1) jedes TS-Feld ist ein Schema-Feld (außer das Schema ist offen); (2) jedes Schema-Feld ist ein TS-Feld
  oder steht in `omit`; (3) nicht `required` → TS-Feld hat `?`; (4) nullbar → TS-Typ enthält `null`; (5) wo beide
  Seiten primitiv sind, stimmt die Art (string/number/boolean/array; String-Literal-Unions zählen als string). Der
  TS-Typ darf weiter sein (optional oder nullbar, wo das Schema es nicht ist).
- Anfrage: (1); `required` im Schema → TS-Feld ohne `?`; `| null` im TS nur, wenn das Schema nullbar ist; (5).
- Wächter: jedes zugeordnete Interface und Schema existiert; die Zahl der Zuordnungen ist gepinnt; eine Gegenprobe im
  Test zeigt, dass jede Regel an einem synthetischen Paar anschlägt (wie `test_the_lint_sees_an_unbounded_integer`,
  `apps/server/tests/test_openapi_integer_bounds.py`).

## Externe Integrationen

- **FastAPI 0.138.0 / pydantic 2.13.4** (gepinnt in `apps/server/requirements.txt`, Monitoring gleich): ein
  `response_model` validiert ein zurückgegebenes Dict, verwirft nicht deklarierte Schlüssel (bei `extra="ignore"`),
  ergänzt Defaults, serialisiert `by_alias`; ein Validierungsfehler wird 500. Pydantic v2 wandelt im Lax-Modus `int`
  nicht in `str`. Mit `extra="allow"` bleiben Zusatzschlüssel erhalten; ob `exclude_unset` sie mitgibt, ist **nicht
  verifiziert** (T1 prüft es mit einer Zeile mit `extra_data`). Der builder von T1 liest vorher die offizielle Doku
  (Response Model, `response_model_exclude_unset`).
- **oasdiff 1.32.0** (`scripts/dev/openapi-breaking.sh`): Probe oben.
- **TypeScript 6.0.3 Compiler-API**: `createSourceFile`, `InterfaceDeclaration`, `PropertySignature` (Probe oben).
- **schemathesis** in der PR-CI: prüft die neuen Schemas gegen echte Antworten.

## Trade-offs & Alternativen

1. **Exakte Modelle statt normalisierter** (eine Schreibweise, `datetime`, engere Typen): normalisieren ändert jede
   Antwort und ist Kevins Entscheidung. Empfehlung exakt: das Vorhaben bleibt vertragsneutral, eine spätere
   Normalisierung wird mit den Modellen eine sichtbare, von oasdiff gemeldete Änderung.
2. **Client-Typen: Vertragstest statt `openapi-typescript`** (R-0686 schlägt Generierung vor) **oder zod**.
   Empfehlung Vertragstest: keine neue Abhängigkeit (Lizenzliste, Audit); die handgeschriebenen Namen bleiben (63 bzw.
   26 Exporte, genutzt in Stores, Models, Komponenten; generierte Typen hießen nach den Schemas und brächten einen
   großen Diff, der mit `fehlervertrag` kollidiert); die Monitoring-Pfade kommen über das Proxy-Präfix
   `/api/monitoring/`, generierte Pfadtypen passten nicht. Trade-off: der Test prüft Schlüssel, Optionalität,
   Nullbarkeit und primitive Arten, nicht die Tiefe frei geformter Felder; `omit` ist eine bewusste Lücke mit Grund.
   Generierung bleibt später möglich, die Modelle sind ihre Voraussetzung.
3. **Zwei Testdateien statt eines geteilten Moduls:** ein Helfer außerhalb von `apps/web` und `apps/desktop/ui`
   fände `typescript` nicht (kein `node_modules` im Repo-Wurzelverzeichnis). Die Desktop-Datei übernimmt den Helfer
   der Web-Datei; Muster ist `apps/web/src/lib/api/mocks.contract.test.ts` (`deref`, `shapeOf`).
4. **Anfragen mitprüfen:** die Request-Schemas gibt es heute schon (`ServerCreate`, `ConnectionCreate`,
   `FrpTunnelCreate`, `CheckCreate` …); dieselbe Maschine prüft sie mit. Antworten allein ließen die Hälfte von
   `types.ts` ohne Gate.
5. **`sync-from-web.sh` bleibt:** der Gleichschritt der vier geteilten Symbole hält Web und Desktop textgleich; die
   Vertragstests prüfen jede Seite gegen den Server. T19 ändert geteilte Zeilen auf beiden Seiten im selben Commit.
6. **Narrowing zentral in `src/lib/models/checkDetails.ts`** (Vorschlag R-0687) statt `LooseDetails` je Komponente
   (Vorbild `SecSystem.svelte:67-97`, `SecBackups.svelte:49-67`): ohne Komponente testbar, eine Stelle je
   Checker-Form. Ein Feld mit falschem Typ gilt als fehlend; die Darstellung gültiger Daten bleibt.
7. **Monitoring-Umfang:** alle JSON-Routen außer `/health` und Agent-Report, auch die, die die Desktop-UI nicht ruft
   (sie teilen die Modelle); `POST /agent-keys` liest der Server (`provisioning/helpers.py:64-66`).
8. **Ein Ledger oder Teil-Ledger:** 25 Tasks. Vorschlag (Kevins Wort, CLAUDE.md §2): `api-contracts-server`
   (T1–T12), `api-contracts-monitoring` (T13–T17), `api-contracts-clients` (T18–T25, T19 ff. nach den beiden
   anderen). Server und Monitoring berühren getrennte Dateien und Snapshots und können parallel laufen.

## Risiken & Rollback

- **500 durch ein zu strenges Modell:** Regeln 3, 6, 7; Gleichheitstests mit dünner Zeile; schemathesis in der PR-CI.
- **Altdaten** (Verbindungen vor v0.36.0): `kind: str`, `tags: list[Any]`; T1 testet eine direkt per ORM geschriebene
  Zeile mit `kind="vnc"` und `tags='[1, "a"]'`.
- **Web-Mock-Vertrag:** `mocks.contract.test.ts:146` pinnt `checked == 16`; sobald Enrollment (T10) und Audit (T12)
  ein Schema haben, steigt die Zahl. `AUDIT_ROWS` (`apps/web/tests/e2e/mocks.ts:57-76`) fehlen `actorId`, `objectId`,
  `sourceIp`, `status`, `detail`; T11 ergänzt sie vor T12. Die Audit-Seite steht im Bildvergleich
  (`smoke.spec.ts-snapshots/audit-chromium-linux.png`, Toleranz 2 %); `status: 'success'` ändert die Statuszelle. Ob
  das in der Toleranz bleibt, ist nicht verifiziert: T11 fährt `smoke.spec.ts`.
- **Nullbarkeit in der Desktop-UI:** `enabled: boolean | null` u. a. kann Aufrufer brechen (erwartet
  `src/lib/models/monitoring.ts:196`); der builder erweitert `Dateien:` per `ledger.sh set-files`.
- **Snapshot-Konflikte** mit parallelen Branches: nach jedem Merge von `main` neu aufzeichnen.
- **Geteilte Dateien mit `fehlervertrag`:** `CHANGELOG.md` (T12, T17, T18); `apps/web/src/lib/api/types.ts`
  (T18, T19; dort T3, Klasse `ApiError`); möglich über Folgeänderungen `apps/desktop/ui/src/lib/stores/monitoring.ts`
  (dort T13) und `src/components/monitoring/BuiltinUpdateModal.svelte` (dort T12). Der Snapshot ändert sich in
  `fehlervertrag` nicht.
- **Rollback:** additiv, keine Migration; der Revert einer Task stellt Modell und Snapshot zurück.

## Doku-Impact

- `CHANGELOG.md`: T12 (Changed: Server-OpenAPI beschreibt die Antworten), T17 (Changed: dasselbe für Monitoring), T18
  (Fixed: Datum eines neuen API-Schlüssels).
- `docs/developer/cicd.html` + `docs/en/developer/cicd.html`, Abschnitt „Paritäts- und Contract-Gates“: T19 (Zeile
  Web-Typen), T20 (Zeile Desktop-Typen, Satz zum Snapshot `:334-336`).
- `DEVELOPMENT.md` (bei `sync-from-web.sh`, `:360-368`): T20, was bei einer Antwortänderung mitzuziehen ist.
- Sonst keine: die API-Referenz verweist für Schemas auf `/api/docs` (`docs/developer/api-reference.html:34`).

## Offene Fragen

1. **Teilung in Teil-Ledger** (Trade-off 8): Kevins Wort. Empfehlung: teilen, Server und Monitoring parallel.
2. **`scenario` vor dem Merge** (ask-first, `Heavy:` im Ledger): die Antworten bleiben byte-gleich, aber Activate,
   `config-hash`, Tunnels und `visitor-bundle` liest nur der echte Agent bzw. Desktop. Empfehlung: fahren.
3. Zur Kenntnis: Vertragstest statt `openapi-typescript` (Trade-off 2); R-0407 (zurückgestellt, typisierte
   Grant-Antwort) erledigt T10 mit; Folgezeile für die Rust-/Go-Leser.
