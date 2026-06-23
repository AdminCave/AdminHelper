# Entwicklungsumgebung einrichten

Anleitung zum lokalen Entwickeln von Client und Server auf **Debian 13 (Trixie)**.

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
pip install -r requirements-dev.txt   # zieht requirements.in (lose) + Test-Deps
```

### Python-Dependencies & Lockfiles

`apps/server` und `apps/monitoring` trennen **Intent** von **Lock**:

- `requirements.in` — die editierbare Quelle (lose `>=`-Constraints). Hier
  Dependencies hinzufügen/ändern.
- `requirements.txt` — die **generierte, gepinnte + gehashte** Lockfile, die der
  Production-Container per `pip install --require-hashes` installiert
  (Supply-Chain-Integrität). **Nicht von Hand editieren.**

Lock neu erzeugen (im passenden Python wie im Dockerfile, derzeit 3.12):

```bash
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/apps/server:/w" -w /w python:3.12-slim \
  sh -c "pip install -q --user pip-tools && \
         python -m piptools compile --generate-hashes \
           --output-file=requirements.txt requirements.in"
```

Tests/CI installieren `requirements.in` (lose, ungehasht) — `--require-hashes`
verträgt keine Mischung aus gehashten und ungehashten Zeilen.

**Dependency-Updates laufen agent-getrieben** (kein Dependabot mehr): Versionen
in der `.in` anheben bzw. `pip-compile --upgrade` fahren, Lock regenerieren,
Tests grün, committen. Für npm/cargo/go analog über die jeweiligen Update-Befehle.

### Python-Lint/Format (ruff)

Beide Python-Komponenten nutzen [ruff](https://docs.astral.sh/ruff/) (Lint +
Formatter, Config in `ruff.toml` im Repo-Root; CI erzwingt beides):

```bash
ruff check apps/server apps/monitoring          # Lint (mit --fix zum Beheben)
ruff format apps/server apps/monitoring         # Formatieren
```

### Go Toolchain (Agent)

```bash
# Go 1.25+ installieren (siehe https://go.dev/dl/ — go.mod verlangt 1.25)
sudo apt install -y golang-go
# Oder manuell (Version von https://go.dev/dl/ einsetzen):
# wget https://go.dev/dl/go1.25.x.linux-amd64.tar.gz
# sudo tar -C /usr/local -xzf go1.25.x.linux-amd64.tar.gz
```

### Node.js + npm (Desktop-UI und Web-Frontend)

Beide Svelte-Frontends (und `cargo tauri dev`, das den Vite-Dev-Server
startet) brauchen Node.js 22+:

```bash
# Z. B. via NodeSource oder nvm; danach in beiden Projekten:
cd apps/desktop/ui && npm ci
cd apps/web && npm ci
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
die Secrets initialisieren — generiert `SECRET_KEY`, `MONITOR_API_KEY`,
`POSTGRES_PASSWORD` und `CA_ROOT_PASSPHRASE` in der `.env`:

```bash
# Im Projektroot:
cp .env.example .env
./scripts/init-secrets.sh

docker compose pull
docker compose up -d
```

(`--build` greift nur, wenn eine `docker-compose.override.yml` mit
`build:`-Sektion existiert — die Standard-Compose nutzt fertige
ghcr.io-Images, siehe unten.)

Das startet:
- **Gateway** (nginx) als einzige öffentliche TLS-Kante auf `443` (Web/API) und `8444`
  (Enrollment); terminiert TLS und proxyt intern an den Server
- **Server** nur intern im Compose-Network (plain-HTTP `8080`, kein Host-Port); erreichbar
  über das Gateway unter `https://localhost`
- **ca-issuer** nur intern (kein Host-Port): erzeugt beim ersten Start die interne PKI und
  stellt dem Gateway sein TLS-Leaf bereit
- **frps** auf Port 7000 (FRP-Protokoll) und 7443 (HTTPS-vhosts)
- **Monitoring** nur intern im Compose-Network (`expose 8080`, kein Host-Port); Agent-Metriken laufen tunnelfrei über den Server unter `/api/monitoring`
- **VictoriaMetrics** auf Port 8428 (intern, Time-Series DB)
- **PostgreSQL 17** (`postgres:17-alpine`, nur intern, kein Port-Mapping) — gemeinsame DB für Server (`adminhelper`) und Monitoring (`adminhelper_monitor`); die zweite DB wird beim ersten Start von `scripts/postgres-init.sh` angelegt

**Erstanmeldung:** Es gibt keinen Default-Login. Entweder den
Bootstrap-Token-Flow nutzen (`docker compose logs server | grep -A2
'Setup-Token'`, dann `POST /api/auth/bootstrap` — siehe README) oder fuer
lokale Entwicklung `ADMIN_PASSWORD=dev` in der `.env`/Override setzen, dann
existiert direkt ein Admin `admin`/`dev`.

Docker Compose laedt automatisch `docker-compose.override.yml`, falls vorhanden. Diese Datei ist in `.gitignore` und eignet sich fuer lokale Anpassungen:

```yaml
# docker-compose.override.yml (Beispiel: alle Images lokal bauen)
services:
  server:
    build:
      context: .            # Server-Image baut aus dem Root-Dockerfile
      dockerfile: Dockerfile
    image: adminhelper-server:dev
    environment:
      - DOMAIN=localhost
      - ADMIN_PASSWORD=dev   # nur fuer lokale Entwicklung; Production: leer lassen + Bootstrap-Token
  monitoring:
    build:
      context: ./apps/monitoring
    image: adminhelper-monitoring:dev
  ca-issuer:
    build:
      context: ./apps/ca-issuer
    image: adminhelper-ca-issuer:dev
  gateway:
    build:
      context: ./apps/gateway
    image: adminhelper-gateway:dev
```

Mit so einer Override-Datei startet `docker compose up --build -d` den
lokal gebauten Stand.

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

Der Client oeffnet sich als Desktop-Fenster. `tauri.conf.json` ruft `npm --prefix ui run dev` (relativ zu `apps/desktop/`) als Vite-Dev-Server auf — Aenderungen am Svelte-Frontend (`apps/desktop/ui/`) werden live uebernommen, Rust-Aenderungen loesen einen Rebuild aus. Das alte `desktop/src/` (Plain-JS) ist seit v0.19.0 historisch und wird nicht mehr gebaut.

**Hinweis:** Beim ersten Build muss eine frpc-Platzhalter-Binary existieren:

```bash
mkdir -p apps/desktop/src-tauri/binaries
touch apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
```

Diese Binary wird im CI/CD durch die echte frpc-Binary ersetzt.

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
pip install -r requirements.in   # lose Quelle; requirements.txt ist die Lock

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

### Automatisierte Integrations-/E2E-Tests (Docker)

Ergaenzend zu den Komponenten-Unit-Tests fahren diese Tests den **echten** Stack
hoch — `docker-compose.yml` plus das Test-Overlay `docker-compose.test.yml`, das
die First-Party-Images aus dem Checkout baut, die Gateway-Ports auf hohe
Per-Run-Ports umlegt und das `./data`-Volume isoliert:

```bash
# From-outside: mTLS-Enrollment (CSR -> :8444) + JWT von aussen durchs Gateway
bash scripts/tests/integration_stack_test.sh

# Desktop-Live-E2E: die echte App (tauri-driver) legt ueber die GUI einen Tunnel an
bash scripts/tests/desktop_e2e_live.sh

# Desktop-Live-E2E: Tunnel STARTEN + verbinden (enrollt, +frps, prueft frps-Login)
bash scripts/tests/desktop_e2e_tunnel.sh

# Desktop-Live-E2E: GUI-CRUD (Connection/Tunnel/Server anlegen/umbenennen/loeschen)
bash scripts/tests/desktop_e2e_crud.sh

# Agent->Monitoring: echte Go-Agenten enrollen (mTLS) + pushen Metriken
# (AH_AGENTS=N fuer mehrere Agenten/Server)
bash scripts/tests/agent_monitoring_test.sh

# Desktop-Live-E2E: Monitoring-Check ueber die GUI anlegen (echte Agent-Daten)
bash scripts/tests/desktop_e2e_monitoring.sh

# Desktop-Live-E2E: Verbindung oeffnen gegen echte Ziel-Container
# (SSH -> sshd-Log, Web -> nginx-Log, RDP -> xrdp-Log)
bash scripts/tests/desktop_e2e_connect.sh

# Desktop-Live-E2E: SSH/Web/RDP ueber FRP-Tunnel, voller Durchstich
# (Desktop-Visitor -> frps -> agent-frpc -> sshd/nginx/xrdp)
bash scripts/tests/desktop_e2e_connect_tunnel.sh

# SSE-Push: Cross-Instance-Fan-out ueber echtes Redis. Zwei Server-Instanzen
# (8081/8082) an einem Postgres+Redis; SSE-Stream gegen A, Event gegen B ->
# A empfaengt den Push (beweist den Multi-Worker-Redis-Pfad). Braucht das
# Server-venv (VENV=..., Default /tmp/ah-venv).
bash scripts/tests/sse_push_e2e.sh

# Desktop-Live-E2E: SSE-Push in der echten GUI. Event injizieren -> die Glocke
# aktualisiert sich in Echtzeit (Badge erscheint << 30s-Poll = beweist Push).
bash scripts/tests/desktop_e2e_sse_push.sh
```

Gemeinsamer Boot/Seed-Code liegt in `scripts/tests/lib_e2e_stack.sh`
(+ `e2e_api.py`). Die Desktop-E2E brauchen zusaetzlich `webkit2gtk-driver`,
`xvfb`, `tauri-driver`, `tauri-cli` und `gnome-keyring`/`dbus`
(siehe `apps/desktop/e2e/README.md`).

In CI laeuft (jeweils nur auf `main`-Push/manuell, kein PR-Gate) der
From-outside-Test (`integration-stack`) und der Desktop-Smoke-E2E
(`desktop-e2e`, `npm test`). Die **Desktop-Live-E2E** (`desktop_e2e_live.sh`
+ `desktop_e2e_tunnel.sh`) laufen bewusst **nur lokal/manuell** — vor Releases
von Hand ausfuehren.

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
│  └─ desktop/               # Tauri Desktop-Client (Backend + UI zusammen)
│     ├─ src-tauri/          # Rust/Tauri-Backend
│     │  ├─ src/
│     │  │  ├─ main.rs            # invoke_handler mit 23 Tauri-Commands
│     │  │  ├─ commands.rs        # IPC-Schnittstelle
│     │  │  ├─ auth.rs            # JWT-Login, Keyring-Persistenz
│     │  │  ├─ frpc.rs            # frpc-Sidecar Prozess-Management
│     │  │  ├─ tunnel.rs          # Tunnel-Mapping + Connection-Resolution
│     │  │  ├─ connection/        # SSH/RDP/Web Verbindungslogik
│     │  │  ├─ password.rs        # OS-Keyring (com.adminhelper.app)
│     │  │  ├─ ansible.rs         # Inventory-Generierung + Playbook-Ausführung
│     │  │  └─ ...
│     │  ├─ binaries/            # frpc-Sidecar (gitignored, CI-Download)
│     │  └─ capabilities/        # Tauri v2 Security Permissions
│     └─ ui/                 # PRODUKTIV: Svelte 5 + TS Desktop-Frontend
│        ├─ src/
│        │  ├─ lib/bridge/       # 22 typisierte invoke()-Wrapper
│        │  ├─ lib/stores/       # 12 Stores
│        │  ├─ lib/models/       # connection, settings, ansible, monitoring (typisiert)
│        │  ├─ components/       # ~30 Components
│        │  └─ pages/            # 4 Pages (Dashboard, Connections, Ansible, Monitoring)
│        └─ vitest.setup.ts      # ~41 Vitest-Unit-Tests
├─ docs/                     # Dokumentation (DE + EN, statisches HTML)
├─ scripts/                  # Ops-/DB-Skripte (+ tests/: integration_stack_test, desktop_e2e_live, lib_e2e_stack)
├─ data/                     # Server-Daten (gitignored, Bind-Mount)
├─ Dockerfile                # Multi-Stage: Vite-Build (apps/web) → Python-Runtime (Server-Image)
├─ docker-compose.yml
├─ docker-compose.test.yml      # Test-Overlay (build aus Checkout, Ports/Volume isoliert)
├─ docker-compose.override.yml  # Lokale Dev-Overrides (gitignored)
├─ .github/workflows/        # CI/CD (GitHub Actions): ci, docker, release
└─ .env.example
```

---

## Aufraeumen

```bash
# Server venv entfernen
rm -rf apps/server/.venv

# Monitoring venv entfernen
rm -rf apps/monitoring/.venv

# Rust Build-Cache leeren (Holzhammer — naechster Build ist ein Full-Rebuild)
cd apps/desktop/src-tauri && cargo clean

# Sanfter: nur veraltete Artefakte entfernen, letzten Build behalten.
# target/ waechst sonst monoton, weil alte Dependency-/Toolchain-Versionen
# liegen bleiben. (einmalig installieren: cargo install cargo-sweep)
cargo sweep --installed       apps/desktop/src-tauri  # Reste alter Toolchains
cargo sweep --time 30         apps/desktop/src-tauri  # Artefakte aelter als 30 Tage
cargo sweep --dry-run --time 30 apps/desktop/src-tauri  # nur anzeigen, nichts loeschen

# Go Build-Cache leeren
cd apps/agent && go clean

# Docker aufraeumen
docker compose down -v

# frpc-Platzhalter entfernen
rm -rf apps/desktop/src-tauri/binaries/
```

Alle generierten Dateien (`.venv/`, `target/`, `data/`, `binaries/`, `__pycache__/`) sind in `.gitignore` eingetragen und landen nicht im Repository.
