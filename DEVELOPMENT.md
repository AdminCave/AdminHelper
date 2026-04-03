# Entwicklungsumgebung einrichten

Anleitung zum lokalen Entwickeln von Client, Server und Extension auf **Debian 13 (Trixie)**.

## Voraussetzungen

### System-Pakete installieren

```bash
sudo apt install -y \
  build-essential \
  curl \
  pkg-config \
  libssl-dev \
  libwebkit2gtk-4.1-dev \
  libjavascriptcoregtk-4.1-dev \
  libsoup-3.0-dev \
  libgtk-3-dev \
  libappindicator3-dev \
  librsvg2-dev \
  patchelf
```

### Rust Toolchain

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### Tauri CLI

```bash
cargo install tauri-cli
```

### Python venv (Server)

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Docker (Server + frps)

Docker und Docker Compose werden fuer das vollstaendige Setup mit frps benoetigt:

```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Danach neu einloggen
```

### Optionale Tools

```bash
# RDP-Client fuer Verbindungstests
sudo apt install -y freerdp3-x11

# SSH-Client (meist schon vorhanden)
sudo apt install -y openssh-client
```

---

## Entwicklung starten

### Server (lokal mit uvicorn)

```bash
cd server
source venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Der Server laeuft dann unter `http://127.0.0.1:8080` mit Web-Interface und API-Docs unter `/api/docs`.

**Standard-Login:** `admin` / `admin`

Umgebungsvariablen koennen ueber eine `.env`-Datei im Projektroot gesetzt werden (siehe `.env.example`).

### Server + frps (Docker, empfohlen)

Fuer das vollstaendige Setup inkl. FRP-Server:

```bash
# Im Projektroot:
docker compose up --build -d
```

Das startet:
- **Server** auf `https://localhost:443` (selbstsigniertes Zertifikat)
- **frps** auf Port 7000 (FRP-Protokoll) und 7443 (HTTPS-vhosts)

**Login:** `admin` / `admin`

Docker Compose laedt automatisch `docker-compose.override.yml`, falls vorhanden. Diese Datei ist in `.gitignore` und eignet sich fuer lokale Anpassungen:

```yaml
# docker-compose.override.yml (Beispiel)
services:
  server:
    build:
      context: ./server
    image: srm-server:dev
    environment:
      - DOMAIN=localhost
      - ADMIN_PASSWORD=admin
```

**Logs ansehen:**

```bash
docker compose logs -f server
docker compose logs -f frps
```

### Client (Tauri)

```bash
cd desktop/src-tauri
cargo tauri dev
```

Der Client oeffnet sich als Desktop-Fenster. Aenderungen am Frontend (`desktop/src/`) werden live uebernommen, Rust-Aenderungen loesen einen Rebuild aus.

**Hinweis:** Beim ersten Build muss eine frpc-Platzhalter-Binary existieren:

```bash
mkdir -p desktop/src-tauri/binaries
touch desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
```

Diese Binary wird im CI/CD durch die echte frpc-Binary ersetzt.

### Chrome Extension

1. `chrome://extensions` oeffnen -> **Entwicklermodus** aktivieren
2. **"Entpackt laden"** -> Verzeichnis `extension/` auswaehlen
3. Nach Code-Aenderungen: Extension in Chrome neu laden

---

## Client-Modi testen

Der Desktop-Client unterstuetzt drei Modi:

### Lokal-Modus

Standard. Connections werden lokal in `connections.json` gespeichert. Kein Server noetig.

### Sync-Modus

Client laedt Connections per HTTPS-URL + API-Key. Im Client: Einstellungen -> Modus: Sync -> URL eingeben.

### Server-Modus (JWT + Tunnel)

Vollstaendige Integration mit dem SRM-Server:

1. **Server + frps starten** (siehe oben)
2. Im Client: Einstellungen -> Modus: **Server** -> Server-URL: `https://localhost`
3. Login mit `admin` / `admin`
4. Connections werden per JWT-API geladen
5. frpc-Visitor startet automatisch im Hintergrund (wenn frpc-Binary vorhanden)

**Tunnel testen:**
- Im Server-Web-Interface: Server + Tunnel + Visitor anlegen
- Der Desktop-Client holt die Visitor-Config automatisch und startet frpc
- Verbindungen mit Tunnel zeigen ein gruenes "via Tunnel"-Badge
- SSH/RDP-Verbindungen werden automatisch ueber `127.0.0.1:<visitor_port>` aufgeloest

---

## Typische Workflows

### Client + Server gleichzeitig

Zwei Terminals oeffnen:

```bash
# Terminal 1: Server + frps (Docker)
docker compose up --build -d

# Terminal 2: Client
cd desktop/src-tauri
cargo tauri dev
```

### Nur Server-API testen

```bash
cd server && source venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# In einem anderen Terminal:
curl http://127.0.0.1:8080/api/docs
```

### Server-Login per CLI testen

```bash
# JWT holen
TOKEN=$(curl -sk https://localhost/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Connections abrufen
curl -sk https://localhost/api/connections \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Tunnel abrufen
curl -sk https://localhost/api/frp/tunnels \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## Projektstruktur

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
│  │  │  ├─ commands.rs       # Tauri-Commands (IPC-Schnittstelle)
│  │  │  ├─ auth.rs           # JWT-Login, Keyring-Persistenz
│  │  │  ├─ frpc.rs           # frpc-Sidecar Prozess-Management
│  │  │  ├─ tunnel.rs         # Tunnel-Mapping + Connection-Resolution
│  │  │  ├─ connection/       # SSH/RDP/Web Verbindungslogik
│  │  │  ├─ storage.rs
│  │  │  ├─ sync.rs           # Sync + JWT-basierter Connection-Fetch
│  │  │  ├─ password.rs
│  │  │  ├─ models.rs
│  │  │  ├─ validation.rs
│  │  │  └─ terminal.rs
│  │  ├─ binaries/            # frpc-Sidecar Binary (gitignored, CI-Download)
│  │  └─ capabilities/        # Tauri v2 Security Permissions
│  └─ scripts/
├─ server/
│  ├─ app/                   # FastAPI-Backend (modularer Monolith)
│  │  ├─ main.py
│  │  ├─ core/               # Config, Auth, DB, Middleware
│  │  └─ modules/            # users, connections, servers, frp, hooks, api_keys
│  ├─ frontend/              # Web-Interface (HTML/CSS/JS)
│  ├─ Dockerfile
│  └─ requirements.txt
├─ agent/                    # frpc Sync-Agent + DEB/RPM-Paketierung
│  ├─ srm-frpc-sync          # POSIX-Shell Sync-Agent
│  ├─ systemd/               # frpc.service, sync.service, sync.timer
│  ├─ build-deb.sh
│  └─ build-rpm.sh
├─ extension/                # Chrome Extension
├─ docs/                     # Dokumentation (DE + EN)
├─ data/                     # Server-Daten (gitignored, Bind-Mount)
├─ docker-compose.yml
├─ docker-compose.override.yml  # Lokale Dev-Overrides (gitignored)
├─ .gitlab-ci.yml
└─ .env.example
```

---

## Aufraeumen

```bash
# Server venv entfernen
rm -rf server/venv

# Rust Build-Cache leeren
cd desktop/src-tauri && cargo clean

# Docker aufraeumen
docker compose down -v

# frpc-Platzhalter entfernen
rm -rf desktop/src-tauri/binaries/
```

Alle generierten Dateien (`venv/`, `target/`, `data/`, `binaries/`, `__pycache__/`) sind in `.gitignore` eingetragen und landen nicht im Repository.
