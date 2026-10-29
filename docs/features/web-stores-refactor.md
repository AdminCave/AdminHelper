<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: Store-Fabrik und Stale-Guards, Formular-Payloads, schlanke Serverliste, Kopier-Helfer, toter Code, Audit-Detail

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand (PR #267 ist seither
gemergt, `origin/main@53a7dbc5`; er ändert von den Dateien dieses Plans nur `CHANGELOG.md`). Ledger:
`tasks/web-stores-refactor.md`. Roadmap R-0724 (T1, T2, T12–T17), R-0777 (T3, T4), R-0779 (T5), R-0722 (T6–T9),
R-0723 (T10, T11), R-0757 (T18).

## Problem / Motivation

1. **Formular → Payload ohne Test (R-0722).** `onSubmit` in `apps/web/src/modals/HookModal.svelte:72-118` baut
   `HookCreate`/`HookUpdate` inline: Name getrimmt, leere Beschreibung als `null` (`:88`, `:99`), Event-Hook ohne Event
   → Toast `modal.hook.selectEvent`, Schedule-Hook mit Preset oder getrimmtem Cron (`interval === 'custom'`), leeres
   Intervall → Toast `modal.hook.selectInterval`, beim Anlegen eines Webhooks geht der Token an `onClose({ token })`.
   `onSubmit` in `apps/web/src/modals/UserModal.svelte:67-110` (die Zeile nennt `:66-99`; die Stelle ist gewandert)
   baut `UserCreate`/`UserUpdate`: `server_ids` aus der Auswahl, Passwort nur wenn gesetzt, beim Anlegen Pflicht
   (`modal.user.passwordRequired`), eigenes Passwort → Abmelden. `HookModal` hat keinen Test; `UserModal.test.ts` deckt
   nur das Bearbeiten des eigenen Kontos (R-0652). Anlegen, Server-Zuweisung, Ladefehler und alle Hook-Payloads sind
   ungetestet; die E2E (`apps/web/tests/e2e/crud.spec.ts`) legt nur an und löscht.
2. **Benutzerdialog lädt das ganze Inventar (R-0723).** `loadServers` (`UserModal.svelte:45-57`) ruft
   `serversApi.list()` (`apps/web/src/lib/api/servers.ts:14-16`) → `GET /api/servers`
   (`apps/server/app/modules/servers/router.py:89-99`) → `Server.to_dict()` mit allen Verbindungen und `frpTunnels`
   (`apps/server/app/modules/servers/models.py:41-54`, Beziehungen `lazy="selectin"` `:26-39`). Der Dialog liest nur
   `id`, `name`, `hostname` (`UserModal.svelte:152-169`). Probe (Python 3.13.5, transiente ORM-Objekte, echtes
   `to_dict`, 500 Server mit je 2 Verbindungen und 1 Tunnel, `json.dumps`, gzip Stufe 6): **565 060 B, gzip 26 083 B**;
   nur `id`/`name`/`hostname`: **50 000 B, gzip 4 069 B**. Die Daten sind synthetisch und stark komprimierbar; echte
   Namen, Notizen und Tags komprimieren schlechter. Kein heutiger Endpunkt liefert einem Admin die schlanke Liste:
   `GET /api/users/me/servers` (`apps/server/app/modules/users/router.py:242-244`) nur die eigenen zugewiesenen
   Server, `GET /api/internal/servers` (`router.py:69-86`) nur mit dem internen Schlüssel.
3. **Kopierte Muster und toter Code (R-0724).** (a) Der Stale-Guard `refreshGen` steht dreimal fast gleich in
   `apps/web/src/lib/stores/users.ts:11-49`, `hooks.ts:37-80`, `apikeys.ts:11-44` (dazu `frp.ts:11-28` für ein
   Einzelobjekt). (b) Vier Kopier-Handler: `KeyRevealModal.svelte:21-27`, `WebhookTokenModal.svelte:30-36`,
   `EnrollTokenModal.svelte:66-74`, `FrpConfigPreviewModal.svelte:22-29`. Der Fehlertext ist dreimal das feste
   englische `'Clipboard error'`, einmal `error.generic` („Fehler“). Dass Enrollment `toast.apikey.copied` meldet, ist
   kein sichtbarer Fehler: der Text ist derselbe wie `toast.frp.copied` (`apps/web/src/lib/i18n/dictionaries.ts:132`,
   `:291`, EN `:421`, `:579`). (c) Toter Code, repo-weiter Wort-`grep` (`git grep -nw`, git 2.47.3) findet nur die
   eigene Definition und eigene Tests: `requireUser` (`apps/web/src/lib/stores/auth.ts:104-108`; die Zeile nennt
   `:63`), `navigate`, `currentPath`, `segments` (`apps/web/src/lib/router.ts:20-27`, `:35-37`, `:39`; dazu
   `router.test.ts` und der Satz `docs/developer/webui.html:60` + EN), `getAccessToken` (`apps/web/src/lib/api/client.ts:46-48`,
   nur `client.test.ts:91`, `:101`), die Prop `size` von `apps/web/src/lib/components/ui/Button.svelte:11`, `:16`,
   `:30`, `:41` (kein `<Button size=…>` im Repo).
4. **Stale-Guard lückenhaft (R-0777).** `frpConfig.save()` (`apps/web/src/lib/stores/frp.ts:30-41`) erhöht
   `refreshGen` nicht: ein `refresh()` (`:18-22`), das vor dem Speichern startete und danach ankommt, setzt die alte
   Konfiguration zurück. Eine Mutation der Listen-Stores (`users.ts:31-49`, `hooks.ts:56-80`, `apikeys.ts:30-44`),
   deren Antwort nach `reset()` (Abmelden) ankommt, hängt an den geleerten Store an (`users.ts:33-34`) und erhöht
   `refreshGen`; damit verwirft sie zusätzlich das erste `refresh()` der neuen Sitzung (`users.ts:22`), die Liste
   bleibt bis zum nächsten Laden leer oder zeigt nur die alte Zeile. `save()` nach `reset()` setzt die alte
   Konfiguration in den geleerten Store.
5. **Alte Anfrage beendet neue Sitzung (R-0779).** Bekommt eine Anfrage ein 401, versucht `request()`
   (`client.ts:110-119`) bzw. `requestRaw()` (`:171-179`) einen Refresh und ruft bei Misserfolg `onAuthFailure`; das
   ist `endSession()` (`apps/web/src/lib/stores/auth.ts:100-102`, `:27-44`), das alle Stores leert und
   `authApi.logout()` schickt, dessen Antwort das Refresh-Cookie löscht (`auth.ts:22-24`,
   `apps/web/src/lib/api/auth.ts:16-25`). Kommt das 401 einer Anfrage der alten Sitzung erst nach Abmelden und neuer
   Anmeldung an, beendet es die neue Sitzung. Gelingt der Refresh dagegen mit dem Cookie der neuen Sitzung, wiederholt
   `request()` die alte Anfrage mit dem Token der neuen (`client.ts:112-114`). Beides ist selten (die Anfrage muss
   über Abmelden und Anmelden hinweg offen sein); `login()` wartet schon auf laufende Abmeldungen (`auth.ts:72-78`),
   schützt aber nicht vor einem 401, das danach eintrifft.
6. **Audit-Ansicht ohne `detail` (R-0757).** Die Tabelle (`apps/web/src/pages/Audit.svelte:114-142`) zeigt Zeit,
   Actor, Aktion, Objekt, IP und Status; `detail` liefert `GET /api/audit` schon
   (`apps/server/app/modules/audit/models.py:52`, Typ `apps/web/src/lib/api/types.ts:203`). Was es trägt, sind kurze
   Texte wie geänderte Felder, `ttl=…`, `reason=…`, `enabled=…` (Schreiber in `hooks/router.py`, `users/router.py`,
   `enrollment/router.py`, `provisioning/router.py`).

## Ziel & Nicht-Ziele

Ziele:

- Die Payload-Logik beider Dialoge liegt in reinen Funktionen (`apps/web/src/lib/utils/hookForm.ts`, `userForm.ts`,
  Muster `apps/web/src/lib/routeGuard.ts`) mit vitest; vorher pinnen Komponenten-Tests das heutige Verhalten (T6, T8),
  die nach dem Umbau unverändert grün bleiben (T7, T9).
- Der Benutzerdialog lädt nur `id`, `name`, `hostname` (T10, T11; Variante c, offene Frage 1).
- Eine Fabrik `listStore<T>()` (`apps/web/src/lib/stores/listStore.ts`) trägt den Guard für `users`, `hooks`,
  `apikeys` (T2); vorher pinnt T1 das Verhalten. Danach verwirft sie Antworten von Mutationen nach `reset()` (T3);
  `frp.ts` bekommt dieselbe Regel für `save()` (T4).
- `client.ts` führt eine Sitzungs-Generation: Ein 401 einer Anfrage aus einer früheren Sitzung löst weder Refresh,
  Wiederholung noch `onAuthFailure` aus (T5).
- Ein Helfer `copyToClipboard(text, okKey)` (`apps/web/src/lib/utils/clipboard.ts`) für alle vier Kopier-Knöpfe, ein
  übersetzter Fehlertext (T12–T14; offene Frage 2).
- Toter Code weg (T15–T17); die Audit-Ansicht zeigt `detail` (T18).

Nicht-Ziele:

- `frp.ts` wird kein `listStore`: ein Einzelobjekt mit eigener Maskierung in `save()` (`frp.ts:34-38`); es bekommt in
  T4 nur dieselbe Generationsregel.
- `GET /api/servers` bleibt unverändert: Der Desktop liest dort Verbindungen und `frpTunnels`.
- Antworten (2xx) alter Sitzungen verwirft `client.ts` nicht allgemein: Die Daten-Stores schützen sich über ihre
  Generationen (T3, T4), Seiten werden beim Abmelden ausgehängt. T5 greift nur in den 401-Pfad.
- Die Suche `q` der Audit-Ansicht durchsucht `detail` nicht (Server, `apps/server/app/modules/audit/router.py:53-56`).
- Der Router des Desktops (`apps/desktop/ui/`) ist ein eigenes Paket; die CSS-Klasse `.btn.small` bleibt (rohe
  `<button class="btn small">`, etwa `Audit.svelte:102-103`).
- R-0651 (Server übernimmt `description: null`) baut server-fixes; das Web schickt weiter `null`, T6 pinnt es.
- Keine Zeile fällt weg: Jeder Befund hält am Code; nur Zeilenangaben sind gewandert (R-0722 `UserModal.svelte`
  `:66-99` → `:67-110`, R-0724 `auth.ts:63` → `:104`), und „Enrollment meldet `toast.apikey.copied`“ ist ein falsch
  benannter Schlüssel mit gleichem Text, kein sichtbarer Fehler (geht in T14 mit auf).

## Betroffene Komponenten & Dateien

- **web** (`verify.sh web`): `apps/web/src/lib/stores/{listStore.ts (neu),users.ts,hooks.ts,apikeys.ts,frp.ts,
  frp.test.ts,refreshGuard.test.ts (neu),auth.ts}`, `apps/web/src/lib/api/{client.ts,client.test.ts,servers.ts,
  types.ts}`, `apps/web/src/lib/utils/{hookForm.ts,hookForm.test.ts,userForm.ts,userForm.test.ts,clipboard.ts,
  clipboard.test.ts}` (alle neu), `apps/web/src/modals/{HookModal.svelte,HookModal.test.ts (neu),UserModal.svelte,
  UserModal.test.ts,KeyRevealModal.svelte,WebhookTokenModal.svelte,EnrollTokenModal.svelte,
  FrpConfigPreviewModal.svelte,copyButtons.test.ts (neu)}`, `apps/web/src/lib/router.ts`, `router.test.ts`,
  `apps/web/src/lib/components/ui/Button.svelte`, `apps/web/src/lib/i18n/dictionaries.ts`,
  `apps/web/src/pages/{Audit.svelte,Audit.test.ts (neu)}`, `apps/web/tests/e2e/mocks.ts`.
- **server** (`verify.sh server`, nur Variante c): `apps/server/app/modules/servers/{router.py,schemas.py}`,
  `apps/server/tests/{test_servers_summary.py (neu),openapi.snapshot.json}`.
- **Doku**: `docs/developer/webui.html` + EN, `docs/developer/api-reference.html` + EN (Variante c),
  `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine Migration. Variante c (T10, Kevins Entscheidung): neue Route `GET /api/servers/summary`, Admin
(`get_current_admin` wie `list_servers`), `response_model=list[ServerSummary]` mit `id`, `name`, `hostname`
(`apps/server/app/modules/servers/schemas.py`, Antwortmodell wie `HookResponse` in
`apps/server/app/modules/hooks/schemas.py:57`), Spaltenabfrage `db.query(Server.id, Server.name, Server.hostname)`
sortiert wie `list_servers` (`Server.name, Server.id`), ohne Pagination (der Dialog braucht alle). Die Route steht
vor `get_server` (`router.py:135`), sonst liest FastAPI `summary` als `server_id`. Additiv: `openapi-breaking.sh`
meldet einen neuen Pfad nicht als ERR; `openapi.snapshot.json` wird neu geschrieben. Contract-Dateien:
`servers/router.py`, `servers/schemas.py`, `openapi.snapshot.json`; Web-Typ `ServerSummary` ersetzt `Server`
(`types.ts:82-89`, einziger Nutzer ist der Dialog).

## Externe Integrationen

Keine. Clipboard-API des Browsers wie heute (`navigator.clipboard.writeText`).

## Trade-offs & Alternativen

1. **R-0723.** (a) Vertragsneutral: Liste je Besuch der Benutzerseite cachen. Spart wiederholte Ladevorgänge, nicht
   die Größe einer Ladung, und zeigt einen inzwischen im Desktop angelegten Server erst nach Neuladen der Seite;
   löst also den Befund nicht. (b) Query-Parameter an `GET /api/servers`, der die Form der Antwort wechselt: ein
   Antworttyp je Parameter, für OpenAPI und den Desktop-Client unklar. (c) Eigene Route mit `response_model`
   (Vorschlag der Zeile, empfohlen): klein, typisiert, additiv, Datenminimierung (Benutzernamen, Hosts und Domänen
   der Verbindungen verlassen den Server für diesen Dialog nicht mehr). (d) Zurückstellen: 26 KB gzip bei 500
   Servern sind heute tragbar; der Befund wächst aber mit jeder Verbindung und jedem Tunnel.
2. **Pin-Tests als eigene Tasks** (T1, T6, T8, T13) statt im Umbau: Der Commit auf HEAD-Verhalten beweist „grün
   vorher“ ohne Revert-Probe; der Umbau ändert keine Assertion.
3. **Fix nach dem Umbau** (T3 nach T2): Der Generationsfehler der Listen-Stores wird einmal in `listStore.ts`
   behoben statt dreimal und dann umgebaut. T4 (`frp.ts`) hängt nicht daran.
4. **Generation in `client.ts`** statt in `stores/auth.ts`: Nur der Client sieht, wann eine Anfrage startete. Die
   Generation steigt in `clearTokens()` und in `setAccessToken()`, wenn vorher kein Token gehalten wurde (Anmeldung,
   Wiederherstellung beim Start); ein Refresh mitten in der Sitzung zählt nicht als neue Sitzung (Kontrolltest T5 e).
   Eine alte Anfrage wirft weiter `ApiError(401, 'Session expired')`; ihr `catch` zeigt evtl. einen Toast, beendet
   aber nichts.
5. **Fehlertext beim Kopieren** (offene Frage 2): neuer Schlüssel wie im Desktop (`infra.prov.copyError`,
   `apps/desktop/ui/src/lib/i18n/dictionaries.ts:70`, `:862`) statt `error.generic`, das nur „Fehler“ sagt.

## Risiken & Rollback

- T5 greift in den Auth-Pfad jeder Anfrage. Die bestehenden Tests in `client.test.ts` (Refresh mit Wiederholung,
  Handler bei gescheitertem Refresh, gebündelter Refresh) bleiben unverändert grün; ein Kontrolltest pinnt, dass ein
  Refresh mitten in der Sitzung den Handler weiter auslöst. Rollback: Revert des Task-Commits.
- T2 baut drei Stores um; T1 pinnt jeden Mutationsweg vorher, Mutations-Stichprobe im Probe-Worktree.
- T10 ist eine neue Route im Server: Auth-Gate (`apps/server/tests/test_route_auth_gate.py`) und 401/403-Tests;
  `security` (Risikoliste). Rollback: Revert T11, dann T10; `GET /api/servers` blieb unverändert.
- Merge-Konflikte mit parallelen Vorhaben (siehe Ledger, „Für alle Tasks“): `client.ts`/`client.test.ts`
  (fehlervertrag, auth-sessions), `types.ts`, `mocks.ts`, `openapi.snapshot.json`, `dictionaries.ts`, `webui.html`,
  `api-reference.html`, `betrieb.html`/`operations.html` (audit-coverage ändert die Nachbarzeile `:132`).

## Doku-Impact

T3: ein Satz im Abschnitt Stores von `docs/developer/webui.html` (+ EN) zu `listStore.ts` und den Generationen;
CHANGELOG (Fixed). T4: CHANGELOG (Fixed). T5: ein Satz im Abschnitt API-Wrapper (`webui.html:79` + EN), CHANGELOG
(Fixed). T10: `GET /api/servers/summary` in `docs/developer/api-reference.html:99-103` (+ EN), CHANGELOG (Added).
T14: CHANGELOG (Changed, Fehlertext beim Kopieren übersetzt und einheitlich). T15: Satz zu den Router-Exporten in
`webui.html:60` (+ EN). T18: `docs/admin/betrieb.html:133` und `docs/en/admin/operations.html:92` nennen die
Spalte Detail; CHANGELOG (Changed). Übrige Tasks: keine (intern).

## Offene Fragen

1. **R-0723, neue Route `GET /api/servers/summary` (T10, T11)?** Optionen: (c) neue typisierte Admin-Route;
   (a) vertragsneutraler Cache je Seitenbesuch; (d) zurückstellen. **Empfehlung (c):** einzige Variante, die die
   Ladung verkleinert (Probe: 565 KB → 50 KB roh, 26 KB → 4 KB gzip bei 500 Servern) und Verbindungsdaten aus dem
   Dialog heraushält; additiv, kein ERR in oasdiff. Trade-off: ein Endpunkt mehr, `linux-full` im Sammellauf,
   `security`-Prüfung. Bei (a) entfällt T10 (`[~]`), die Session schreibt T11 auf den Cache um und setzt
   `Heavy: none`; bei (d) entfallen T10 und T11.
2. **Fehlertext beim Kopieren (T12, T14)?** Optionen: neuer Schlüssel `toast.copyFailed` „Kopieren
   fehlgeschlagen“ / „Copy failed“; vorhandenes `error.generic` „Fehler“ / „Error“; festes `'Clipboard error'`.
   **Empfehlung: `toast.copyFailed`** — übersetzt, sagt, was scheiterte, gleicher Text wie im Desktop. Trade-off: ein
   Schlüssel mehr je Sprache. Sichtbar ändert sich nur der Fehlertoast (drei Dialoge zeigten Englisch, einer
   „Fehler“); die Erfolgstexte bleiben.
