<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Nicht-Admins: Tunnel-Zuordnungen für den Desktop, Hinweisseite im Web-Panel — Task-Ledger
Status: erledigt · Branch: feature/non-admin-access · Review: pro Task
Spec: docs/features/non-admin-access.md (Roadmap R-0484, R-0721)
Heavy: linux-full — T2 ändert Autorisierung und Antwort einer Server-Route im frp-Modul (`GET /api/frp/tunnels` für Nicht-Admins); der Sammellauf über `main` fährt die Server-API (`run.sh integration`, Schemathesis) und die Desktop-Tunnel-Journeys, die die Route als Admin lesen (`apps/desktop/e2e/test/lib/live.js:254-257`). Die Web-Journey `authz.spec.ts` (T5) läuft schon in der PR-CI (`frontend-e2e`). Kein `scenario`: FRP-Konfiguration, Visitor-TOML, Provisionierung und Datenpfad bleiben unverändert, der Desktop-Code unter Variante A auch (T3, T4 ändern nur Kommentare und Doku). Kein `windows`: kein Plattform-Code. Wählt Kevin Variante B, ändert T3 den Abruf in `tunnel.rs`; dann prüft die Session die Zeile neu
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Risikopfad (Auth/Autorisierung; `apps/server/app/modules/frp/*` und `apps/desktop/src-tauri/src/tunnel.rs`, FRP in `scripts/dev/review-risk.txt:44`, `:48`): T2 und T3 zusätzlich mit `security`; das Branch-Review ebenso.

Ziel:
1. Ein Nicht-Admin liest die Tunnel-Zuordnungen, die sein Desktop braucht, und nur die seiner zugewiesenen Server
   (R-0484). Den Weg wählt Kevin; die Tasks sind für die Empfehlung A + D2 + F2 geschrieben (Spec, Offene Frage 1).
2. Ein Nicht-Admin sieht im Web-Panel eine übersetzte Hinweisseite statt der Platzhalterseite (R-0721).

Zeilenangaben: origin/main@b25c65a6. Der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge:
  - T1, T5 sind ohne Kevins Antwort baubar.
  - T2 wartet auf Offene Frage 1, T3 und T4 hängen an T2.
  - T6 wartet auf Offene Frage 2 und hängt an T5.
- Server-Tests melden sich über `/api/auth/login` an wie `apps/server/tests/test_frp_tunnels.py:13-16`, mit den
  Fixtures `admin_user` (`admin`/`adminpass`) und `normal_user` (`viewer`/`viewerpass`) aus
  `apps/server/tests/conftest.py:315-338`. Einen Server weisen sie zu mit `normal_user.servers.append(…)` und
  `db_session.commit()` wie `apps/server/tests/test_frp_permissions.py:94-97`.
- Keine Route bekommt einen Docstring: Er wäre ihre OpenAPI-`description` und machte `test_openapi_snapshot` rot.
  Das Warum steht als `#`-Kommentar.
- Neue Code-Strings sind englisch. Neue Texte im Web stehen in `dictionaries.ts` (DE und EN, gleiche Schlüssel).
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737.

### T1 — Tunnel-Routen: heutige Rechte festhalten (Admin-Liste, Nicht-Admin an Einzel- und Schreib-Routen)  [x]
Komponente: server · Dateien: apps/server/tests/test_frp_tunnel_access.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @298720d6 2026-10-23T07:01:20+02:00
Review: approve (.ah-out/review/non-admin-access/T1.verdict.json)
Änderung: Neue Datei mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`).

Seed im Modul nach dem Muster `test_frp_permissions.py:22-78`:
- eine FRP-Konfiguration;
- Server `srv-a` und `srv-b`;
- STCP-Tunnel `t-a` (`srv-a`, Visitor-Port 6000) und `t-b` (`srv-b`, 6001), je mit Secret und `enabled=True`.

Tests:
- (a) Admin, `GET /api/frp/tunnels`:
  - liefert `t-a` und `t-b`;
  - jedes Element hat genau die Schlüssel `id, serverId, frpConfigId, name, tunnelType, protocol, localIp,
    localPort, secretKey, customDomains, visitorPort, connectionId, enabled, extraConfig, tags, createdAt`
    (`apps/server/app/modules/frp/models.py:111-131`);
  - `secretKey` ist `None`;
  - `?server_id=srv-a` liefert nur `t-a`.
- (b) `normal_user` mit `srv-a` zugewiesen bekommt `403` auf `GET /api/frp/tunnels/t-a`, `POST /api/frp/tunnels`
  (gültiger STCP-Body für `srv-a`), `PUT /api/frp/tunnels/t-a` (`{"name": "renamed"}`) und
  `DELETE /api/frp/tunnels/t-a`. Danach ist `t-a` unverändert in der DB, und es gibt keinen dritten Tunnel.

Die Liste `GET /api/frp/tunnels` für Nicht-Admins pinnt T1 nicht, die ändert T2.

Mutations-Stichprobe in einem eigenen Probe-Worktree (nie im Bau-Worktree, CLAUDE.md §5), je Mutation allein an
`apps/server/app/modules/frp/tunnel_router.py`:
- M1: `get_current_admin` → `get_current_user` an `PUT` (`:166`);
- M2: dasselbe an `GET /tunnels/{id}` (`:153`);
- M3: `mask_secrets=True` → `False` in `list_tunnels` (`:38`).

Erwartet: M1 und M2 machen (b) rot, M3 macht (a) rot. Ergebnis und Summary-Zeilen kommen in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnel_access.py
Doku: keine (intern)
Orakel: mutation-sample — M1 bis M3 an `tunnel_router.py`, je eine allein
HEAD: b25c65a6

### T2 — `GET /api/frp/tunnels`: Nicht-Admins lesen die freigegebenen Tunnel ihrer Server, nur die Felder des Desktops (R-0484)  [x]
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @92d9620e 2026-10-23T07:27:43+02:00
Review: approve (.ah-out/review/non-admin-access/T2.verdict.json)
Entscheidung: Kevin 2026-10-22: Variante A + D2 + F2 (Filter im bestehenden Endpunkt, nur freigegebene Tunnel der zugewiesenen Server, genau die zehn Felder von TunnelMapping).
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_tunnel_access.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung (Variante A + D2 + F2): `list_tunnels` (`tunnel_router.py:25-38`) hängt an
`current_user=Depends(get_current_user)` statt an `_admin=Depends(get_current_admin)` (`:30`).
- Admin: unverändert, alle Tunnel, `to_dict(mask_secrets=True)`.
- Nicht-Admin:
  - Server-IDs aus `current_user.servers`; ohne Zuordnung `[]`.
  - Sonst `FrpTunnel.server_id.in_(ids)` und `FrpTunnel.enabled.is_(True)`; `server_id` und `frp_config_id` grenzen
    zusätzlich ein.
  - Je Tunnel nur die Schlüssel aus einer Modul-Konstante `_MAPPING_FIELDS = ("id", "serverId", "tunnelType",
    "protocol", "localPort", "visitorPort", "customDomains", "connectionId", "enabled", "name")`, ausgelesen aus
    `to_dict(mask_secrets=True)`.
- Ein `#`-Kommentar nennt das Warum: Das ist, was der Desktop liest (`TunnelMapping`); dieselbe Trennung wie
  `_visible_stcp_tunnels`. Kein Docstring.
- Die anderen Routen bleiben, wie sie sind.

Tests in `test_frp_tunnel_access.py`, Seed um einen gesperrten STCP-Tunnel `t-off` (`srv-a`) und einen HTTPS-Tunnel
`t-web` (`srv-a`, `custom_domains="web.example"`) erweitert. Mit `normal_user`:
- (c) mit `srv-a` zugewiesen: die IDs sind genau `{t-a, t-web}`, jedes Element hat genau die zehn Schlüssel, kein
  `t-b`, kein `t-off`, kein `secretKey`; `t-web` hat `customDomains == "web.example"`.
- (d) ohne Zuordnung: `200` und `[]`.
- (e) mit `srv-a`: `?server_id=srv-b` und `?frp_config_id=<unbekannt>` ergeben `[]`, `?server_id=srv-a` ergibt
  `{t-a, t-web}`.
- (f) Parität, Klasse D:
  - Die Feldnamen von `pub struct TunnelMapping` aus `apps/desktop/src-tauri/src/tunnel.rs` (Pfad über
    `Path(__file__).resolve().parents[3]` wie `apps/server/tests/test_event_whitelist.py:44`), in camelCase
    gewandelt, sind gleich der Menge `_MAPPING_FIELDS`.
  - Die Menge ist nicht leer, ein fehlendes Feld macht den Test rot.

Zuerst rot auf HEAD: (c), (d), (e), denn sie bekommen `403`. (a) und (b) aus T1 bleiben grün, damit ist der Admin
unverändert. `test_openapi_snapshot` bleibt grün ohne Snapshot-Änderung.

Unter Variante B schreibt die Session diese Task um: neue Route, `apps/server/tests/openapi.snapshot.json` in
`Dateien:`, `list_tunnels` bleibt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnel_access.py tests/test_frp_tunnels.py tests/test_frp_permissions.py tests/test_openapi_snapshot.py
Doku:
- `docs/developer/api-reference.html:140` und `docs/en/developer/api-reference.html:140`, ein Satz:
  - Admins bekommen alle Tunnel wie beschrieben.
  - Nicht-Admins bekommen nur die freigegebenen Tunnel ihrer zugewiesenen Server, je mit `id, serverId, name,
    tunnelType, protocol, localPort, visitorPort, customDomains, connectionId, enabled`; ohne Zuordnung `[]`.
  - Die übrigen Tunnel-Routen: Nicht-Admin → `403`.
- `CHANGELOG.md` (Fixed, umlautfrei): Der Desktop löst für Benutzer ohne Admin-Rechte auch Verbindungen auf, die
  ein Admin mit einem Tunnel verknüpft hat, und zeigt deren Tunnel; sie lesen dafür nur die Tunnel ihrer
  zugewiesenen Server.
Abhängt von: T1
Beweis: origin/main@b25c65a6 · Probe (Python 3.13, FastAPI 0.141.1): `get_current_admin(current_user=<Stand-in mit is_admin=False>)` wirft dreimal identisch `HTTPException(403, "Admin-Rechte erforderlich")`; zwei Minimal-Apps mit derselben Route an `get_current_admin` bzw. `get_current_user` erzeugen ein identisches `openapi()`. Der rote Test ist (c) mit `bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnel_access.py`
Orakel: contract — ein Nicht-Admin liest genau die freigegebenen Tunnel seiner zugewiesenen Server mit genau den Feldern von `TunnelMapping`
Dedup-Key: bug:server:frp/tunnel_router.py:list_tunnels-admin-only
HEAD: b25c65a6
Semantik: Die Doku beschreibt heute die Lücke, nicht ein gewolltes Recht: `docs/admin/frp-tunnel.html:106` — „Die Verbindungen löst der Desktop-Client auf den tatsächlichen Port auf: die mit dem Tunnel automatisch angelegte (<code>127.0.0.1:&lt;Visitor-Port&gt;</code>) für alle Benutzer, eine von Hand mit dem Tunnel verknüpfte nur für Admins, denn nur sie lesen die Tunnel-Zuordnungen.“; R-0430 führt sie als offene Lücke (`docs/features/desktop-session-ports.md:59`). Kevin hat R-0484 als BUG angenommen und den Weg an den Plan gegeben (Notiz der Zeile, 2026-10-18).

### T3 — Desktop (Rust): Kommentare und Entwickler-Doku zu den Zuordnungen für Nicht-Admins  [x]
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f0fc9eb1 2026-10-23T07:28:07+02:00
Review: approve (.ah-out/review/non-admin-access/T3.verdict.json)
Entscheidung: Kevin 2026-10-22: Variante A (T2), also nur Kommentare und Entwickler-Doku, kein neuer Abruf.
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/connection/mod.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Änderung (Variante A): Nur Kommentare, kein Verhalten. Die Stellen, die sagen, nur Admins lesen Zuordnungen, sagen
künftig, dass ein Nicht-Admin die Zuordnungen seiner zugewiesenen Server liest:
- `tunnel.rs:69`;
- `tunnel.rs:405-406` (Test-Helfer `literal`: „wie ein Nicht-Admin eine automatische sieht“ wird „ohne eigene
  Zuordnung“);
- `tunnel.rs:573-574`;
- `apps/desktop/src-tauri/src/connection/mod.rs:471`.

Die Regel 2 (wörtliche Auflösung) bleibt für Verbindungen ohne Zuordnung, ihre Tests bleiben unverändert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- tunnel::
Doku: `docs/developer/desktop.html:261` und `:267`, EN `docs/en/developer/desktop.html:261` und `:267`:
- „nur Admins dürfen sie lesen“ / „only admins may read them“ wird „Admins lesen alle, andere Benutzer die
  freigegebenen Tunnel ihrer zugewiesenen Server“.
- „für Nicht-Admins leer“ / „empty for non-admins“ wird „leer für einen Benutzer ohne zugewiesenen Server mit
  Tunnel“.
- Der Satz zu Regel 2, „So … auch für Nicht-Admins aufgelöst“, bleibt.
Abhängt von: T2

### T4 — Desktop-UI: Kommentare und Admin-Doku zu den Zuordnungen für Nicht-Admins  [x]
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e0d5368e 2026-10-23T07:29:13+02:00
Review: approve (.ah-out/review/non-admin-access/T4.verdict.json)
Entscheidung: Kevin 2026-10-22: Variante A (T2).
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html
Änderung (Variante A): Nur Kommentare, kein Verhalten:
- `connectFlow.ts:149` „(admins only)“ wird „(an admin's, or one on a server assigned to the user)“;
- `connectFlow.test.ts:135` „Only admins read mappings, so a non-admin has none“ wird „A user without a mapping
  for the connection“.

Die Assertions bleiben.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: `docs/admin/frp-tunnel.html:106` und `docs/en/admin/frp-tunnel.html:106`: „eine von Hand mit dem Tunnel
verknüpfte nur für Admins, denn nur sie lesen die Tunnel-Zuordnungen“ / „one linked to the tunnel by hand for admins
only, as only they read the tunnel mappings“ wird „eine von Hand verknüpfte für Admins und für Benutzer, denen der
Server des Tunnels zugewiesen ist“.
Abhängt von: T2

### T5 — Web-Panel: übersetzte Hinweisseite für Nicht-Admins (R-0721)  [x]
Komponente: web · Dateien: apps/web/src/pages/Placeholder.svelte, apps/web/src/pages/Placeholder.test.ts, apps/web/src/lib/i18n/dictionaries.ts, apps/web/tests/e2e/authz.spec.ts, docs/admin/benutzer.html, docs/en/admin/users.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @808d7dcb 2026-10-23T06:52:51+02:00
Review: approve (.ah-out/review/non-admin-access/T5.verdict.json)
Änderung: `Placeholder.svelte` (`:7-21`) liest `isAdmin` aus `$lib/stores/auth` (`apps/web/src/lib/stores/auth.ts:98`)
und `t` aus `$lib/i18n`.
- Nicht-Admin:
  - `.page-title` = `t('page.adminOnly.title')`, Text = `t('page.adminOnly.text')`;
  - DE „Web-Panel nur für Admins“ / „Bitte den Desktop-Client nutzen.“;
  - EN „Web panel for admins only“ / „Please use the desktop client.“
- Admin: sieht bis T6 die bisherige Seite, unverändert.
- Der Dateiname bleibt (`docs/developer/webui.html:48`). `routes.ts`, `routeGuard.ts`, `App.svelte` und die
  Seitenleiste bleiben.

Neue Datei `apps/web/src/pages/Placeholder.test.ts` mit SPDX-Header. Muster: `apps/web/src/modals/UserModal.test.ts`
mit `vi.mock('$lib/api/auth')`, `vi.mock('$lib/api/client')`, `auth.hydrate()` und `language.set(…)`. Tests:
- (a) Nicht-Admin, `de` und `en`: Titel und Text wie oben, die Wörter „portiert“ und „spaeteren“ kommen nicht vor.
- (b) Admin: Der Hinweis `page.adminOnly.title` erscheint nicht.

Zuerst rot: (a).

`apps/web/tests/e2e/authz.spec.ts:28`: Die erwartete `.page-title` wird `'Web-Panel nur für Admins'` (Locale
`de-DE`, `apps/web/playwright.config.ts:64`); Testname und die Assertion der leeren Nav (`:24`) bleiben. Die Spec
läuft in der PR-CI (`frontend-e2e`), nicht im `Verify:`.
Assertion-Änderung: apps/web/tests/e2e/authz.spec.ts::Nicht-Admin: leere Admin-Nav + Deep-Link mountet den Placeholder statt der Admin-Seite — der erwartete Seitentitel folgt dem neuen Text der Seite (R-0721), die Prüfung bleibt gleich streng
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Placeholder.test.ts src/lib/i18n/i18n.test.ts
Doku:
- `docs/admin/benutzer.html:47` und `docs/en/admin/users.html:41`: Zeile `user` um einen Satz ergänzt: Im Web-Panel
  sieht die Rolle nur einen Hinweis auf den Desktop-Client.
- `CHANGELOG.md` (Changed, umlautfrei): Benutzer ohne Admin-Rechte sehen im Web-Panel einen uebersetzten Hinweis, dass
  das Panel Admins vorbehalten ist und der Desktop-Client der Weg ist, statt der alten Platzhalterseite.
Dedup-Key: ref:web:Placeholder.svelte:non-admin-dead-end
HEAD: b25c65a6

### T6 — Web-Panel: übersetzte Seite für einen Admin auf einer unbekannten Route  [x]
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @73d21d5d 2026-10-23T06:59:38+02:00
Review: approve (.ah-out/review/non-admin-access/T6.verdict.json)
Entscheidung: Kevin 2026-10-22: (a) übersetzte Seite "Seite nicht gefunden" mit Link auf die Benutzerseite (#/users).
Komponente: web · Dateien: apps/web/src/pages/Placeholder.svelte, apps/web/src/pages/Placeholder.test.ts, apps/web/src/lib/i18n/dictionaries.ts, CHANGELOG.md
Änderung (Empfehlung a):
- Der Admin-Zweig in `Placeholder.svelte` zeigt `t('page.notFound.title')` und einen Link auf `#/users`
  (`t('page.notFound.back')`):
  - DE „Seite nicht gefunden“ / „Zur Benutzerverwaltung“;
  - EN „Page not found“ / „Go to user management“.
- Die drei alten deutschen Texte (`:14`, `:15`, `:19`) entfallen.

Test (c) in `Placeholder.test.ts`: Admin, `de` und `en`, zeigt Titel und Link mit `href="#/users"`; Test (b) aus T5
bleibt. Zuerst rot: (c).
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Placeholder.test.ts src/lib/i18n/i18n.test.ts
Doku: `CHANGELOG.md` (Changed, umlautfrei: eine unbekannte Adresse im Web-Panel zeigt Admins eine uebersetzte Seite
„nicht gefunden“ mit Link zur Benutzerverwaltung)
Abhängt von: T5

### T7 — Funde aus tester und Branch-Review: Admin-Liste mit gesperrten Tunneln, `frp_config_id` grenzt ein, README-Zeile  [x]
Komponente: server · Dateien: apps/server/tests/test_frp_tunnel_access.py, README.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8777fef6 2026-10-23T10:00:40+02:00
Review: approve (.ah-out/review/non-admin-access/T7.verdict.json)
Änderung (Funde vom 2026-10-23, kein Produktcode):
- tester (wichtig): `test_admin_lists_every_tunnel_in_the_full_shape_without_secret` nutzt `more_tunnels` statt
  `tunnels` und erwartet die IDs `{t-a, t-b, t-off, t-web}`, mit `?server_id=srv-a` genau `{t-a, t-off, t-web}`.
  Schlüsselmenge und `secretKey is None` prüft er weiter für jedes Element. Grund: Die Mutation des testers an
  `tunnel_router.py` (`db.query(FrpTunnel).filter(FrpTunnel.enabled.is_(True))`, also der `enabled`-Filter auch für
  Admins) blieb grün; die Admin-Ansicht `TunnelsTab.svelte` zeigt gesperrte Tunnel.
- Branch-Review (nit, mitgenommen, dieselbe Datei): `test_non_admin_query_parameters_only_narrow` bekommt den Fall
  `{"frp_config_id": "cfg-1"}` → `{t-a, t-web}` (kein `t-b`, kein `t-off`); der Fall mit unbekannter Config bleibt.
- Branch-Review (wichtig): `README.md:283` `GET /api/frp/tunnels  # Tunnel list (admin)` wird
  `# Tunnel list (admin; user: enabled tunnels of assigned servers)`; die Spaltenausrichtung der Nachbarzeilen bleibt.

Mutations-Stichprobe in einem eigenen Probe-Baum (nie im Bau-Worktree): die Mutation des testers oben macht den
geänderten Admin-Test rot; die Mutation „`frp_config_id`-Zweig ohne den Nicht-Admin-Filter“ macht den neuen Fall rot.
Ergebnis und Summary-Zeilen kommen in den Commit-Body.
Assertion-Änderung: apps/server/tests/test_frp_tunnel_access.py::test_admin_lists_every_tunnel_in_the_full_shape_without_secret — die Admin-Liste umfasst jetzt auch gesperrte und HTTPS-Tunnel, die erwarteten ID-Mengen werden größer und die Prüfung strenger
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnel_access.py
Doku: `README.md:283` (s. o.)
Orakel: mutation-sample — `enabled`-Filter für alle und `frp_config_id` ohne Nicht-Admin-Filter an `tunnel_router.py`, je eine allein
Abhängt von: T2
