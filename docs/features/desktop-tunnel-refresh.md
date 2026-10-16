<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Tunnel übernimmt Änderungen selbst — Spec

Roadmap: R-0402 (BUG), R-0389 (BUG), R-0390 (BUG). Stand: `origin/main@b84b9495`, 2026-10-16.

**Entscheidungen Kevin, 2026-10-16 (Fragerunde):** Der Desktop fragt alle **60 s** ab; ein **404** von
`/api/frp/generate/visitor-bundle` heißt „keine Tunnel“, ohne neuen API-Vertrag; das Restrisiko der
Token-Rotation (Neustart des Desktop-frpc, alle Sitzungen kurz weg) wird hingenommen; ein
`multibox`-Lauf vor dem Merge ist erlaubt. R-0389 und R-0390 werden mit R-0402 geplant, weil der
automatische Neustart ohne sie nach einem Stopp durch den Nutzer wieder anspringen würde.

## Problem / Motivation

Im Feld (Installation v0.45.0, 2026-10-16) ging SSH über einen neu angelegten Tunnel erst nach einem
Neustart der Desktop-App. Im Code sind es drei Lücken:

1. **Bundle und Mappings nur beim Login.** `startIfServerMode` (`apps/desktop/ui/src/lib/stores/tunnel.ts:36`)
   ruft einmal `start_tunnel` (`apps/desktop/src-tauri/src/frpc.rs:344`) und `fetch_tunnels`; aufgerufen
   wird es aus `AppShell.svelte:134`, `SettingsModal.svelte:226` und `stores/settings.ts:113`. Danach fragt
   niemand mehr. Ein Tunnel, der später angelegt, geändert (Secret, Ports, `allowUsers`) oder gelöscht wird,
   und eine Rotation des frps-Tokens erreichen den laufenden Desktop nicht. Die Doku verlangt deshalb
   Handarbeit: „alle Desktop-Visitor das Tunnel-Bundle neu laden“ (`docs/admin/frp-tunnel.html:71`) und
   „danach den Tunnel im Desktop neu starten“ (`:92`).
2. **frpc gibt beim ersten Fehlschlag auf.** Die Visitor-TOML setzt kein `loginFailExit`; frp beendet
   sich dann nach dem ersten gescheiterten Login (Default `true`, siehe Externe Integrationen). Ist frps
   beim Login des Admins nicht erreichbar oder startet gerade neu, endet frpc; `markTerminated`
   (`tunnel.ts:72`) setzt nur „disconnected“, niemand startet neu.
3. **Fehlermeldung ohne Tunnel.** Sieht der Nutzer keinen STCP-Tunnel, antwortet der Server mit 404
   (`apps/server/app/modules/frp/generate_router.py:150`, ohne FRP-Config ebenso `:35`);
   `fetch_visitor_bundle` (`frpc.rs:90`) macht daraus einen Fehler, der bei jedem Login als
   Tunnel-Fehler erscheint.

Dazu zwei Ereignis-Lücken, die ein automatischer Neustart verschärfen würde:

- **R-0389:** `stop_frpc` (`frpc.rs:323`) erhöht die Generation nicht. Das späte `Terminated` des
  gestoppten Prozesses gilt als laufende Generation, `frpc-terminated` geht ans UI (`frpc.rs:303`) und
  setzt die Anzeige von „idle“ auf „disconnected“. Mit Auto-Neustart würde es frpc nach einem bewussten
  Stopp wieder starten.
- **R-0390:** `CommandEvent::Error` sendet `frpc-error` ohne Generationsprüfung (`frpc.rs:306-308`). Ob ein
  getöteter Sidecar überhaupt ein `Error` liefert, ist unbelegt; die Prüfung kostet nichts.

## Ziel & Nicht-Ziele

**Ziele**
- Jede Änderung an den für den Nutzer sichtbaren STCP-Tunneln und an der FRP-Server-Config erreicht den
  laufenden Desktop **innerhalb von 60 s**, nach eigenem Anlegen, Ändern oder Löschen im Desktop sofort.
- **Nur Visitors geändert** (neu, weg, Secret, Port, `serverUser`): frpc übernimmt per **Hot-Reload**;
  unveränderte Visitors und ihre offenen Verbindungen bleiben stehen.
- **Common geändert** (`serverAddr`, `serverPort`, `user`, `auth.*`, `transport.*`, also auch eine
  Token-Rotation): frpc wird **neu gestartet** — frp übernimmt diese Werte nur beim Start.
- **Keine sichtbaren Tunnel** (404): frpc wird still gestoppt, Anzeige „idle“, keine Fehlermeldung.
- **frps nicht erreichbar oder neu gestartet:** frpc versucht es selbst weiter (`loginFailExit = false`).
- **frpc endet unerwartet** (laufende Generation, kein Stopp durch den Nutzer): Neustart mit wachsender
  Pause 5 s → 10 s → 20 s → 40 s → 60 s (Deckel), zurückgesetzt nach einem erfolgreichen Start.
- **Netzwerkfehler, 401 nach gescheitertem Refresh, 5xx:** der laufende Tunnel bleibt unangetastet; der
  nächste Takt versucht es neu.
- Stopp durch den Nutzer, Abmelden, Wechsel in den lokalen oder Sync-Modus: kein Neustart, kein Takt.
- **Knopf „Neu verbinden“** an der Tunnel-Anzeige (Kevin 2026-10-16), nur sichtbar, solange die Anzeige
  „getrennt“ ist: verwirft einen geplanten Backoff-Neustart, setzt die Pause auf 5 s zurück und stößt sofort
  einen Abgleich an. Bei verbundenem Tunnel gibt es ihn nicht, damit kein Klick laufende Sitzungen trennt.

**Nicht-Ziele (YAGNI)**
- Anstoß über den Benachrichtigungs-Stream (SSE). Heute ungeeignet: `frp.tunnel.created` ist `info`, das
  Standard-Abo der Admins `warning+`; Zuweisungen, Token-Rotation und Umbenennungen erzeugen kein
  Ereignis. Erst nötig, wenn 60 s zu langsam sind.
- Agent-Seite (Vorhaben agent-frpc-sync) und frps selbst (Vorhaben frps-supervisor).
- Übernahme eines erneuerten Geräte-Zertifikats in den laufenden frpc.
- HTTPS-Tunnel: sie haben keinen Visitor; ihre Mappings kommen weiter über `fetch_tunnels`.

## Betroffene Komponenten & Dateien

**Desktop-Backend (Rust)**
- `apps/desktop/src-tauri/src/frpc.rs` — `FrpcProcess` (`:43`): Generation auch beim Stopp (R-0389),
  Fehlerereignis nach Generation (R-0390), dazu die zuletzt angewandte Server-TOML und die Zugangsdaten
  der lokalen Admin-API; `fetch_visitor_bundle` (`:90`) liefert bei 404 „keine Tunnel“; neue reine
  Entscheidungsfunktion (Start / Neustart / Reload / unverändert) über die geparste TOML; lokaler Kopf
  (`loginFailExit`, `webServer.*`) **nach** `validate_visitor_toml` (`:151`) vorangestellt; Reload per
  `GET /api/reload`; `start_tunnel` (`:344`) wird zum idempotenten Abgleich.
- `apps/desktop/src-tauri/src/commands.rs` — Command `refresh_tunnel` (neben `start_tunnel` `:307`).
- `apps/desktop/src-tauri/src/main.rs` — Registrierung (`:103-104`).
- `apps/desktop/src-tauri/src/models.rs` — `TunnelStatus` (`:155`) um die Namen der aktiven Visitors.
- `apps/desktop/src-tauri/src/auth.rs` — `authenticated_get` sendet nach dem Pin das Access-Token der
  aktiven Sitzung aus dem Keyring, für alle Aufrufer (T5), siehe Trade-offs.

**Desktop-UI (Svelte/TS)**
- `apps/desktop/ui/src/lib/stores/tunnel.ts` — Takt (aktivieren/deaktivieren nach dem Muster von
  `stores/notifications.ts:102-152`), Single-Flight, Leerlauf ohne Tunnel, Neustart mit Backoff.
- `apps/desktop/ui/src/lib/bridge/index.ts` (`:213`), `lib/bridge/types.ts` (`:67`) — `refreshTunnel`, Typen.
- `apps/desktop/ui/src/components/AppShell.svelte` (`:134`, `:141-142`), `components/SettingsModal.svelte`
  (`:226`), `lib/stores/settings.ts` (`:113`) — Aufrufer von `startIfServerMode`.
- `apps/desktop/ui/src/components/infra/TunnelModal.svelte` (`:76-78`, `:100-106`) — sofort abfragen nach
  Anlegen, Ändern, Löschen.
- `apps/desktop/ui/src/components/TunnelIndicator.svelte` (`:15-25`, `:28-33`) — Knopf „Neu verbinden“ bei
  getrenntem Tunnel; Texte in `apps/desktop/ui/src/lib/i18n/dictionaries.ts` (`:191`, `:815`).

**Live-E2E:** `apps/desktop/e2e/test/specs/tunnel-start.live.js` (erweitert, läuft über
`scripts/tests/desktop_e2e_tunnel.sh`, das unverändert bleibt).

**Server:** keine Änderung.

## Datenmodell / API / Migrationen

- **Server-API:** keine Änderung, keine Migration. `GET /api/frp/generate/visitor-bundle` behält seine
  Antworten; der Desktop **liest** 404 neu als „keine Tunnel“ (beide 404-Fälle, `generate_router.py:35`
  und `:150`, bedeuten genau das). 401 behandelt `authenticated_get` wie heute (`auth.rs:183`), jede andere
  Nicht-2xx-Antwort ist ein Fehler, der den Tunnel stehen lässt.
- **Tauri-IPC (desktop-intern, Rust ↔ UI in einem Build):** neuer Command `refresh_tunnel(serverUrl,
  token, username)` → `{ status: TunnelStatus, outcome: "started" | "restarted" | "reloaded" |
  "unchanged" | "stopped" }`; `TunnelStatus` bekommt `visitors: string[]` (Namen der angewandten
  Visitors). `start_tunnel` bleibt und läuft über denselben Abgleich. Kein Drift zu Server, Web oder Agent.
- **Lokale Dateien:** `visitor.toml` (0600, App-Data) trägt zusätzlich den lokalen Kopf mit dem
  Passwort der Admin-API.

## Externe Integrationen

frp **v0.69.1** (gebündelter Sidecar, `.github/workflows/ci.yml:24`). Quellen unter
`https://github.com/fatedier/frp/blob/v0.69.1/…`, gegengeprüft am 2026-10-16:

- **Hot-Reload nur für Proxies/Visitors.** README: „Then run command `frpc reload -c ./frpc.toml` … Note that
  global client parameters won't be modified except 'start'.“ `client/service.go:131`: „It can be updated
  by /api/reload without mutating startup-only common behavior.“
- **Was der Reload anfasst.** `client/visitor/visitor_manager.go` `UpdateAll`: Vergleich per
  `reflect.DeepEqual`; geänderte oder entfernte Visitors werden geschlossen, neue gestartet, unveränderte
  bleiben laufen. `client/visitor/visitor.go:142-152` (`BaseVisitor.Close`) schließt nur den Listener.
  **Nicht Ende-zu-Ende verifiziert:** dass eine offene Verbindung über einen *geänderten* Visitor den
  Reload überlebt; für *unveränderte* Visitors folgt es direkt aus dem Code (sie werden nicht angefasst).
- **Admin-API.** `client/api_router.go`: `GET /api/reload`, `POST /api/stop`, `GET/PUT /api/config` hinter
  `AuthMiddleware`, `/healthz` ohne Auth. `pkg/util/net/http.go:47-51`: ohne Benutzer **und** Passwort ist
  die API offen. `client/http/controller.go:71-82`: `Reload` → `ReloadFromFile` (liest die `-c`-Datei neu).
  `client/service.go:186-192`: lässt sich der Admin-Listener nicht binden, startet frpc nicht.
- **`loginFailExit`.** `pkg/config/v1/client.go:54-57` und `:88`: Default `true`. `client/service.go:258-263`:
  mit `true` endet frpc nach dem ersten gescheiterten Login. `client/service.go:273-301`
  (`keepControllerWorking`): nach dem ersten erfolgreichen Login verbindet frpc **immer** selbst neu
  (`loopLoginUntilSuccess(20s, false)`, drei schnelle Versuche, dann bis 20 s).

**Nicht verifiziert:** ob die Windows-Firewall bei einem Listener auf 127.0.0.1 nachfragt.

## Abläufe

**Abgleich (`refresh_tunnel`, serialisiert über eine Async-Sperre im Backend):**

| Bundle | frpc | Common gleich? | Visitors gleich? | Aktion | Outcome |
|---|---|---|---|---|---|
| Fehler (Netz, 5xx, 401 nach Refresh) | egal | — | — | nichts ändern, Fehler an das UI | Fehler |
| 404 | läuft | — | — | stoppen (Generation +1) | `stopped` |
| 404 | läuft nicht | — | — | nichts | `stopped` |
| TOML | läuft nicht | — | — | Kopf neu (Port, Passwort), schreiben, starten | `started` |
| TOML | läuft | nein | — | stoppen, Kopf neu, schreiben, starten | `restarted` |
| TOML | läuft | ja | nein | mit **altem** Kopf schreiben, `GET /api/reload`; scheitert er → Neustart | `reloaded` |
| TOML | läuft | ja | ja | nichts | `unchanged` |

„Common“ ist die Wurzeltabelle der **Server-TOML** ohne `visitors`, „Visitors“ das Array `visitors`, beides
als geparstes `toml::Value` verglichen (kein Textvergleich). Der lokale Kopf:

```toml
loginFailExit = false
webServer.addr = "127.0.0.1"
webServer.port = <freier Port>
webServer.user = "adminhelper"
webServer.password = "<32 Zufallsbytes, hex>"
```

Er wird **nach** `validate_visitor_toml` vor die Server-TOML gestellt (vor jeder Tabellen-Überschrift, also
in der Wurzel). Die Allow-List bleibt unverändert: ein Server, der selbst `webServer` oder `loginFailExit`
schickt, wird weiter abgewiesen. Den Port wählt das Backend per Bind auf `127.0.0.1:0`; ist er beim Start
belegt, endet frpc, und der Neustart mit Backoff wählt einen neuen. Zufall über den vorhandenen
ring-Provider (`crate::tofu::ring_provider()`), keine neue Abhängigkeit. Der Reload-Aufruf geht über
einen eigenen reqwest-Client ohne Proxy (`no_proxy`), mit Basic-Auth und kurzem Timeout.

**UI-Takt (`stores/tunnel.ts`):**
- `startIfServerMode()` beim Eintritt in den Server-Modus mit Session: sofort ein Abgleich, dann alle 60 s;
  `stop()` beim Abmelden (Kopfzeile über `signOut()`, T13; Einstellungen über `serverLogout()`) und beim
  Moduswechsel, mit Generationszähler wie `notifications.ts:100` gegen überholte Aktivierungen. Endet die
  Sitzung ohne `stop()`, beendet der nächste Lauf den Takt selbst.
- **Single-Flight:** läuft ein Abgleich, wird der nächste Takt übersprungen. `refreshNow()` (aus
  `TunnelModal`) reiht während eines laufenden Abgleichs genau einen Folgelauf ein (weitere Aufrufe teilen
  ihn, `stop()` oder eine neue Aktivierung verwerfen ihn), damit eine gespeicherte Änderung sofort ankommt.
- Nach jedem Abgleich werden die Mappings (`fetch_tunnels`) neu geladen, damit auch HTTPS-Tunnel aktuell
  sind; ein Fehler dabei lässt die alten Mappings stehen.
- `stopped` → Anzeige „idle“, Mappings leer, keine Meldung. Fehler → Anzeige bleibt, höchstens eine Meldung
  je Fehlerserie.
- `frpc-terminated` (nur noch laufende Generation) während der Takt aktiv ist → „disconnected“ und Neustart
  mit Backoff (5–60 s; eine Serie endet erst, wenn frpc einen ganzen Takt hielt; eine Meldung je Serie);
  `stop()` beendet Takt und Backoff.

## Trade-offs & Alternativen

1. **Abfrage alle 60 s vs. SSE-Anstoß.** Die Abfrage erfasst jeden Fall (auch Zuweisungen und
   Token-Rotation) mit einer Stelle; SSE bräuchte neue Ereignisse an vielen Server-Stellen. Kosten: zwei GETs
   je Minute und Nutzer. **Empfehlung: Abfrage** (Kevin, 2026-10-16).
2. **Reload vs. immer Neustart.** Neustart wäre einfacher, beendet aber bei jeder Tunnel-Änderung alle
   Sitzungen des Admins. **Empfehlung: Reload für Visitors, Neustart nur für Common.** Preis: ein lokaler
   HTTP-Listener mit Passwort.
3. **Token für den Takt.** Das UI hält das Access-Token vom Login; `authenticated_get` erneuert es bei 401
   transparent und speichert das neue nur im Keyring (`auth.rs:183-203`). Nach acht Stunden liefe sonst
   **jeder Takt** in einen Refresh mit Rotation; zwei gleichzeitige Refreshes mit demselben Refresh-Token
   lösen die Reuse-Erkennung aus und melden den Nutzer ab. **Gewählt (T5):** `authenticated_get` sendet
   nach dem Pin das Access-Token der aktiven Sitzung aus dem Keyring, für alle Aufrufer (Visitor-Bundle,
   Mappings, Verbindungs-Sync). Seit T15 liest es die Sitzung einmal als Schnappschuss (Ziel-Pin, Access- und
   Refresh-Token) und erneuert bzw. speichert nur, solange der Keyring noch dieselbe Sitzung hält; ohne
   Sitzung wird nichts gesendet. Die Abgleiche laufen nacheinander.
   Berührt `auth.rs` (Risikopfad).
4. **Vergleich per TOML-Parser vs. Textvergleich.** `toml` ist schon Abhängigkeit (`Cargo.toml:57`); der
   Parser macht den Vergleich unabhängig von Formatierung. **Empfehlung: Parser.**
5. **Lokaler Kopf im Server-Generator vs. im Desktop.** Im Desktop: der Server kennt Port und Passwort nicht
   und darf beides nie setzen. **Empfehlung: Desktop.**

## Risiken & Rollback

- **Lokale Admin-API:** jeder lokale Prozess erreicht 127.0.0.1. Schutz: Basic-Auth mit 32 Zufallsbytes, nur
  in `visitor.toml` (0600) und im Speicher; Browser-Angriffe (DNS-Rebinding, CSRF) scheitern am Passwort,
  `/healthz` verrät nichts. Ohne Passwort wäre `GET /api/config` (Token, alle `secretKey`) offen — der Kopf
  setzt es deshalb immer, ein Test sichert das ab.
- **Neustart-Schleife** bei dauerhaft kaputter Config: Backoff bis 60 s, eine Meldung je Serie.
- **Token-Rotation:** Neustart des Desktop-frpc nach höchstens 60 s, offene Sitzungen brechen ab (von Kevin
  hingenommen; die Mitteilung an Betroffene kommt aus dem Vorhaben frps-supervisor).
- **Rollback:** Revert des Merge-Commits; keine Daten, keine Migration, keine Server-Änderung.

## Doku-Impact

Sichtbare Änderung, DE + EN: `docs/admin/frp-tunnel.html` (`:71`, `:92`, EN gleiche Zeilen: Desktop
übernimmt Änderungen selbst innerhalb von 60 s, bei Token-Rotation mit kurzem Abbruch),
`docs/developer/desktop.html` und `docs/en/developer/desktop.html` (`:145-149`: Abgleich, Reload/Neustart,
lokale Admin-API, Backoff), Knopf „Neu verbinden“ in der Fehlerbehebung von `frp-tunnel.html` (DE `:113-114`,
EN an der entsprechenden Stelle), `CHANGELOG.md`.

## Offene Fragen

Keine. Entschieden von Kevin am 2026-10-16:

1. **Scenario-Flags:** `--agents 1 --tunnel --desktop` reicht. Die Desktop-Box dort fährt nur `server-crud`
   und `monitoring-check` (`scripts/tests/multibox.sh`, `DESK_SPECS`), den GUI-Visitor prüft der Lauf nicht;
   den Beweis für den Desktop trägt das Live-E2E (T9).
2. **Sitzungserhalt beim Reload Ende-zu-Ende** wird hier nicht geprüft; für unveränderte Visitors folgt er aus
   dem frp-Code, den `scenario`-Beweis für eine offene Sitzung liefert agent-frpc-sync.
3. **Knopf „Neu verbinden“:** ja, als eigene Tasks (T10, T11), siehe Ziele.
