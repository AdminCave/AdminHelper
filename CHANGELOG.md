# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.18.0] - 2026-04-18

### Highlights

Big-Bang-Migration des **Desktop-Clients** von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (11 Phasen). Das alte `desktop/src/`
wurde vollstaendig durch `desktop-src/` ersetzt und baut ueber
`npm --prefix ../desktop-src run build` in den Tauri-Release.
Funktional bleibt der Client unveraendert; intern ist alles typisiert
und reaktiv ueber Stores statt DOM-imperativen Managern.

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

### Changed

- `desktop/src-tauri/tauri.conf.json` `beforeBuildCommand` zeigt auf
  `../desktop-src` statt `../src`
- Sidebar-Version-Label von `v0.17.0` auf `v0.18.0`

### Removed

- Altes Plain-JS-Frontend (`desktop/src/`) wird vom Tauri-Build nicht
  mehr verwendet (bleibt historisch im Repo erhalten, bis alle
  Referenzen entfernt sind)

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

[0.17.0]: https://git.ks98.de/kevin/simpleremotemanager/-/releases/v0.17.0
