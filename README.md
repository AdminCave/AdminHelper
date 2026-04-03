# Simple Remote Manager

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

- **Mode**: Local or Sync
- **Sync URL** and **interval** (Sync mode only)
- **Language**: German/English
- **Store passwords locally**: Optional, per-device, OS keychain (RDP only)
- **RDP scaling mode**: `auto`, `normal`, `hdpi`

---

## Server (Team-Modus)

Der optionale **Simple Remote Manager Server** ermöglicht zentrale Verwaltung und gemeinsamen Zugriff auf Verbindungen im Team.

### Features

- **Web-Interface** im gleichen Design wie der Desktop-Client
- **Benutzerrollen**: Admin (vollständige CRUD) und User (nur lesen)
- **API-Keys** für programmatischen Zugriff und Client-Sync
- **JWT-Authentifizierung** für das Web-Interface
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
POST   /api/auth/login          # Login → JWT
GET    /api/auth/me             # Aktueller Benutzer

GET    /api/connections         # Verbindungen (User + API-Key)
POST   /api/connections         # Erstellen (Admin)
PUT    /api/connections/{id}    # Bearbeiten (Admin)
DELETE /api/connections/{id}    # Löschen (Admin)

GET    /api/users               # Benutzer-Liste (Admin)
POST   /api/users               # Benutzer anlegen (Admin)
PUT    /api/users/{id}          # Benutzer bearbeiten (Admin)
DELETE /api/users/{id}          # Benutzer löschen (Admin)

GET    /api/api-keys            # API-Keys (Admin)
POST   /api/api-keys            # API-Key anlegen (Admin)
DELETE /api/api-keys/{id}       # API-Key löschen (Admin)
```

API-Dokumentation: `http://localhost:8080/api/docs`

---

## Chrome Extension

Die **Simple Remote Manager Chrome Extension** zeigt Web-Verbindungen (`kind: web`) vom Team-Server direkt als Browser-Popup an.

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
│  │  ├─ platformApi.js
│  │  ├─ settingsModel.js
│  │  └─ i18n.js
│  ├─ src-tauri/             # Rust-Backend (Tauri)
│  │  └─ src/
│  │     ├─ main.rs
│  │     ├─ commands.rs
│  │     ├─ connection/
│  │     ├─ storage.rs
│  │     ├─ sync.rs
│  │     ├─ password.rs
│  │     ├─ models.rs
│  │     ├─ validation.rs
│  │     └─ terminal.rs
│  └─ scripts/
├─ server/
│  ├─ app/                   # FastAPI-Backend (modularer Monolith)
│  │  ├─ main.py
│  │  ├─ core/               # Config, Auth, DB, Middleware
│  │  └─ modules/            # users, connections, servers, frp, hooks, api_keys
│  ├─ frontend/              # Web-Interface (HTML/CSS/JS)
│  │  ├─ index.html
│  │  ├─ css/styles.css
│  │  ├─ js/app.js
│  │  └─ assets/logo.svg
│  ├─ Dockerfile
│  └─ requirements.txt
├─ agent/                    # frpc Sync-Agent + DEB/RPM-Paketierung
│  ├─ srm-frpc-sync          # POSIX-Shell Sync-Agent
│  ├─ systemd/               # frpc.service, sync.service, sync.timer
│  ├─ deb/                   # Debian-Paket-Dateien
│  ├─ rpm/                   # RPM-Spec
│  ├─ build-deb.sh
│  └─ build-rpm.sh
├─ extension/                # Chrome Extension
│  ├─ manifest.json
│  ├─ popup.html / popup.js
│  ├─ options.html / options.js
│  └─ background.js
├─ docs/                     # Dokumentation (DE + EN)
├─ data/                     # Server-Daten (gitignored, Bind-Mount)
├─ .gitlab-ci.yml
├─ .env.example
└─ docker-compose.yml
```

---
