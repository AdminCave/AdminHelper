# AdminHelper

A lightweight Windows + Linux connection manager built with **Tauri v2 + Rust** and a fast **HTML/CSS/JS** UI. Manage SSH, RDP, and Web targets in one place with tags, search, and a clean workflow.

## Highlights

- **SSH / RDP / Web** connections in a single app
- **Filters**:
  - `Einzeln` (single connections)
  - `Zusammengefasst` (grouped by host/IP)
  - `SSH`, `RDP`, `Web`
- **List + Tree view**:
  - In single mode: tree is grouped by tags
  - In grouped mode: list is grouped by host/IP, tree is grouped by tags (with host groups inside)
- **Tags + search** for fast filtering
- **Sync mode**: load connections from a remote **HTTPS JSON** on startup and on a schedule
- **Secure by design**: passwords are **not stored by default** (optional per-device storage)
- **Localization**: German + English, auto-detected on first start (changeable later)

## Platform behavior

- **SSH**
  - Windows: opens Windows Terminal (or cmd) and runs `ssh`
  - Linux: opens the first available terminal (gnome-terminal, konsole, xfce4-terminal, xterm, alacritty, kitty, wezterm, ...)
- **RDP**
  - Windows: opens `mstsc`
  - Linux: uses **FreeRDP** (`xfreerdp3` or `xfreerdp`)
  - RDP scaling mode is configurable in settings: `auto` | `normal` | `hdpi`
  - On Linux, keyboard layout for RDP is derived from app language setting:
    - German (`de`) => German layout
    - English / default => US layout
- **Web**: opens the default browser

## Security notes

- **Passwords are not saved by default**. Optional per-device storage uses the OS keychain/credential store.
- Password storage is currently **RDP-only**. SSH uses keys and does not store passwords; Web connections do not have password fields.
- On Linux RDP, the password dialog is shown in-app and passed to FreeRDP via **stdin**.
- On Windows RDP, stored credentials are written to the Windows Credential Manager and used by `mstsc`.
- Local data files are written with **0600 permissions** on Unix systems.

## Data & settings

The app stores data in the OS-specific *app data directory*:

- `connections.json`
- `settings.json`

You can find the folder by searching for those filenames on your system.

### Sync format (HTTPS JSON)

The remote JSON must be a plain array of connection objects, e.g.:

```json
[
  {
    "id": "uuid",
    "name": "My Server",
    "kind": "ssh",
    "host": "example.com",
    "port": 22,
    "username": "user",
    "domain": "",
    "keyPath": "~/.ssh/id_ed25519",
    "url": "",
    "notes": "",
    "tags": ["prod"],
    "trustCert": false,
    "lastUsed": "2026-01-27T10:39:21.574Z"
  }
]
```

Notes:
- `kind` = `ssh` | `rdp` | `web`
- `trustCert` only affects RDP
- Sync requires **https://** URLs
- In **Sync mode**, editing/creating/deleting connections is disabled
- Passwords are **never** included in sync data

### Settings

- **Mode**: Local, Sync, or Server
- **Sync URL** and **interval** (Sync mode only)
- **Server URL** (Server mode only)
- **Language**: German/English
- **Store passwords locally**: Optional, per-device, OS keychain (RDP only)
- **RDP scaling mode**: `auto`, `normal`, `hdpi`

### Server mode (JWT + Tunnel)

In **Server mode**, the client connects to an AdminHelper server with JWT authentication:

1. Set mode to **Server** in settings, enter the server URL
2. Login with username/password — JWT is stored in the OS keyring
3. Connections are loaded from the server API
4. **frpc** starts automatically as a visitor to establish STCP/HTTPS tunnels
5. Connections with matching tunnels are resolved transparently:
   - SSH/RDP (STCP): `host` → `127.0.0.1`, `port` → visitor port
   - Web (HTTPS): URL → custom domain
   - Web (STCP): URL → `http://127.0.0.1:<visitor_port>`
6. A tunnel indicator in the header shows connection status
7. Cards show a green **"via Tunnel"** badge for tunneled connections

Session is persisted — no re-login needed on restart. Local and Sync modes remain fully functional.

---

## Server (Team-Modus)

Der optionale **AdminHelper Server** ermöglicht zentrale Verwaltung und gemeinsamen Zugriff auf Verbindungen im Team.

### Features

- **Web-Interface** im gleichen Design wie der Desktop-Client
- **Benutzerrollen**: Admin (vollständige CRUD) und User (nur lesen)
- **API-Keys** für programmatischen Zugriff und Client-Sync
- **JWT-Authentifizierung** mit Refresh-Token-Mechanismus
- **FRP-Tunnel-Verwaltung** mit Config-Generierung, Visitor-Profilen und Provisioning
- **Monitoring-Service** mit Agent-basiertem Ressourcen-Monitoring, Templates und Alerting
- **Server-Verwaltung** mit Tags, PKI/TLS-Management und Auto-Connection
- **Docker**-Deployment via GitLab-Registry

### Schnellstart

Das Server-Image wird direkt aus der GitLab-Registry gezogen:

```bash
# Im Projektroot:
cp .env.example .env
# .env anpassen: SERVER_IMAGE auf die gewünschte Registry-URL setzen

docker compose pull
docker compose up -d
```

Der Server ist dann unter `http://localhost:8080` erreichbar.

**Standard-Zugangsdaten:** `admin` / `admin` (über `ADMIN_PASSWORD` Env-Variable änderbar)

> **Wichtig:** `SECRET_KEY` in der `docker-compose.yml` vor dem Produktiveinsatz ändern.

### Persistente Daten

Die Server-Daten werden im Verzeichnis `./data/` im Projektroot gespeichert (Bind-Mount). Dieses Verzeichnis ist in `.gitignore` eingetragen und wird automatisch angelegt.

```
./data/           ← connections.json, SQLite-Datenbank, etc.
```

### Client-Sync konfigurieren

1. Im Server-Web-Interface: API-Key mit Berechtigung **"Nur lesen"** anlegen
2. Im Desktop-Client: Einstellungen → Modus: **Sync** → URL:
   ```
   http://<server>:8080/api/connections?api_key=<key>
   ```

### Server-API

```
POST   /api/auth/login          # Login -> JWT
GET    /api/auth/me             # Aktueller Benutzer

GET    /api/connections         # Verbindungen (User + API-Key)
POST   /api/connections         # Erstellen (Admin)
PUT    /api/connections/{id}    # Bearbeiten (Admin)
DELETE /api/connections/{id}    # Loeschen (Admin)

GET    /api/users               # Benutzer-Liste (Admin)
POST   /api/users               # Benutzer anlegen (Admin)
PUT    /api/users/{id}          # Benutzer bearbeiten (Admin)
DELETE /api/users/{id}          # Benutzer loeschen (Admin)

GET    /api/api-keys            # API-Keys (Admin)
POST   /api/api-keys            # API-Key anlegen (Admin)
DELETE /api/api-keys/{id}       # API-Key loeschen (Admin)

GET    /api/servers              # Server-Liste (Admin)
POST   /api/servers              # Server anlegen (Admin)
DELETE /api/servers/{id}         # Server loeschen (Admin)

GET    /api/frp/tunnels         # Tunnel-Liste (Admin)
GET    /api/frp/visitors        # Visitor-Liste (Admin)
GET    /api/frp/generate/visitor-toml  # Visitor-Config generieren
POST   /api/frp/provision/{id}/activate  # Provisioning aktivieren

GET    /api/monitoring/checks    # Monitoring-Checks (Admin)
GET    /api/monitoring/templates # Monitoring-Templates (Admin)
POST   /api/monitoring/agent-keys/{server_id}  # Agent-Key generieren
```

API-Dokumentation: `http://localhost:8080/api/docs`

---

## Chrome Extension

Die **AdminHelper Chrome Extension** zeigt Web-Verbindungen (`kind: web`) vom Team-Server direkt als Browser-Popup an.

### Features

- Verbindungen per API-Key vom Server laden
- **Sofortige Anzeige** aus dem Cache, im Hintergrund neu laden
- **Live-Suche** über Name, URL, Tags und Notizen
- **Zwei Ansichten**: flache Liste oder nach Tags gruppiert (aufklappbar)
- **Badge** am Extension-Icon zeigt Anzahl der Web-Verbindungen
- Automatisches **Hintergrund-Refresh** alle 5 Minuten
- Gleiches **Dark-Theme** wie Client und Server

### Installation

1. `chrome://extensions` öffnen → **Entwicklermodus** aktivieren
2. **"Entpackt laden"** → Verzeichnis `extension/` wählen
3. Extension-Icon klicken → Server-URL und API-Key eingeben
4. Web-Verbindungen erscheinen sofort im Popup

### Konfiguration

Über das **⚙-Icon** im Popup oder die Options-Seite:

- **Server-URL**: z.B. `http://server:8080`
- **API-Key**: Read-only API-Key aus dem Server-Web-Interface

### Einstellungen zwischen Geräten

Die Einstellungen (Server-URL, API-Key) werden über `chrome.storage.sync` gespeichert und bei aktivierter Chrome-Synchronisierung automatisch auf alle Geräte übertragen.

---

## Monitoring

Der **Monitoring-Service** läuft als separater Container neben dem Server und überwacht registrierte Server über einen leichtgewichtigen Agent.

### Features

- **Check-Typen**: Ping, TCP, HTTP, SNMP, Agent-basierte Ressourcen-Checks
- **Agent-Plugins**: CPU, RAM, Disk, Systemd Health, Docker, ZFS, Proxmox (automatisch erkannt)
- **Templates**: Monitoring-Konfigurationen als Templates definieren und an Server zuweisen
- **Alerting**: Webhook- und E-Mail-Benachrichtigungen mit konfigurierbarem Cooldown
- **Recovery-Alerts**: Automatische Benachrichtigung wenn ein Check wieder OK ist

### Agent installieren

Der **Unified Go Agent** (`adminhelper-agent`) vereint FRP-Sync und Monitoring in einem einzigen Paket fuer Linux und Windows:

```bash
# DEB installieren:
apt install ./adminhelper-agent_0.15.0_amd64.deb

# Monitoring einrichten:
sudo adminhelper-agent monitor init \
  --url https://<server>/api/monitoring \
  --api-key <KEY> \
  --server-id <SERVER-ID>

# FRP-Sync einrichten:
sudo adminhelper-agent frpc init \
  --url https://<server> \
  --token <PROVISION-TOKEN> \
  --server-id <SERVER-ID>

# Dauerbetrieb starten (FRP-Sync + Monitor-Push alle 5 Min):
sudo adminhelper-agent run

# Als systemd-Service installieren:
sudo adminhelper-agent service install
```

**Agent-Subcommands:**

| Befehl | Funktion |
|--------|----------|
| `adminhelper-agent run [--once]` | FRP-Sync + Monitor-Push (Loop oder einmalig) |
| `adminhelper-agent frpc init` | FRP-Ersteinrichtung mit Provision-Token |
| `adminhelper-agent frpc sync` | Einmaliger Config-Sync |
| `adminhelper-agent monitor init` | Monitoring-Ersteinrichtung |
| `adminhelper-agent monitor push` | Einmaliger Metriken-Push |
| `adminhelper-agent service install` | OS-Service registrieren (systemd/Windows) |
| `adminhelper-agent service uninstall` | OS-Service deregistrieren |
| `adminhelper-agent version` | Version anzeigen |

Der Agent erkennt automatisch vorhandene Subsysteme (Docker, ZFS, Proxmox) und sammelt CPU-, RAM-, Disk- und Service-Metriken. Metriken werden in **VictoriaMetrics** gespeichert (90 Tage Retention).

---

## Ansible

Die integrierte **Ansible-Verwaltung** ermoeglicht zentrale Playbook-Verwaltung ueber den Server und lokale Ausfuehrung ueber den Desktop-Client.

### Features

- **Playbook-CRUD** im Server-Web-Interface (Admin-only)
- **YAML-Validierung** beim Erstellen und Bearbeiten
- **Tag-basierte Filterung** und Suche
- **Desktop-Integration** mit 3-Schritt-Workflow:
  1. Playbook auswaehlen
  2. Ziel-Server auswaehlen (einzeln oder nach Tags)
  3. Lokal via `ansible-playbook` ausfuehren

### Voraussetzungen

- `ansible-playbook` muss auf dem Desktop-Rechner installiert sein
- Server muessen im Server-Web-Interface unter "Server" angelegt sein

### API

```
GET    /api/ansible/playbooks              # Alle Playbooks auflisten
POST   /api/ansible/playbooks              # Playbook erstellen (Admin)
GET    /api/ansible/playbooks/{id}         # Playbook-Metadaten
GET    /api/ansible/playbooks/{id}/content # YAML-Inhalt abrufen
PUT    /api/ansible/playbooks/{id}         # Playbook aktualisieren (Admin)
DELETE /api/ansible/playbooks/{id}         # Playbook loeschen (Admin)
```

Der Desktop-Client generiert automatisch ein INI-Inventory aus den ausgewaehlten Servern und startet `ansible-playbook` in einem nativen Terminal.

---

## Client – Build & Run

### Requirements

- Rust (stable)
- Tauri CLI (`cargo tauri`)
- Supported OS: Windows, Linux
- Platform WebView dependencies (see Tauri docs for your OS)
- **Linux RDP**: `xfreerdp3` or `xfreerdp`

### Dev

```bash
cd desktop/src-tauri
cargo tauri dev
```

### Build

```bash
cd desktop/src-tauri
cargo tauri build
```

> For Windows, building on **Windows** is recommended for the installer/bundler.

## Project structure

```text
.
├─ desktop/                  # Tauri Desktop-Client (SSH/RDP/Web)
│  ├─ src/                   # Frontend (HTML/CSS/JS)
│  │  ├─ index.html
│  │  ├─ styles.css
│  │  ├─ app.js
│  │  ├─ connectionModel.js
│  │  ├─ platformApi.js       # Tauri-Bridge: Auth, Connections, Tunnel, Passwords
│  │  ├─ settingsModel.js
│  │  └─ i18n.js
│  ├─ src-tauri/             # Rust-Backend (Tauri)
│  │  ├─ src/
│  │  │  ├─ main.rs
│  │  │  ├─ commands.rs       # Tauri-Commands (IPC)
│  │  │  ├─ auth.rs           # JWT-Login, Keyring-Persistenz
│  │  │  ├─ frpc.rs           # frpc-Sidecar Prozess-Management
│  │  │  ├─ tunnel.rs         # Tunnel-Mapping + Connection-Resolution
│  │  │  ├─ connection/       # SSH/RDP/Web Verbindungslogik
│  │  │  ├─ storage.rs
│  │  │  ├─ sync.rs
│  │  │  ├─ password.rs
│  │  │  ├─ models.rs
│  │  │  ├─ validation.rs
│  │  │  ├─ ansible.rs          # Inventory-Generierung + Playbook-Ausfuehrung
│  │  │  └─ terminal.rs
│  │  ├─ binaries/            # frpc-Sidecar (gitignored, CI-Download)
│  │  └─ capabilities/        # Tauri v2 Security Permissions
│  └─ scripts/
├─ server/
│  ├─ app/                   # FastAPI-Backend (modularer Monolith)
│  │  ├─ main.py
│  │  ├─ core/               # Config, Auth, DB, Middleware
│  │  └─ modules/            # users, connections, servers, frp, hooks, api_keys, ansible, monitoring_proxy
│  ├─ frontend/              # Web-Interface (HTML/CSS/JS)
│  ├─ Dockerfile
│  └─ requirements.txt
├─ monitoring/
│  ├─ app/                   # FastAPI Monitoring-Service
│  │  ├─ main.py
│  │  ├─ models.py           # Checks, States, Templates, AlertRules, AgentKeys
│  │  ├─ routers/            # checks, templates, alerts, agent, admin
│  │  ├─ core/               # Config, Auth, DB
│  │  └─ scheduler.py        # APScheduler fuer periodische Checks
│  └─ Dockerfile
├─ agent-go/                 # Unified Go Agent (Linux + Windows)
│  ├─ cmd/adminhelper-agent/         # Cobra CLI (run, frpc, monitor, service, version)
│  ├─ internal/              # Config, FRPC-Sync, Monitor, Service-Verwaltung
│  ├─ deb/                   # Debian-Paketierung
│  ├─ rpm/                   # RPM-Paketierung
│  ├─ systemd/               # adminhelper-agent.service + adminhelper-agent.timer
│  └─ Makefile               # build-linux, build-windows, deb, rpm
├─ extension/                # Chrome Extension
├─ docs/                     # Dokumentation (DE + EN)
├─ data/                     # Server-Daten (gitignored, Bind-Mount)
├─ docker-compose.yml
├─ docker-compose.override.yml  # Lokale Dev-Overrides (gitignored)
├─ .gitlab-ci.yml
└─ .env.example
```

---
