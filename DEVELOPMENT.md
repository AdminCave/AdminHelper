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
cd apps/server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Go Toolchain (Agent)

```bash
# Go 1.24+ installieren (siehe https://go.dev/dl/)
sudo apt install -y golang-go
# Oder manuell:
# wget https://go.dev/dl/go1.24.2.linux-amd64.tar.gz
# sudo tar -C /usr/local -xzf go1.24.2.linux-amd64.tar.gz
```

### Docker (Server + frps + Monitoring)

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
cd apps/server
source .venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Der Server laeuft dann unter `http://127.0.0.1:8080` mit Web-Interface und API-Docs unter `/api/docs` (Swagger UI) bzw. `/openapi.json`.

**Erstanmeldung:** Es gibt keinen Default-Login mehr. Im Log nach `Setup-Token` suchen, dann mit dem Token einen Admin per `POST /api/auth/bootstrap` anlegen (siehe README). Fuer schnelle lokale Entwicklung kannst du in der `.env` `ADMIN_PASSWORD=dev` setzen — dann legt der Server beim Start einen Admin `admin/dev` direkt an.

Umgebungsvariablen koennen ueber eine `.env`-Datei im Projektroot gesetzt werden (siehe `.env.example`).

### Server + frps (Docker, empfohlen)

Fuer das vollstaendige Setup inkl. FRP-Server. Beim ersten Start einmal
die Secrets initialisieren — generiert `SECRET_KEY` und `MONITOR_API_KEY`
in der `.env`:

```bash
# Im Projektroot:
cp .env.example .env
./scripts/init-secrets.sh

docker compose up --build -d
```

Das startet:
- **Server** auf `https://localhost:443` (selbstsigniertes Zertifikat)
- **frps** auf Port 7000 (FRP-Protokoll) und 7443 (HTTPS-vhosts)
- **Monitoring** nur intern im Compose-Network (`expose 8080`, kein Host-Port); Agent-Metriken laufen tunnelfrei über den Server unter `/api/monitoring`
- **VictoriaMetrics** auf Port 8428 (intern, Time-Series DB)
- **PostgreSQL 17** (`postgres:17-alpine`, nur intern, kein Port-Mapping) — gemeinsame DB für Server (`adminhelper`) und Monitoring (`adminhelper_monitor`); die zweite DB wird beim ersten Start von `scripts/postgres-init.sh` angelegt

**Login:** `admin` / `admin`

Docker Compose laedt automatisch `docker-compose.override.yml`, falls vorhanden. Diese Datei ist in `.gitignore` und eignet sich fuer lokale Anpassungen:

```yaml
# docker-compose.override.yml (Beispiel)
services:
  server:
    build:
      context: ./server
    image: adminhelper-server:dev
    environment:
      - DOMAIN=localhost
      - ADMIN_PASSWORD=dev   # nur fuer lokale Entwicklung; Production: leer lassen + Bootstrap-Token
```

**Logs ansehen:**

```bash
docker compose logs -f server
docker compose logs -f frps
```

### Client (Tauri)

```bash
cd apps/desktop/src-tauri
cargo tauri dev
```

Der Client oeffnet sich als Desktop-Fenster. `tauri.conf.json` ruft `npm --prefix ../../apps/desktop/ui run dev` als Vite-Dev-Server auf — Aenderungen am Svelte-Frontend (`apps/desktop/ui/`) werden live uebernommen, Rust-Aenderungen loesen einen Rebuild aus. Das alte `desktop/src/` (Plain-JS) ist seit v0.19.0 historisch und wird nicht mehr gebaut.

**Hinweis:** Beim ersten Build muss eine frpc-Platzhalter-Binary existieren:

```bash
mkdir -p apps/desktop/src-tauri/binaries
touch apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
```

Diese Binary wird im CI/CD durch die echte frpc-Binary ersetzt.

### Chrome Extension

1. `chrome://extensions` oeffnen -> **Entwicklermodus** aktivieren
2. **"Entpackt laden"** -> Verzeichnis `apps/extension/` auswaehlen
3. Nach Code-Aenderungen: Extension in Chrome neu laden

### Go Agent

```bash
cd apps/agent

# Linux-Binary bauen:
make build-linux

# Windows-Binary bauen (Cross-Compile):
make build-windows

# DEB-Paket erstellen:
make deb

# RPM-Paket erstellen:
make rpm

# Alles bauen:
make all
```

Der Agent laesst sich auch direkt starten:

```bash
go run ./cmd/adminhelper-agent version
go run ./cmd/adminhelper-agent run --once
```

### Monitoring (lokal ohne Docker)

```bash
cd apps/monitoring
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

VICTORIA_METRICS_URL=http://localhost:8428 \
uvicorn app.main:app --reload --host 127.0.0.1 --port 8081
```

**Hinweis:** Fuer den vollen Monitoring-Stack wird VictoriaMetrics benoetigt, die per `docker compose up` automatisch mitgestartet wird.

---

## Client-Modi testen

Der Desktop-Client unterstuetzt drei Modi:

### Lokal-Modus

Standard. Connections werden lokal in `connections.json` gespeichert. Kein Server noetig.

### Sync-Modus

Client laedt Connections per HTTPS-URL + API-Key. Im Client: Einstellungen -> Modus: Sync -> URL eingeben.

### Server-Modus (JWT + Tunnel)

Vollstaendige Integration mit dem AdminHelper-Server:

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
cd apps/desktop/src-tauri
cargo tauri dev
```

### Nur Server-API testen

```bash
cd apps/server && source .venv/bin/activate
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
├─ apps/                     # alle lauffähigen Einheiten
│  ├─ server/                # FastAPI-Backend (modularer Monolith, 8 Module)
│  │  ├─ app/
│  │  │  ├─ main.py
│  │  │  ├─ core/                # config, auth, database, events, middleware, rate_limit
│  │  │  └─ modules/             # users, connections, servers, frp, hooks, api_keys,
│  │  │                          #   ansible, monitoring_proxy
│  │  ├─ alembic/               # DB-Migrationen
│  │  └─ requirements.txt
│  ├─ monitoring/            # eigenständiger FastAPI-Microservice (eigene DB)
│  │  ├─ app/
│  │  │  ├─ checkers/            # agent, smart, http, ping, tcp, plugins
│  │  │  ├─ routers/             # admin, agent, alerts, checks, templates
│  │  │  ├─ core/                # auth, config, database, victoria
│  │  │  └─ scheduler.py         # APScheduler für Pull-Checks
│  │  └─ Dockerfile
│  ├─ agent/                 # Unified Go Agent (Linux + Windows)
│  │  ├─ cmd/adminhelper-agent/  # Cobra CLI (run, frpc, monitor, service, version)
│  │  ├─ internal/               # config, frpc, monitor, service
│  │  ├─ deb/, rpm/              # Paket-Metadaten
│  │  ├─ systemd/                # adminhelper-agent.service + .timer
│  │  └─ Makefile                # build-linux, build-windows, deb, rpm
│  ├─ web/                   # PRODUKTIV: Svelte 5 + TS Web-Admin-Panel
│  │  ├─ src/
│  │  │  ├─ lib/api/             # 11 Module (client + 9 Domain-Wrapper + types)
│  │  │  ├─ lib/stores/          # 10 Stores
│  │  │  ├─ lib/i18n/            # DE/EN-Dictionaries
│  │  │  ├─ pages/               # 8 Produktiv-Pages + Login + Placeholder
│  │  │  └─ modals/              # 19 Modal-Komponenten
│  │  └─ tests/e2e/              # Playwright (login.spec.ts, smoke.spec.ts)
│  ├─ desktop/               # Tauri Desktop-Client (Backend + UI zusammen)
│  │  ├─ src-tauri/          # Rust/Tauri-Backend
│  │  │  ├─ src/
│  │  │  │  ├─ main.rs            # invoke_handler mit 23 Tauri-Commands
│  │  │  │  ├─ commands.rs        # IPC-Schnittstelle
│  │  │  │  ├─ auth.rs            # JWT-Login, Keyring-Persistenz
│  │  │  │  ├─ frpc.rs            # frpc-Sidecar Prozess-Management
│  │  │  │  ├─ tunnel.rs          # Tunnel-Mapping + Connection-Resolution
│  │  │  │  ├─ connection/        # SSH/RDP/Web Verbindungslogik
│  │  │  │  ├─ password.rs        # OS-Keyring (com.adminhelper.app)
│  │  │  │  ├─ ansible.rs         # Inventory-Generierung + Playbook-Ausführung
│  │  │  │  └─ ...
│  │  │  ├─ binaries/            # frpc-Sidecar (gitignored, CI-Download)
│  │  │  └─ capabilities/        # Tauri v2 Security Permissions
│  │  └─ ui/                 # PRODUKTIV: Svelte 5 + TS Desktop-Frontend
│  │     ├─ src/
│  │     │  ├─ lib/bridge/       # 22 typisierte invoke()-Wrapper
│  │     │  ├─ lib/stores/       # 12 Stores
│  │     │  ├─ lib/models/       # connection, settings, ansible, monitoring (typisiert)
│  │     │  ├─ components/       # ~30 Components
│  │     │  └─ pages/            # 4 Pages (Dashboard, Connections, Ansible, Monitoring)
│  │     └─ vitest.setup.ts      # ~41 Vitest-Unit-Tests
│  └─ extension/             # Browser-Extension (Manifest V3)
├─ docs/                     # Dokumentation (DE + EN, statisches HTML)
├─ scripts/                  # Ops-/DB-Skripte (postgres-init, init-secrets, pg-backup)
├─ data/                     # Server-Daten (gitignored, Bind-Mount)
├─ Dockerfile                # Multi-Stage: Vite-Build (apps/web) → Python-Runtime (Server-Image)
├─ docker-compose.yml
├─ docker-compose.override.yml  # Lokale Dev-Overrides (gitignored)
├─ .github/workflows/        # CI/CD (GitHub Actions): ci, docker, release
└─ .env.example
```

---

## Aufraeumen

```bash
# Server venv entfernen
rm -rf server/.venv

# Monitoring venv entfernen
rm -rf monitoring/.venv

# Rust Build-Cache leeren
cd apps/desktop/src-tauri && cargo clean

# Go Build-Cache leeren
cd apps/agent && go clean

# Docker aufraeumen
docker compose down -v

# frpc-Platzhalter entfernen
rm -rf apps/desktop/src-tauri/binaries/
```

Alle generierten Dateien (`.venv/`, `target/`, `data/`, `binaries/`, `__pycache__/`) sind in `.gitignore` eingetragen und landen nicht im Repository.
