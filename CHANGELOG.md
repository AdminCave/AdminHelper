# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.21.0] - 2026-05-02

### Highlights

Migration der Server-Side-Persistenz von **SQLite auf PostgreSQL 17**
(server + monitoring). Beide FastAPI-Services teilen sich einen Postgres-
Cluster mit zwei DBs (`adminhelper`, `adminhelper_monitor`). Schema-Anlage
uebernimmt jetzt **Alembic** statt `Base.metadata.create_all()`. Tests
laufen gegen ein echtes Postgres via `testcontainers` (lokal) bzw.
`services: postgres:17-alpine` (CI), nicht mehr gegen SQLite-in-memory.

Plus: alle Pre-Release P0-Sicherheits-Fixes aus dem Audit, Brand-
Migration auf "AdminHelper", komplettes Doku-Refresh.

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

[0.20.0]: https://git.nevondo.com/ks98/adminhelper/-/releases/v0.20.0
[0.19.1]: https://git.nevondo.com/ks98/adminhelper/-/releases/v0.19.1
[0.19.0]: https://git.nevondo.com/ks98/adminhelper/-/releases/v0.19.0
[0.17.0]: https://git.nevondo.com/ks98/adminhelper/-/releases/v0.17.0
