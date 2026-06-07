# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Changed

- **FRP von 0.61.1 auf 0.69.1 angehoben** — frps-Image (`docker-compose.yml`),
  gebundeltes frpc (CI/Release) und die SHA-256-Pins der frp-Artefakte im
  Gleichschritt. Das Wire-Protokoll bleibt v1 (Default in 0.69), daher
  abwaerts­kompatibel; v2 ist opt-in (`transport.wireProtocol`) und wird nicht
  gesetzt. **Tunnel-getestet:** frps+frpc 0.69.1 mit der vom `config_generator`
  erzeugten Struktur (STCP-Proxy + `allowUsers`, Visitor mit `serverUser`,
  mutual `transport.tls` gegen eine eigene CA) — `verify` akzeptiert die Config
  und Nutzdaten fliessen durch den Tunnel.

## [0.25.0] - 2026-06-06

### Security

- **Desktop: Path-Traversal (Zip-Slip) beim Schreiben server-gelieferter
  PKI-Dateinamen geschlossen.** Ein boesartiger/kompromittierter Server konnte
  ueber den Visitor-Bundle-Dateinamen (`pki_dir.join(filename)`) beliebige Dateien
  auf dem Client schreiben. Dateinamen werden jetzt als einzelne, separator-freie
  Pfad-Komponente validiert.
- **Desktop: TLS auf der authentifizierten Server-URL erzwungen.** Login/Refresh/
  Logout/`authenticated_get` senden Passwort + Tokens nur noch ueber `https://`
  (Ausnahme: Loopback fuer lokale Entwicklung) — kein Klartext mehr ueber das Netz.
- **Monitoring: VictoriaMetrics-Line-Protocol-Injection geschlossen.** Agent-Report-
  Felder werden numerisch erzwungen, Tags/Measurements escaped (Backslash/Newline/
  Control-Chars) — ein Agent-Key kann keine fremden Zeitreihen mehr faelschen.
- **FRP-PKI: CA-Private-Key + alle Client-Keys aus dem internet-zugewandten
  frps-Volume entfernt.** Master-PKI liegt jetzt server-privat (Volume `frp-pki`);
  ins geteilte `frp-config`-Volume wird nur noch die frps-Teilmenge
  (`ca.crt`/`frps.crt`/`frps.key`) publiziert. Bestandsdeployments werden beim
  Startup einmalig migriert (CA bleibt erhalten).
- **Monitoring: Admin-API nicht mehr direkt zum Host exponiert.** Agent-Metriken
  laufen jetzt tunnelfrei ueber den Server-Proxy (`POST /api/monitoring/agent/
  {id}/report` auf 443); der Monitoring-Dienst ist nur noch intern erreichbar.
  `/docs`+`/openapi.json` sind standardmaessig aus (Env `MONITOR_ENABLE_DOCS`),
  der interne/Agent-Key wird konstant-zeitig (`secrets.compare_digest`,
  fail-closed) verglichen.

- **Server: Passwort-Reset widerruft jetzt bestehende JWTs.** Ein Passwort-Wechsel
  setzt `users.tokens_valid_after`; Tokens mit `iat` davor (oder ohne `iat`) werden
  abgelehnt — vorher blieben Access-(8h)/Refresh-(7d)-Tokens nach einem Reset gueltig.
- **Server: Input-Validierung auf User-Endpunkten.** `UserCreate`/`UserUpdate`
  erzwingen Passwort-Mindestlaenge (8) und einen Username-Charset
  (`^[a-zA-Z0-9._-]+$`, 3–64) — der Username fliesst in FRP-TOML und PKI-Dateinamen.

- **Extension: API-Key nicht mehr im URL-Query-String.** `background.js`/`popup.js`/
  `options.js` senden den Key jetzt über den `X-API-Key`-Header statt `?api_key=`
  (vorher landete der langlebige Key in Access-/Proxy-Logs, Referer, History).
  Zusätzlich: überflüssige `tabs`-Permission entfernt, und Verbindungs-URLs werden
  vor dem Öffnen auf `http(s)` geprüft.
- **Agent: `--insecure` persistiert nicht mehr in die Schleife.** Statt `INSECURE=1`
  dauerhaft zu speichern (TLS-Verify dauerhaft aus + API-Key-Leak pro Zyklus),
  erfasst der Agent beim Provisioning das Server-Zertifikat und pinnt es (TOFU) —
  `--insecure` gilt nur noch für den einmaligen Activate-Aufruf. Zusätzlich:
  Secret-Verzeichnisse `0700` (auch bei Raw-Binary-Provisioning), Config-Writer
  lehnt Steuerzeichen ab (verhindert `INSECURE=1`-Injection via Newline),
  PKI-Bundle-Dateien default `0600` (nur `.crt` auf `0644`).
- **Container laufen nicht mehr als root.** Server- und Monitoring-Image starten
  nur kurz als root (chownt die gemounteten Pfade), droppen dann via `gosu` auf
  einen Non-root-User (uid 10001) — uvicorn, Alembic, Cert-Generierung und
  Hook-Subprozesse laufen unprivilegiert. Begrenzt die Auswirkung einer
  App-RCE/Path-Traversal auf einen Non-root-Prozess.
- **`frps.toml` jetzt `0600`.** Die Datei (globaler `auth.token` +
  Dashboard-Passwort) im mit frps geteilten Volume wurde zuvor world-readable
  (`0664`) geschrieben; jetzt umask-robust `0600` (frps liest sie als root).
- **CI/CD-Supply-Chain gehärtet.** Alle third-party GitHub-Actions sind auf den
  vollen Commit-SHA gepinnt (vorher mutable Tags/Branch-Refs wie
  `rust-toolchain@stable` in Jobs mit ghcr-Push + `contents:write`); der
  `frpc`-Download wird vor Nutzung gegen einen gepinnten SHA-256 verifiziert;
  Dependabot (`github-actions` + pip/npm/gomod/cargo) hält die Pins aktuell.
- **Desktop: drei aktive `rustls`-Advisories geschlossen** (`reqwest` 0.11 → 0.12).
  `reqwest` 0.11 war der einzige Konsument des EOL-`rustls` 0.21 →
  `rustls-webpki` 0.101.7 mit zwei Cert-Validation-Bypässen
  (RUSTSEC-2026-0098/-0099: Name-Constraints für URI-/Wildcard-Namen fälschlich
  akzeptiert) und einem DoS-Panic (RUSTSEC-2026-0104, CRL-Parsing). Jetzt
  `rustls` 0.23.40 / `rustls-webpki` 0.103.13 — Krypto-Provider bleibt **`ring`**
  (kein `aws-lc-rs`, also kein neuer NASM-Build-Zwang auf Windows), Roots bleiben
  `webpki-roots` (unveraendertes Trust-Verhalten). Keine Code-Aenderung noetig.

### Changed

- **Provisioning-Antwort `monitorUrl` ist nun ein server-relativer Pfad
  (`/api/monitoring`).** Der Agent setzt ihn an die bereits TLS-vertraute
  Server-URL, gegen die er provisioniert wurde — der Metrik-Push trifft so immer
  denselben Host/Cert, ohne dass der Server seine oeffentliche Adresse kennen muss.
- **Desktop: `keyring`-Crate von 2.3 auf 3.6 angehoben.** Verhalten unveraendert
  (gleiche Backends: Linux `secret-service`/zbus + `crypto-rust`, macOS Keychain,
  Windows Credential Manager). Der Major-Bump zieht ein neueres `zbus` (4.x) nach
  und entfernt damit die als **unmaintained** geflaggte transitive Abhaengigkeit
  `derivative` (RUSTSEC-2024-0388); netto **-12** Crates im Lockfile. Dependabots
  vorgeschlagener Sprung auf `keyring` 4.0 wurde bewusst **nicht** uebernommen: Die
  4.x-Crate ist auf Sample-/CLI-Code umgebaut (re-exportiert `Entry`/`Error` nicht
  mehr → unbaubar) und zieht ueber den unbedingten `db-keystore`-Store eine ganze
  SQL-Engine (Turso) + Volltextsuche (Tantivy) + `bindgen` herein (+160 Crates).
- **Desktop: `windows`-Crate von 0.56 auf 0.61 angehoben.** Der `flags`-Parameter
  von `CredReadW`/`CredDeleteW` ist in 0.61 `Option<u32>` statt `u32` — der
  Windows-Credential-Code (`password.rs`) wurde entsprechend von `0` auf `Some(0)`
  angepasst. Verhalten unveraendert (`0` ≙ keine Flags). Nur subtraktiv im Lockfile
  (-5 Crates: doppelter 0.56-Subtree entfernt, 0.61.3 war via Tauri bereits
  vorhanden). Verifiziert per isoliertem Cross-Compile gegen `x86_64-pc-windows-gnu`,
  da der Linux-CI-Job den `#[cfg(windows)]`-Pfad nicht kompiliert.
- **Desktop-UI: Build-Toolchain modernisiert** — Vite 5→8, TypeScript 5→6,
  ESLint 9→10, `@sveltejs/vite-plugin-svelte` 4→7, `eslint-plugin-svelte` 2→3
  (+ `svelte-eslint-parser`, `globals`, `prettier-plugin-svelte`, `@types/node`).
  `tsconfig.json` auf relative `paths` ohne `baseUrl` umgestellt (TS-7-fest).
  Der strengere `eslint-plugin-svelte@3`-Regelsatz deckte echte Mängel auf, die
  **gefixt** statt unterdrückt wurden: 18 `{#each}`-Blöcke in den Monitoring-Views
  haben jetzt stabile `(key)` (korrekte DOM-Reconciliation beim Umsortieren/Entfernen),
  und `normalizeConnection` dedupliziert Connection-Tags (keine doppelten Tag-Chips,
  kollisionsfreie Keys). Drei Regel-Treffer waren Fehlalarme (uPlot-DOM-Interop,
  transiente `Map` in `$derived.by`, bewusste `$effect`-Dependency-Registrierung)
  und sind mit begründeten `eslint-disable`-Kommentaren versehen.
- **Web-Frontend: Build-Toolchain modernisiert** — Vite 5→8, TypeScript 5→6,
  ESLint 9→10, Vitest 2→4, `@sveltejs/vite-plugin-svelte` 4→7,
  `eslint-plugin-svelte` 2→3, Svelte 5.1→5.56, `typescript-eslint`,
  `@playwright/test`, `svelte-check`, `@types/node`, `globals`,
  `prettier-plugin-svelte`. Fehlendes direktes `@eslint/js` ergänzt (wurde unter
  ESLint 9 nur transitiv aufgelöst, unter 10 nicht mehr). `tsconfig.json` auf
  relative `paths` ohne `baseUrl` umgestellt (TS-7-fest). In `client.ts` eine tote
  `null`-Initialisierung entfernt. Die sieben `prefer-svelte-reactivity`- und der
  eine `no-dom-manipulating`-Treffer waren allesamt Fehlalarme (transiente
  `Map`/`Set` in `$derived.by`, Copy-then-reassign-Pattern, uPlot-DOM-Interop) und
  sind mit begründeten `eslint-disable`-Kommentaren versehen.
- **Ops: schwebende `:latest`-Images in `docker-compose.yml` gepinnt.**
  `snowdreamtech/frps` → `0.61.1` (im Gleichschritt mit der gebundelten frpc-Version
  `FRP_VERSION`, damit Server/Client nicht auseinanderlaufen) und
  `victoriametrics/victoria-metrics` → `v1.144.0` — reproduzierbare Deployments,
  keine ueberraschenden Versionsspruenge mehr. (Ein FRP-Bump auf 0.69.x ist bewusst
  separat zu testen.)
- **Server: totes `requests`-Dependency entfernt** (`apps/server/requirements.txt`);
  der einzige HTTP-Client ist `httpx` (`monitoring_proxy.py`).

### Fixed

- **Desktop:** frpc-Status wird nach Prozess-Ende zurueckgesetzt (Restart war
  zuvor mit „frpc laeuft bereits" blockiert). (#2)
- **Desktop:** Dashboard-Connections-Subscription wird in `onDestroy` aufgeraeumt
  (Subscription-Leak pro Navigation). (#6)
- **Desktop:** Wechsel in den Server-Modus mit gueltiger Session laedt jetzt
  neu und startet den Tunnel (zuvor erst nach Neustart). (#7)
- **Desktop:** re-entrantes `requestPassword` haengt nicht mehr den ersten
  Connect-Flow (in-flight-Prompt wird als „cancelled" aufgeloest). (#8)
- **Windows-Desktop:** Session-Load implementiert (`CredReadW`) — kein
  Re-Login mehr bei jedem Start. (#4)
- **Windows-Agent:** Service ist SCM-aware (`svc.Run`) — `sc start` laeuft nicht
  mehr in Fehler 1053. (#3)
- **Agent:** Watched-Service-Health wird pro Zyklus nur einmal erhoben (#5);
  letzter STOPPED-Service auf Windows korrekt als `enabled_inactive` (#11);
  re-Provisioning ueberschreibt `SERVICES` nicht mehr mit leer (#12).
- **Server:** `GET /api/frp/status` blockiert den Event-Loop nicht mehr
  (sync-Endpoint) (#9); Ansible-Playbook-Schreib/Loeschvorgaenge sind mit der
  DB-Transaktion geordnet (keine verwaisten Dateien/Rows) (#10).
- **Frontend:** englischsprachige Nutzer sehen keine deutschen Strings mehr
  (Tunnel-Status-Labels + ~54 `'Fehler'`-Toast-Fallbacks i18n-isiert) (#13);
  Metrik-Fetches bei schnellem Perioden-Wechsel werden sequenziert
  (kein Stale-Overwrite) (#14).

### Removed

- **Monitoring-Host-Port (`MONITOR_AGENT_PORT`/`8480`) aus `docker-compose.yml`
  entfernt** (nur noch `expose: 8080`).
  **Breaking (Ops):** Nach dem Upgrade muessen bereits provisionierte Agents
  **neu provisioniert** werden — ihre gespeicherte `MONITOR_URL` zeigt sonst auf
  den weggefallenen Port. Wer direkt gegen `:8480` skriptet, stellt auf
  `https://<server>/api/monitoring/agent/{id}/report` um.

## [0.24.0] - 2026-06-04

### Security

- **FRP-PKI-Schluessel jetzt `0600`, PKI-Verzeichnis `0700`.** Private Keys
  (`ca.key`, `frps.key`, Client-Keys) wurden zuvor umask-abhaengig (oft
  world-readable `0644`) geschrieben. `_write_key` erzeugt sie nun atomar mit
  `0600`; bestehende lax-permissionierte Deployments werden bei jedem
  PKI-Zugriff idempotent nachgezogen.
- **IDOR auf `GET /api/frp/provision/{server_id}/config(-hash)` geschlossen.**
  Mit einem beliebigen gueltigen Read-API-Key war zuvor die `frpc.toml`
  (globaler `auth.token` + STCP-Secrets) jedes Servers abrufbar. API-Keys sind
  jetzt an einen `server_id` gebunden; der Endpoint prueft die Server-Scope
  strikt (403) und ist Admin-only.
- **TOCTOU im Provision-Activate behoben.** Der Einmal-Token wird nun atomar
  per bedingtem `UPDATE ... WHERE used_at IS NULL` konsumiert; ein verlorenes
  Rennen liefert `409` und erzeugt fail-closed keinen API-Key.
- **Hook-Ausfuehrung: ehrliche Sicherheits-Posture.** Das wirkungslose
  `exec()`-Pseudo-Sandbox wurde entfernt; die Worker-Umgebung ist auf das
  Noetigste minimiert (entfernt u.a. `ADMIN_PASSWORD`). Hooks bleiben bewusst
  vertrauenswuerdiger Admin-Code mit DB-Zugriff — das ist nun dokumentiert und
  testverankert, statt faelschlich „isoliert" zu suggerieren.

### Added

- **GitHub Actions CI/CD.** `ci.yml` (Lint/Tests aller Komponenten),
  `docker.yml` (Server- + Monitoring-Images nach ghcr.io) und `release.yml`
  (Desktop-DEB/RPM, Agent-Pakete + Binaries, Checksums, Draft-Release).
- **Periodische JWT-Blacklist-Bereinigung.** `cleanup_expired_blacklist` laeuft
  jetzt als System-Job (Intervall 6 h); zuvor wuchs die `token_blacklist`-
  Tabelle unbegrenzt.
- **Server-Bindung fuer API-Keys** (`api_keys.server_id`, inkl.
  Alembic-Migration mit Backfill).

### Changed

- **Docker-Images kommen aus ghcr.io**
  (`ghcr.io/ks98/adminhelper/{server,monitoring}`); `docker-compose.yml` und
  `.env.example` entsprechend vereinheitlicht.
- **Quellcode-Kommentare und README auf Englisch** vereinheitlicht; Doku-Links
  und CI-Beschreibung von GitLab auf GitHub umgestellt. Lokalisierte
  UI-Strings (DE/EN) bleiben unveraendert.

### Removed

- Toter Code: `ScriptSecurityError`, `ScriptTimeoutError`, ungenutzte
  `UserResponse` und die wirkungslose Hook-Sandbox.

### Fixed

- Alembic-`downgrade` Postgres-kompatibel (`sa.DateTime()` / `sa.String()`
  statt `sa.DATETIME()` / `sa.VARCHAR()`).

## [0.23.2] - 2026-05-03

### Fixed

**Desktop-Client: alte Connections nach Server-Wechsel sichtbar**

Beim Wechsel zwischen zwei AdminHelper-Servern (Login zu B nach Login zu A,
oder serverUrl-Aenderung in den Settings) blieben die Verbindungen vom
vorherigen Server im Desktop-Client sichtbar — sowohl im Memory-Store als
auch persistent in `connections.json` (Tauri-AppDataDir). Bei Fehlschlag
des Fetch-Calls zum neuen Server (z.B. falscher Port) blieb der alte Stand
unveraendert.

Drei Code-Pfade hatten den Connection-Reload nicht getriggert:

- `session.ts:login()` aktualisierte nur das Session-Objekt, ohne
  `connections.reloadForMode()` zu rufen → frischer Login zu Server B
  liess die alten Daten von Server A stehen, bis der User manuell die
  Connections-Page wechselte (was ohne Trigger auch nichts neu lud).
- `session.ts:logout()` setzte nur die Session auf `null`, leerte aber
  nicht den Connection-Cache → die Datei blieb voll mit Server-A-Daten
  und tauchte nach dem naechsten App-Start wieder auf.
- `settings.ts:saveSettings()` ignorierte serverUrl-Wechsel mit aktiver
  Session — das alte JWT gehoerte zum alten Server, der neue Server
  haette es abgelehnt, aber der User merkte das nie, weil kein Reload
  triggerte.

Fix: Login triggert nun `reloadForMode(settings, sess)` direkt nach dem
Token-Setzen. Logout leert vor dem Session-Reset den Connection-Cache
(Memory + Datei via `saveAll([])`). Settings erzwingen bei serverUrl-
Wechsel mit aktiver Session ein `serverLogout()`, sodass der User in den
needsLogin-Flow geschickt wird.

## [0.23.1] - 2026-05-03

### Highlights

**Server-zentrisches Provisioning** — bis v0.22.x war der Provision-Flow
fest an FRP gekoppelt; wer keinen Tunnel hatte, konnte den Token-Flow nicht
nutzen und bekam keinen Monitor-Agent-Key. Ab v0.23.x lebt Provisioning im
Server-Modul und liefert je nach Konfiguration optional FRP-Bundle und
Monitor-Key. Ein einziger Agent-Aufruf ersetzt das alte zweistufige Setup.

(v0.23.0 wurde lokal getaggt, aber nie auf origin gepusht — der CI-Job
scheiterte an einer Prettier-Verletzung in `Frp.svelte`. v0.23.1 enthaelt
denselben Funktionsumfang plus den Style-Fix.)

### Fixed

- `prettier --check` failte im CI-Job auf `Frp.svelte`, weil beim Entfernen
  der Provision-Modal-Einbindung eine ueberzaehlige Leerzeile stehengeblieben
  war. Inhaltlich kein Effekt, blockierte aber die Tag-Pipeline.

### Added

- Neues Backend-Modul `app.modules.provisioning` mit Endpoints
  `POST /api/servers/{id}/provision/token`, `GET /tokens` und
  `POST /activate` (Header `X-Provision-Token`). Activate-Antwort:
  `{ serverName, apiKey, monitorApiKey?, monitorUrl?, frp? }` —
  Felder sind `null`, wenn die jeweilige Komponente nicht konfiguriert
  oder nicht erreichbar ist. Resilience-Pattern: ausgefallener
  Monitor-Service blockiert das Provisioning nicht.
- Neuer Agent-Subbefehl `adminhelper-agent provision --url ... --token ... --server-id ...`
  in `internal/provision/`. Orchestriert Activate-Aufruf, dann je nach
  Antwort `monitor.Init` und `frpc.Apply`.
- Frontend: `ServerProvisionModal.svelte` an der Servers-Page (statt
  vorher in der Frp-Page); generiert genau einen `provision`-Befehl
  zum Kopieren.
- Tests: `server/tests/test_provisioning.py` mit pytest-httpx-Mocking
  fuer den Monitor-Service-Aufruf (8 Testfaelle, u.a. minimal/with-monitor/
  monitor-down/wrong-token/used-twice/wrong-server).
- Neue Test-Dependency: `pytest-httpx>=0.30` in `requirements-dev.txt`.

### Changed

- Tabelle `frp_provision_tokens` umbenannt zu `provision_tokens` per
  `op.rename_table` (nicht-destruktive Alembic-Migration
  `0494a8f377ef_rename_frp_provision_tokens_to_provision_tokens`).
  Constraints (PK, UNIQUE auf `hashed_token`, FK auf `servers`) werden
  von Postgres automatisch mit umbenannt.
- `frpc.Init` (HTTP + Datei + Service in einem) wurde zu `frpc.Apply`
  (nur Datei + Service) zerlegt — der HTTP-Activate-Aufruf wandert in
  das neue `internal/provision/` Package.
- `frp/models.py` exportiert `ProvisionToken` weiterhin (Re-Export aus
  `app.modules.provisioning.models`) als Backwards-Compat fuer Test-
  Fixtures, die das alte Symbol importieren.

### Removed (Breaking)

- Alte Endpoints `/api/frp/provision/{id}/token`, `/tokens` und `/activate`
  sind komplett entfernt — Pre-Release, kein Deprecation-Window.
  Das FRP-Modul behaelt nur noch `/api/frp/provision/{id}/config` und
  `/config-hash` fuer den laufenden Sync-Agent.
- Agent-Subbefehl `adminhelper-agent frpc init` ist entfernt — Setup
  laeuft nun ausschliesslich ueber `adminhelper-agent provision`.
- Frontend-API: `createMonitoringAgentKey()` (toter Code, war im alten
  Modal als Fallback gedacht) und der API-Type `MonitoringAgentKeyResult`
  sind weg. Die zugehoerigen Funktionen `listProvisionTokens` /
  `createProvisionToken` sind aus `lib/api/frp.ts` in das neue
  `lib/api/provisioning.ts` umgezogen, Types `FrpProvisionToken[…]`
  heissen jetzt `ProvisionToken[…]`.
- Versions-Bump aller Komponenten auf `v0.23.1` (Server, Monitoring,
  Web-Admin-Panel, Desktop-Client, Browser-Extension, Go-Agent via
  `.gitlab-ci.yml AGENT_VERSION`, 40 Doku-HTML-Footer).

## [0.22.1] - 2026-05-02

### Fixed

- `docker compose pull` scheiterte mit `pull access denied for
  adminhelper-monitoring`, weil das Monitoring-Image nirgends in
  der Registry lebte (es gab nur einen `docker_server`-Job). Neuer
  `docker_monitoring`-Job in `.gitlab-ci.yml` (1:1 analog zu
  `docker_server`) baut + pusht jetzt das Monitoring-Image nach
  `docker.nevondo.com/$CI_PROJECT_PATH/monitoring` mit den Tags
  SHA, `latest`, `dev` (main-Branch) und `$CI_COMMIT_TAG` (bei Tags).
  `MONITORING_IMAGE`-Default in `docker-compose.yml` zeigt jetzt
  auf den Registry-Pfad statt den nicht-pullbaren lokalen Tag.

### Changed

- Versions-Bump aller Komponenten auf `v0.22.1` (Patch-Release).

## [0.22.0] - 2026-05-02

### Changed

- Koordinierter Versions-Bump aller Komponenten auf `v0.22.0`
  (Server, Web-Admin-Panel, Desktop-Client, Browser-Extension,
  Go-Agent via `.gitlab-ci.yml AGENT_VERSION`, Doku-Footer in
  40 HTML-Dateien). Sammel-Release ohne funktionale Aenderungen.

### Fixed

- CI-Job `server_test` scheiterte mit `pytest: command not found`,
  weil `pytest` und `testcontainers` nur lokal im venv installiert
  waren, nicht in `requirements.txt`. Neu: `requirements-dev.txt`
  mit `pytest`, `pytest-asyncio` und `testcontainers[postgres]`;
  CI installiert beide Files. Production-Container (Dockerfile)
  bleibt schlanker, weil testcontainers + pytest nicht mehr in
  jedem Server-Image landen.

## [0.21.0] - 2026-05-02

### Highlights

**Pre-Release-Welle**: drei groesse Stoesse parallel gefahren —
Brand-Umbenennung **SimpleRemoteManager/SRM &rarr; AdminHelper**,
**6 P0-Sicherheits-Fixes** aus dem Pre-Release-Audit, und Migration
der Server-Side-Persistenz von **SQLite auf PostgreSQL 17**
(server + monitoring). Plus 2 P1-Cleanups, Plain-JS-Desktop-Client-
Reste entfernt, Doku komplett aufgeraeumt.

Beide FastAPI-Services teilen sich einen Postgres-Cluster mit zwei
DBs (`adminhelper`, `adminhelper_monitor`). Schema-Anlage uebernimmt
jetzt **Alembic** statt `Base.metadata.create_all()`. Tests laufen
gegen ein echtes Postgres via `testcontainers` (lokal) bzw.
`services: postgres:17-alpine` (CI), nicht mehr gegen SQLite-in-memory.

22 Commits seit v0.20.0.

### Brand

- Vollstaendige Umbenennung des Projekts von "SimpleRemoteManager"
  (intern auch "SRM") auf **"AdminHelper"** &mdash; in Doku, Code,
  Storage-Keys (localStorage `adminhelper_token`, `adminhelper_refresh_token`,
  `adminhelper_language`), Tauri-Keyring-Service (`com.adminhelper.app`),
  Browser-Extension, FRP-Provision-Token-Prefix, Go-Agent-Variablen.
- GitLab-Repo migriert auf <https://git.nevondo.com/ks98/adminhelper>;
  Doku-Verweise und CHANGELOG-Release-Links aktualisiert.
- Bewusst behalten: Legacy-Paketnamen (`srm-frpc-client`, `srm-monitor-agent`,
  `srm-agent`) in DEB-`Replaces`/RPM-`Obsoletes` &mdash; werden gebraucht
  fuer DEB/RPM-Upgrades von Vorgaenger-Installationen.

### Security (Pre-Release-Audit-Fixes)

- **P0-1**: API-Key wird jetzt zusaetzlich als Query-Parameter akzeptiert
  (`?api_key=...`), nicht nur als `X-API-Key`-Header &mdash; Browser-
  Extension funktionierte vorher gar nicht.
- **P0-2**: `MONITOR_API_KEY`-Mismatch zwischen server und monitoring
  geloest; `init-secrets.sh` generiert jetzt einen synchronen Wert.
  Vorher: Default-Setup hatte 401 auf jedem `/api/monitoring/*`-Aufruf.
- **P0-3**: Authorization-Bypass im FRP-Visitor-Bundle behoben &mdash;
  Non-Admin-User ohne Server-Zuweisungen sahen vorher *alle* STCP-Tunnel
  inklusive Secret-Keys (`if server_ids:`-Logik invertiert). Plus
  5 Regression-Tests in `test_frp_permissions.py`.
- **P0-4**: Frontend-Logout invalidiert JWT jetzt auch serverseitig
  via `POST /api/auth/logout`. Vorher: Token blieb 8h gueltig nach "Abmelden".
- **P0-5**: Security-Headers-Middleware hinzugefuegt
  (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
  CSP nur fuer SPA-HTML, nicht fuer `/api/docs` (Swagger-UI braucht CDN).
- **P0-6**: Default-Admin `admin/admin` entfernt; ersetzt durch
  Bootstrap-Token-Pattern (Vaultwarden/Gitea-Style). Server schreibt
  Setup-Token in `data/.bootstrap_token`, Admin wird ueber
  `POST /api/auth/bootstrap` angelegt. 6 neue Endpoint-Tests.
- **P1-6 + P1-7**: stale `server/frontend/`-Stub-Verzeichnis entfernt,
  Dead Config `MONITOR_AGENT_API_KEYS` aus `docker-compose.yml` raus.

### Database (SQLite &rarr; PostgreSQL)

- PostgreSQL 17 als neuer `postgres`-Service in `docker-compose.yml`
  mit Healthcheck und `service_healthy`-Dependencies fuer beide Apps.
- `server/alembic/` und `monitoring/alembic/` mit initialen Migrations.
- `monitoring/docker-entrypoint.sh` neu (vorher nur `CMD`).
- Server- und Monitoring-Entrypoint warten via `pg_isready` auf die DB
  und fuehren `alembic upgrade head` vor `uvicorn`-Start aus.
- `scripts/postgres-init.sh` legt beim ersten Postgres-Start die zweite
  DB (`adminhelper_monitor`) idempotent an.
- `scripts/pg-backup.sh` + `scripts/pg-restore.sh` fuer pg_dump-basiertes
  Backup beider DBs (Custom-Format, 7-Tage-Retention).
- Optionaler `pg-backup`-Service in `docker-compose.yml` (auskommentiert
  als Opt-In-Beispiel) &mdash; taegliche Backups nach `./backups/`.
- `init-secrets.sh` erzeugt zusaetzlich `POSTGRES_PASSWORD` (32 Bytes hex).
- `psycopg[binary]>=3.1`, `alembic>=1.13` in beiden requirements.txt.
- `testcontainers[postgres]>=4.7` als dev-dependency im server.
- Server-`pytest`-Job in `.gitlab-ci.yml` (existierte vorher nicht):
  nutzt `services: postgres:17-alpine` als CI-Sidecar.
- `tests/test_alembic_consistency.py`: Drift-Detector zwischen
  `Base.metadata` und Alembic-Migrations, laeuft bei jedem CI-Run.

### Other

- Plain-JS-Desktop-Client (`desktop/src/`, ~6670 Zeilen) komplett
  geloescht &mdash; war seit v0.19.0 nur noch historisch im Repo.
  8 Migrationskontext-Kommentare in `desktop-src/` bereinigt.
- `/api/docs` Swagger-UI-Pfad in der Doku korrigiert (war faelschlich
  als `/docs` dokumentiert; `app/main.py` setzt explizit
  `docs_url='/api/docs'`).
- README + DEVELOPMENT.md auf aktuellen v0.20.0-Stand gebracht
  (Lead-Beschreibung Svelte 5, Project-Tree mit `desktop-src/` +
  `frontend-src/` als produktiven Frontends).

### Changed

- Server-Side-DBs von SQLite auf PostgreSQL umgestellt:
  - `server/app/core/database.py` + `monitoring/app/core/database.py`:
    Engine ohne `check_same_thread`, dafuer Pool (size=10, overflow=20,
    pre-ping, recycle=3600).
  - `server/app/core/config.py` + `monitoring/app/core/config.py`:
    `DATABASE_URL` aus Env mit Postgres-Default-Fallback.
- Beide Dockerfiles installieren `postgresql-client` (fuer `pg_isready`),
  kopieren `alembic/`-Folder in den Container.
- `server/tests/conftest.py` komplett neu: testcontainers-Postgres,
  SAVEPOINT-Pattern fuer Test-Isolation (kein DROP/CREATE pro Test).
- Tests jetzt 78 (77 bestehende + 1 alembic-consistency); Wallclock
  ~17s lokal (12s Container-Boot einmalig), ~8s im Cache-Lauf.

### Removed

- `_migrate_connections_json`, `_migrate_add_columns`,
  `_migrate_visitors_to_users` aus `server/app/main.py` (PRAGMA-basierte
  SQLite-only Migrationen, jetzt durch Alembic ersetzt).
- `_migrate_columns`, `_migrate_agent_keys_to_hash` aus
  `monitoring/app/main.py` (gleiches Pattern).
- `Base.metadata.create_all()` aus beiden Lifespans (Alembic ist neuer
  Schema-Owner).
- `CONNECTIONS_FILE`-Konstante aus `server/app/core/config.py`
  (Konsument war `_migrate_connections_json`).
- `desktop/src/` (Plain-JS-Frontend) und 8 SQLite-Stub-Files unter
  `server/frontend/`.

### Migration

- Bestehende lokale `data/db.sqlite3` und `data/monitor.sqlite3` sind
  obsolete und koennen geloescht werden.
- Pre-Release-Status: keine Production-Datenmigration noetig.
- Beim Update bestehender Setups vor dem ersten Restart:
  `./scripts/init-secrets.sh` ausfuehren, damit `POSTGRES_PASSWORD`
  in der `.env` steht (sonst weigert sich der Postgres-Container).
- `data/`-Verzeichnis bleibt erhalten (Bootstrap-Token, .secret_key,
  FRP-PKI), nur die DB-Datei darin ist obsolete.

### Added

- PostgreSQL 17 als neuer `postgres`-Service in `docker-compose.yml`
  mit Healthcheck und `service_healthy`-Dependencies fuer beide Apps
- `server/alembic/` und `monitoring/alembic/` mit initialen Migrations
- `monitoring/docker-entrypoint.sh` neu (vorher nur `CMD`)
- Server- und Monitoring-Entrypoint warten via `pg_isready` auf die DB
  und fuehren `alembic upgrade head` vor `uvicorn`-Start aus
- `scripts/postgres-init.sh` legt beim ersten Postgres-Start die zweite
  DB (`adminhelper_monitor`) idempotent an
- `scripts/pg-backup.sh` + `scripts/pg-restore.sh` fuer pg_dump-basiertes
  Backup beider DBs (Custom-Format, 7-Tage-Retention)
- Optionaler `pg-backup`-Service in `docker-compose.yml` (auskommentiert
  als Opt-In-Beispiel) — taegliche Backups nach `./backups/`
- `init-secrets.sh` erzeugt zusaetzlich `POSTGRES_PASSWORD` (32 Bytes hex)
- `psycopg[binary]>=3.1` und `alembic>=1.13` in beiden requirements.txt
- `testcontainers[postgres]>=4.7` als dev-dependency im server
- Server-`pytest`-Job in `.gitlab-ci.yml` (existierte vorher nicht):
  nutzt `services: postgres:17-alpine` als CI-Sidecar
- `tests/test_alembic_consistency.py`: Drift-Detector zwischen
  `Base.metadata` und Alembic-Migrations, laeuft bei jedem CI-Run

### Changed

- Server-Side-DBs von SQLite auf PostgreSQL umgestellt:
  - `server/app/core/database.py` + `monitoring/app/core/database.py`:
    Engine ohne `check_same_thread`, dafuer Pool (size=10, overflow=20,
    pre-ping, recycle=3600)
  - `server/app/core/config.py` + `monitoring/app/core/config.py`:
    `DATABASE_URL` aus Env mit Postgres-Default-Fallback
- Beide Dockerfiles installieren `postgresql-client` (fuer `pg_isready`),
  kopieren `alembic/`-Folder in den Container
- `server/tests/conftest.py` komplett neu: testcontainers-Postgres,
  SAVEPOINT-Pattern fuer Test-Isolation (kein DROP/CREATE pro Test)
- Tests jetzt 78 (77 bestehende + 1 alembic-consistency); Wallclock
  ~17s lokal (12s Container-Boot einmalig), ~8s im Cache-Lauf

### Removed

- `_migrate_connections_json`, `_migrate_add_columns`,
  `_migrate_visitors_to_users` aus `server/app/main.py` (PRAGMA-basierte
  SQLite-only Migrationen, jetzt durch Alembic ersetzt)
- `_migrate_columns`, `_migrate_agent_keys_to_hash` aus
  `monitoring/app/main.py` (gleiches Pattern)
- `Base.metadata.create_all()` aus beiden Lifespans (Alembic ist neuer
  Schema-Owner)
- `CONNECTIONS_FILE`-Konstante aus `server/app/core/config.py`
  (Konsument war `_migrate_connections_json`)

### Migration

- Bestehende lokale `data/db.sqlite3` und `data/monitor.sqlite3` sind
  obsolete und koennen geloescht werden.
- Pre-Release-Status: keine Production-Datenmigration noetig.
- Beim Update bestehender Setups vor dem ersten Restart:
  `./scripts/init-secrets.sh` ausfuehren, damit `POSTGRES_PASSWORD`
  in der `.env` steht (sonst weigert sich der Postgres-Container).
- `data/`-Verzeichnis bleibt erhalten (Bootstrap-Token, .secret_key,
  FRP-PKI), nur die DB-Datei darin ist obsolete.

## [0.20.0] - 2026-04-19

### Changed

- Koordinierter Versions-Bump ueber alle Komponenten
  (Desktop-Client, Web-Admin-Panel, Go-Agent, Browser-Extension,
  Docker-Image, CI-Pipeline) auf `v0.20.0` — Sammel-Release ohne
  funktionale Aenderungen, um alle Artefakte wieder auf einen
  gemeinsamen Versions-Stand zu heben

## [0.19.1] - 2026-04-18

### Changed

- Einmalige Prettier-Formatierung ueber `frontend-src/` (rein
  kosmetisch, 31 Dateien)

### Fixed

- CI-Failure bei `npm run lint` im Frontend behoben: ESLint 9
  Flat-Config (`eslint.config.js`) eingefuehrt, `typescript-eslint` +
  `globals` als Dev-Dependencies ergaenzt, `.prettierignore` fuer
  `frontend-src/`

## [0.19.0] - 2026-04-18

### Highlights

Big-Bang-Migration des **Desktop-Clients** von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (11 Phasen). Das alte `desktop/src/`
wurde vollstaendig durch `desktop-src/` ersetzt und baut ueber
`npm --prefix ../desktop-src run build` in den Tauri-Release.
Funktional bleibt der Client unveraendert; intern ist alles typisiert
und reaktiv ueber Stores statt DOM-imperativen Managern.

Zusaetzlich in 0.19.0: mehrere Security-Haertungen (Refresh-Token-
Rotation mit Blacklist/Reuse-Detection, Login-Rate-Limit auf Redis,
Tauri-Capability-Scoping, PKI-Bundle-Zip-Slip-Schutz), ein komplett
ueberarbeitetes Monitoring-Dashboard sowie ein Doku-Komplett-Rewrite
mit getrennten Admin- und Developer-Sektionen (DE + EN).

### Added

- `desktop-src/` als eigenstaendiges Projekt (kein Monorepo) mit
  Svelte 5 Runes, TS strict, Vite-Build, Pfad-Aliassen (`$lib`)
- Typisierte Tauri-Bridge (`src/lib/bridge/`) mit 1:1-Mapping zu allen
  24 `#[tauri::command]` Backend-Funktionen
- Store-Architektur: `sessionStore`, `connectionsStore`, `tunnelStore`,
  `monitoringStore`, `ansibleStore`, `settingsStore`, `connectFlow`,
  `passwordPrompt`, `editorStore`, `statusBarStore`
- Seiten: Dashboard, Connections (mit Live-Suche + Kind/Group-Filter),
  Monitoring (Overview/Alerts/Log mit uPlot-Charts), Ansible
  (3-Stufen-Wizard mit Server/Tag-Auswahl)
- Modals: ConnectionEditor, PasswordPrompt (Promise-Continuation),
  SettingsModal (Sync/Server-Mode, RDP-Optionen, Sprache, Logout)
- Connect-Flow mit RDP-Race-Guard (monotone Connect-ID) und
  Tunnel-Auto-Resolve fuer Server-Modus
- Vitest-Suite: 41 Tests fuer Models (connection, settings, ansible,
  monitoring) und Stores (ansible, connections)
- Monitoring-Detail: Current-Values-Panel und Status-Timeline pro Check
- Grouped-View und Tree-View fuer die Connections-Seite
- Scroll-Beschleunigung als wiederverwendbare Svelte-Action
- Refresh-Token-Rotation mit Token-Blacklist und Reuse-Detection
  (kompromittierte Tokens werden erkannt und alle Sessions der
  betroffenen User-Kette invalidiert)
- Komplette Dokumentation neu aufgesetzt: getrennte Admin- und
  Developer-Sektionen, vollstaendige EN-Spiegelung unter `docs/en/`

### Changed

- `desktop/src-tauri/tauri.conf.json` `beforeBuildCommand` zeigt auf
  `../desktop-src` statt `../src`
- Sidebar-Version-Label auf `v0.19.0`
- Monitoring-Detail auf Sektions-Dashboard umgestellt: pro Server werden
  alle Checks in typ-spezifischen Sektionen (Heartbeat, Live, Network,
  Services, Docker, Backups, ZFS, SMART) gruppiert; jede Zeile klappt
  inline auf zu Perioden-Tabs (1h/6h/24h/7d) mit Graph und Timeline
- Monitoring-Dashboard v2: Card-Layout mit typ-spezifischen Heroes,
  Master-Detail-Layout fuer die Overview, Sektions-basiertes Dashboard
  statt Card-Grid
- Connections-Liste: Card fungiert als Connect-Button, Edit-Icon nur
  noch per Hover eingeblendet, aufgeraeumte Button-Anordnung
- Login-Rate-Limit auf Redis migriert (mit In-Memory-Fallback, wenn
  Redis nicht erreichbar ist) — skaliert ueber mehrere Server-Worker
  hinweg konsistent
- Tauri-Capabilities strikt gescopt (minimale Permissions statt
  Default-Allow-All), RDP-Fenstertitel werden sanitisiert
- i18n fuer Stores, Validatoren und `timeAgo` eingefuehrt, i18n-Leaks
  in AppShell/App/Connections geschlossen
- `metricLabel` als eigenes Modul ausgelagert, toter Alert-Log-Wrapper
  entfernt

### Fixed

- RDP-Race-Condition zwischen aufeinanderfolgenden Connects ueber
  Correlation-IDs geschlossen
- `lastUsed` wird pro Connect-Modus getrennt gefuehrt (statt global)
- `trustCert`-Checkbox logisch zu RDP zugeordnet (war faelschlich
  auch bei Web aktiv)
- Transparente Modals durch fehlende `--bg-panel`- und
  `--bg-input`-CSS-Variablen beseitigt
- PKI-Bundle-Import gegen Zip-Slip und Zip-Bomb geschuetzt, erzeugte
  Secrets landen mit `0600` auf der Platte
- Visuelle Regressionen, Monitoring-TLS-Handling und i18n-Engine
  in der Desktop-UI

### Removed

- Altes Plain-JS-Frontend (`desktop/src/`) wird vom Tauri-Build nicht
  mehr verwendet (bleibt historisch im Repo erhalten, bis alle
  Referenzen entfernt sind)
- Monitoring-Card-Grid, Filter-Bar, View-Switch und Hero-Komponenten
  (`MonCheckPanel/Card/Row`, `MonFilterBar`, `MonDetailPanel`,
  `hero/Hero*.svelte`) — ersetzt durch `MonServerDashboard` +
  `section/Sec*.svelte` mit wiederverwendbarem `MonCheckLine`-Snippet

## [0.17.0] - 2026-04-18

### Highlights

Big-Bang-Migration des Web-Admin-Panels von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (12 Phasen). Das alte `server/frontend/`
wurde vollstaendig durch `frontend-src/` ersetzt und wird im Docker-Image
ueber einen Multi-Stage-Build ausgeliefert.

### Added

- Svelte 5 Frontend in `frontend-src/` mit Hash-Router, Token-Auth,
  i18n (DE/EN), Toast- und ConfirmDialog-Komponenten
- UI-Komponentenbibliothek (`Button`, `Modal`, `TagChip`, `Tabs`,
  `EmptyState`, uvm.) mit einheitlichem Design-System
- Alle 8 Produktiv-Seiten portiert: Connections, Servers, Users,
  API-Keys, Hooks, Ansible, FRP-Tunnels, Monitoring
- Monitoring-Seite mit uPlot-Charts fuer SMART-Temperaturen und
  Resource-Gauges
- Playwright E2E-Tests: Smoke-Tests fuer alle 8 Routen + Login,
  Visual-Diff Screenshots (`frontend-src/tests/e2e/`)
- CI: neue `check`-Stage mit `frontend_check` (svelte-check + lint)
  und `frontend_e2e` (Playwright mit HTML-Report-Artifact)
- Repo-Root `Dockerfile` als Multi-Stage-Build (Vite-Build ->
  Python-Runtime) und `.dockerignore`
- SMART-Health-Monitoring mit Kind-Erkennung (SATA/SAS/NVMe),
  Temperatur-Thresholds und NVMe-Bit-Dekodierung

### Changed

- `docker_server`-CI-Job: Build-Context auf Repo-Root (`-f Dockerfile .`)
- `server/app/main.py`: Static-Mounts auf Vite-Output angepasst
  (`/assets`, `/fonts`), SPA-Fallback prueft erst Datei-Existenz
- Agent-Version auf 0.17.0 synchronisiert (Desktop, Extension,
  Go-Agent-Pakete)

### Fixed

- Strict-MIME-Error auf `/assets/*.js` durch dedizierten Static-Mount
- Unterstrichene Sidebar-Menueeintraege (Browser-Default fuer `<a href>`)
- Fehlende Modal-Body-/Footer-Styles (Buttons klebten aneinander)
- Favicon-Referenz in `index.html` korrigiert (`/logo.svg`)
- Redirect nach Login via `$effect` statt nur in `onMount`

### Removed

- Altes Plain-JS-Frontend (`server/frontend/`) und separates
  `server/Dockerfile` + `server/.dockerignore`

## Vorherige Versionen

Aeltere Releases siehe Git-Tags `v0.7.0` bis `v0.16.0`.

[0.25.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.25.0
[0.24.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.24.0
[0.23.2]: https://github.com/ks98/AdminHelper/releases/tag/v0.23.2
[0.23.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.23.1
[0.22.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.22.1
[0.22.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.22.0
[0.21.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.21.0
[0.20.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.20.0
[0.19.1]: https://github.com/ks98/AdminHelper/releases/tag/v0.19.1
[0.19.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.19.0
[0.17.0]: https://github.com/ks98/AdminHelper/releases/tag/v0.17.0
