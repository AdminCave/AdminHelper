<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Nicht-Admins: Tunnel-Zuordnungen für den Desktop, Hinweisseite im Web-Panel

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/non-admin-access.md`. Roadmap R-0484 (T1–T4), R-0721 (T5, T6).

## Problem / Motivation

1. **Nicht-Admins bekommen keine Tunnel-Zuordnungen (R-0484).** `GET /api/frp/tunnels`
   (`apps/server/app/modules/frp/tunnel_router.py:25-38`) hängt an `get_current_admin` (`:30`), das jeden
   Nicht-Admin mit `403 Admin-Rechte erforderlich` abweist (`apps/server/app/core/auth.py:234-239`). Der Desktop holt
   die Zuordnungen für jeden Benutzer dort (`apps/desktop/src-tauri/src/tunnel.rs:43-63`). Bei 401/403 verwirft er
   die gehaltenen (`:46-53`) und meldet einen Fehler (`:54-58`); der Tunnel-Store behält dann die bisherigen, also
   leeren Zuordnungen (`apps/desktop/ui/src/lib/stores/tunnel.ts:218-222`). Folgen für einen Nicht-Admin:
   - `resolve_connection` (`tunnel.rs:73-127`) hat für ihn nur die wörtliche Regel aus R-0430: Ziel `127.0.0.1`
     oder `localhost` am Server-Port eines Visitors. Hat ein Admin eine Verbindung mit einem Tunnel verknüpft
     (`FrpTunnel.connection_id`) und hat ihr Ziel nicht diese Form, öffnet sie ihr gespeichertes Ziel statt des
     Tunnels. R-0430 hat diese Lücke ausdrücklich offen gelassen (`docs/features/desktop-session-ports.md:59`).
   - Die Verbindungsliste zeigt an seinen Verbindungen keinen Tunnel-Namen
     (`apps/desktop/ui/src/pages/Connections.svelte:75-78`).

   Beleg (Probe an `origin/main@b25c65a6`, Python 3.13, FastAPI 0.141.1): `get_current_admin` mit einem
   Stand-in-Benutzer mit `is_admin=False` wirft dreimal identisch `HTTPException(403, "Admin-Rechte erforderlich")`.

   **Korrektur am Befund der Zeile:** Die Zeile nennt auch `frp/router.py:25` („include mit `_admin`“). Dieses
   `_admin` ist `require_scope(SCOPE_ACCESS)` (`apps/server/app/modules/frp/router.py:20`), also der mTLS-Scope aller
   Menschen („humans: desktop / browser“, `apps/server/app/core/identity.py:43`), keine Admin-Prüfung. Für
   Nicht-Admins gibt es nur ein Tor, `tunnel_router.py:30`; `router.py` bleibt unverändert.

2. **Die Zuordnung Benutzer → Server → Tunnel gibt es schon.** Sie läuft über `User.servers` mit der Tabelle
   `user_servers` (`apps/server/app/modules/users/models.py:11-16`, `:46`). Schon heute trennt sie Nicht-Admins an
   drei Stellen:
   - Visitor-TOML und Visitor-Bundle über `_visible_stcp_tunnels`
     (`apps/server/app/modules/frp/generate_router.py:40-61`, genutzt von `:106-133` und `:136-158`).
   - Verbindungen über `_scope_connections` (`apps/server/app/modules/connections/router.py:37-52`).
   - `GET /api/users/me/servers` (`apps/server/app/modules/users/router.py:242-244`).

   Über das Visitor-Bundle bekommt ein Nicht-Admin schon heute zu jedem freigegebenen STCP-Tunnel seiner Server den
   Namen, den Visitor-Port und das Secret. Der Fix braucht weder ein neues Datenmodell noch eine Migration.

3. **Im Web-Panel landet ein Nicht-Admin auf einer veralteten deutschen Seite (R-0721).**
   - Alle fünf Routen sind `adminOnly` (`apps/web/src/routes.ts:14-18`); alles andere fällt auf `'*'` =
     `Placeholder.svelte` (`:19`).
   - `resolveRoute` gibt einem Nicht-Admin auf einer Admin-Route ebenfalls `'*'` (`apps/web/src/lib/routeGuard.ts:27`).
     Nach dem Login führt `apps/web/src/App.svelte:27` nach `#/users`.
   - Die Seite sagt fest auf Deutsch „Nicht verfuegbar“, „Wird in einer spaeteren Phase migriert.“ und „Diese Seite
     ist noch nicht auf Svelte portiert.“ (`apps/web/src/pages/Placeholder.svelte:14-19`).
   - Die Seitenleiste ist leer (`apps/web/src/lib/components/layout/Sidebar.svelte:56`).

   Ein Admin auf einer unbekannten Route sieht dieselbe Seite. Kevin hat am 2026-10-21 entschieden: eine übersetzte
   Hinweisseite „Web-Panel nur für Admins, bitte den Desktop nutzen“.

## Ziel & Nicht-Ziele

Ziel:
- Ein Nicht-Admin liest die Tunnel-Zuordnungen, die sein Desktop braucht, und nur die seiner zugewiesenen Server
  (T2). Den Weg wählt Kevin (Offene Frage 1).
- Vor dem Fix halten Tests fest, was heute gilt und bleiben soll (T1): An den übrigen Tunnel-Routen darf ein
  Nicht-Admin nichts. Ein Admin bekommt aus der Liste alle Tunnel in voller, maskierter Form.
- Kommentare und Doku, die „nur Admins lesen Zuordnungen“ sagen, folgen dem Fix (T3, T4).
- Ein Nicht-Admin sieht im Web-Panel eine übersetzte Hinweisseite statt der Platzhalterseite (T5).

Nicht-Ziele:
- Unverändert bleiben:
  - `frp/router.py` (siehe Korrektur oben).
  - Anlegen, Ändern, Lesen per ID und Löschen von Tunneln: bleiben admin-only, T1 pinnt das.
  - `GET /api/servers`: admin-only, `apps/server/app/modules/servers/router.py:89-93`.
  - Visitor-TOML, Provisionierung und der FRP-Datenpfad.
- Keine Web-Seiten für Nicht-Admins: Das Web-Panel bleibt Instanz-Verwaltung (`docs/developer/webui.html:34`).
- Keine Weiterleitung nach dem Login: `App.svelte` bleibt, auch weil auth-sessions die Datei ändert.
- Kein neues Rollen- oder Zuordnungsmodell.
- Kein Befund dieser Zeilen fällt weg. Die Korrektur zu `frp/router.py:25` ändert nur den Ort des Fixes.

## Betroffene Komponenten & Dateien

| Komponente | Dateien | Task |
|---|---|---|
| server | neu `apps/server/tests/test_frp_tunnel_access.py` | T1, T2 |
| server | `apps/server/app/modules/frp/tunnel_router.py` | T2 |
| desktop-rs | `apps/desktop/src-tauri/src/tunnel.rs`, `apps/desktop/src-tauri/src/connection/mod.rs` (Kommentare; unter Variante B der Abruf) | T3 |
| desktop-ui | `apps/desktop/ui/src/lib/stores/connectFlow.ts`, `connectFlow.test.ts` (Kommentare) | T4 |
| web | `apps/web/src/pages/Placeholder.svelte`, `apps/web/src/lib/i18n/dictionaries.ts`, neu `apps/web/src/pages/Placeholder.test.ts`, `apps/web/tests/e2e/authz.spec.ts` | T5, T6 |
| docs | `docs/developer/api-reference.html` (T2), `docs/developer/desktop.html` (T3), `docs/admin/frp-tunnel.html` (T4), `docs/admin/benutzer.html` (T5), jeweils mit EN; `CHANGELOG.md` (T2, T5, T6) | |

Risikopfade (`scripts/dev/review-risk.txt`): `apps/server/app/modules/frp/*` (`:44`) und
`apps/desktop/src-tauri/src/tunnel.rs` (`:48`). T2 ändert die Autorisierung einer Route, T3 berührt `tunnel.rs`.

## Datenmodell / API / Migrationen

- Keine Migration, kein neues Modell.
- **Variante A** (Empfehlung): `GET /api/frp/tunnels` hängt an `get_current_user` statt an `get_current_admin`.
  - Admin: unverändert.
  - Nicht-Admin: `200` mit den freigegebenen Tunneln seiner zugewiesenen Server, je mit genau den zehn Feldern, die
    der Desktop liest. Ohne Zuordnung bekommt er `[]`.
  - Das OpenAPI-Dokument bleibt gleich:
    - Das Antwortschema ist heute `{}`, die Route hat kein `response_model`.
    - Probe an `origin/main@b25c65a6`: Zwei Minimal-Apps, deren Route an `get_current_admin` bzw. an
      `get_current_user` hängt, erzeugen ein identisches `openapi()`.
    - Voraussetzung: Die Route bekommt keinen Docstring, denn er würde ihre `description`. Das Warum steht als
      `#`-Kommentar.
  - `oasdiff` meldet nichts.
- **Variante B:** ein neuer Pfad, z. B. `GET /api/frp/mappings`, für jeden Benutzer mit der schmalen Form;
  `/api/frp/tunnels` bleibt admin-only. Der Snapshot `apps/server/tests/openapi.snapshot.json` bekommt einen Pfad
  (additiv, kein `oasdiff`-ERR).
- Die übrigen Tunnel-Routen bleiben admin-only (`tunnel_router.py:66-71`, `:152-153`, `:160-166`, `:259-264`).

## Externe Integrationen

- Tauri-IPC `fetch_tunnels` (`apps/desktop/src-tauri/src/commands.rs:500-505`) bleibt unter Variante A unverändert.
- Der Rust-Typ `TunnelMapping` (`apps/desktop/src-tauri/src/tunnel.rs:16-29`) liest zehn Felder in camelCase:
  `id, serverId, tunnelType, protocol, localPort, visitorPort, customDomains, connectionId, enabled, name`.
  - Er hat kein `deny_unknown_fields`, ein Admin bekommt also weiter die volle Form.
  - `local_port: u16` ist Pflicht. Ohne `localPort` scheitert die Deserialisierung in jedem ausgelieferten Desktop,
    das Feld bleibt also in der schmalen Form.
  - Der TS-Spiegel ist `apps/desktop/ui/src/lib/bridge/types.ts:109-120`.
- Die volle Form (`FrpTunnel`) liest im Desktop nur `TunnelsTab.svelte` (`apps/desktop/ui/src/lib/api/frp.ts:22-23`).
  Der Tab ist nur über die Server-Details erreichbar, und die brauchen das admin-only `GET /api/servers`.
- FRP, VictoriaMetrics und Proxmox berührt das Vorhaben nicht.

## Trade-offs & Alternativen

**R-0484, der Weg (Kevin: „eigener Endpunkt oder Rollenprüfung“, 2026-10-18):**

| | A: Filter im bestehenden Endpunkt (Rollenprüfung) | B: eigener Endpunkt |
|---|---|---|
| Server | `list_tunnels` mit Zweig für Nicht-Admins | neue Route, `list_tunnels` bleibt |
| Desktop | keine Code-Änderung; jede ausgelieferte Version löst danach auf | `fetch_tunnels` auf den neuen Pfad, Rückfall bei `404` auf alten Servern; alte Desktops bleiben für Nicht-Admins ohne Zuordnung |
| Vertrag | OpenAPI gleich; die Antwortform hängt an der Rolle | additiv; je Endpunkt eine Form |
| Risikopfade | `frp/*` | `frp/*` und `tunnel.rs` |
| Muster im Code | wie `_visible_stcp_tunnels`, `_scope_connections` | wie `/api/users/me/servers` |

Unter B nicht `/api/users/me/tunnels`: Das berührte `users/router.py`, das audit-coverage gerade ändert.

**Datenumfang für Nicht-Admins:**
- **D1:** alle Tunnel der zugewiesenen Server.
- **D2 (Empfehlung):** nur die freigegebenen (`enabled`). Der Desktop nutzt gesperrte ohnehin nicht
  (`tunnel.rs:129-136`, `Connections.svelte:76`).
- **D3:** nur Tunnel, deren `connectionId` eine für ihn sichtbare Verbindung ist. Verworfen: eine verdeckte zweite
  Regel ohne Gewinn, denn die automatischen Verbindungen liegen ohnehin auf dem Server des Tunnels
  (`apps/server/app/modules/frp/_helpers.py`, `create_auto_connection`).

Die Query-Parameter `server_id` und `frp_config_id` grenzen für einen Nicht-Admin nur weiter ein. Ein fremder Server
ergibt `[]`.

**Felder für Nicht-Admins:**
- **F1:** die volle maskierte Form (16 Felder).
- **F2 (Empfehlung):** genau die zehn Felder von `TunnelMapping`, als feste Liste im Server. Verborgen bleiben
  `frpConfigId`, `localIp`, `secretKey`, `extraConfig`, `tags` und `createdAt`.
- **F3:** F2 ohne `localPort`. Verworfen: bricht die Deserialisierung aller ausgelieferten Desktops (siehe oben).

Ein Paritätstest liest die Felder von `TunnelMapping` aus `tunnel.rs` und vergleicht sie mit der Liste im Server
(Muster: `apps/server/tests/test_event_whitelist.py:44`).

**Empfehlung A + D2 + F2**, nach dem Prinzip der geringsten Rechte:
- Ein Nicht-Admin sieht nur, was sein Desktop liest, und nur zu Servern, die ihm ein Admin zugewiesen hat. Das ist
  fast eine Teilmenge dessen, was ihm das Visitor-Bundle schon gibt.
- Neu sind nur `localPort` (der Dienst-Port auf dem Zielserver, etwa 22 oder 3389), die HTTPS-Tunnel mit ihrer
  Domain (die automatische HTTPS-Verbindung trägt sie schon in ihrer `url`) und `connectionId`.
- A heilt jede ausgelieferte Desktop-Version ohne Release und ohne Desktop-Code.
- Preis: Die Antwortform hängt an der Rolle. Das steht in der API-Referenz, und die Tests pinnen beide Formen.

**Randfall:** Ein Tunnel auf einem zugewiesenen Server, dessen `connectionId` auf eine Verbindung eines nicht
zugewiesenen Servers zeigt, verrät dem Nicht-Admin nur deren UUID, nicht die Verbindung. Kein Handlungsbedarf.

**R-0721:** Die Hinweisseite entsteht als Zweig in `Placeholder.svelte`: Ein Nicht-Admin sieht den Hinweis, ein
Admin auf einer unbekannten Route etwas anderes (Offene Frage 2).
- Der Dateiname bleibt, denn `docs/developer/webui.html:48` nennt ihn.
- `App.svelte` bleibt unverändert. Der Nicht-Admin landet nach dem Login weiter auf `#/users` und sieht dort den
  Hinweis.
- Verworfen: Nicht-Admins schon im Login abweisen. Das bräuchte eine Server-Änderung oder eine zweite Rollenprüfung
  im Client und nähme ihnen das Abmelden und die Sprachwahl in der Seitenleiste.

## Risiken & Rollback

- **Erweiterte Leserechte (T2).** Ein Fehler im Filter zeigte fremde Tunnel. Dagegen stehen Tests:
  - Ein Nicht-Admin mit einem Server sieht genau dessen freigegebene Tunnel.
  - Ohne Zuordnung bekommt er `[]`.
  - Query-Parameter grenzen nur ein.
  - Er bekommt kein Secret und kein Feld außerhalb der Liste.
  - Die übrigen Routen antworten `403` (T1).

  T2 prüft zusätzlich `security`.
- **Rollenabhängige Form (A).** Ein späterer Client, der als Nicht-Admin die volle Form erwartet, bekäme sie nicht.
  Die API-Referenz nennt beide Formen.
- **Parallele Vorhaben.** Gemeinsame Dateien stehen im Bericht an die Session:
  - `CHANGELOG.md`, `docs/developer/api-reference.html` und `dictionaries.ts` mit server-hardening, audit-coverage
    und auth-sessions.
  - `connectFlow.ts`, `connectFlow.test.ts` und `frp-tunnel.html` mit desktop-ui-fixes: andere Hunks, aber
    `frp-tunnel.html:105` grenzt an `:106`.
  - `desktop.html` mit desktop-hardening-2: andere Hunks, `:268` grenzt an `:267`.
- **Rollback:**
  - T2 zurücknehmen stellt das heutige `403` wieder her. Der Desktop behandelt das wie heute: Zuordnungen leer,
    wörtliche Auflösung.
  - T5 zurücknehmen bringt die alte Seite zurück.
  - Keine Daten, keine Migration.

## Doku-Impact

- `docs/developer/api-reference.html:140` und `docs/en/developer/api-reference.html:140`: wer was aus
  `GET /api/frp/tunnels` liest (T2).
- `docs/developer/desktop.html:261`, `:267` und EN `:261`, `:267`: „nur Admins dürfen sie lesen“ bzw. „für
  Nicht-Admins leer“ wird zur Zuordnung über die zugewiesenen Server (T3).
- `docs/admin/frp-tunnel.html:106` und `docs/en/admin/frp-tunnel.html:106`: „eine von Hand mit dem Tunnel verknüpfte
  nur für Admins, denn nur sie lesen die Tunnel-Zuordnungen“ wird „für Benutzer, denen der Server zugewiesen ist“
  (T4).
- `docs/admin/benutzer.html:47` und `docs/en/admin/users.html:41`: Die Rolle `user` sieht im Web-Panel nur den
  Hinweis auf den Desktop-Client (T5).
- `CHANGELOG.md`: Fixed (T2) und Changed (T5, T6).

## Offene Fragen

1. **R-0484: Welcher Weg, welcher Umfang, welche Felder?** (T2, T3, T4)
   - Optionen:
     - A: Filter im bestehenden `GET /api/frp/tunnels`.
     - B: eigener Endpunkt, z. B. `GET /api/frp/mappings`.
     - Umfang D1 (alle Tunnel der zugewiesenen Server), D2 (nur freigegebene) oder D3 (nur verknüpfte).
     - Felder F1 (volle maskierte Form) oder F2 (die zehn Felder von `TunnelMapping`).
   - **Empfehlung A + D2 + F2:**
     - geringste Rechte: nur was der Desktop liest, nur zu zugewiesenen Servern;
     - wirkt für jeden ausgelieferten Desktop;
     - kein OpenAPI-Diff, kein Desktop-Code.
   - Trade-off: Die Antwortform hängt an der Rolle. B hielte den Admin-Endpunkt streng admin-only, kostet aber eine
     Desktop-Änderung im Risikopfad `tunnel.rs` und hilft alten Desktops nicht.
   - Unter B schreibt die Session T2 und T3 um: T3 bekommt den Abruf mit Rückfall bei `404`.
2. **Was sieht ein Admin auf einer unbekannten Web-Route?** (T6)
   - Optionen:
     - (a) übersetzt „Seite nicht gefunden“ mit Link auf die Benutzerseite;
     - (b) Weiterleitung nach `#/users`;
     - (c) dieselbe Hinweisseite wie ein Nicht-Admin.
   - **Empfehlung (a):** Ein Tippfehler in der URL bleibt sichtbar, statt still umgeleitet zu werden. Der Text passt
     zu einem Admin, denn (c) sagte ihm, das Panel sei nur für Admins.
   - Trade-off: zwei neue Übersetzungsschlüssel mehr als bei (b).
   - Bis zur Antwort sieht ein Admin dort weiter die alte Seite (T5 ändert nur den Zweig für Nicht-Admins).
