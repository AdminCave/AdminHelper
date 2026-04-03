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

### Optionale Tools

```bash
# RDP-Client für Verbindungstests
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

Der Server läuft dann unter `http://127.0.0.1:8080` mit Web-Interface und API-Docs unter `/api/docs`.

**Standard-Login:** `admin` / `admin`

Umgebungsvariablen können über eine `.env`-Datei im Projektroot gesetzt werden (siehe `.env.example`).

### Server (Docker)

```bash
# Im Projektroot:
cp .env.example .env
# .env anpassen

docker compose up -d
```

### Client (Tauri)

```bash
cd client/src-tauri
cargo tauri dev
```

Der Client öffnet sich als Desktop-Fenster. Änderungen am Frontend (`client/src/`) werden live übernommen, Rust-Änderungen lösen einen Rebuild aus.

### Chrome Extension

1. `chrome://extensions` öffnen → **Entwicklermodus** aktivieren
2. **"Entpackt laden"** → Verzeichnis `extension/` auswählen
3. Nach Code-Änderungen: Extension in Chrome neu laden

---

## Typische Workflows

### Client + Server gleichzeitig

Zwei Terminals öffnen:

```bash
# Terminal 1: Server
cd server && source venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# Terminal 2: Client
cd client/src-tauri
cargo tauri dev
```

Im Client dann Sync-Modus aktivieren und auf `http://127.0.0.1:8080/api/connections?api_key=<key>` zeigen.

### Nur Server-API testen

```bash
cd server && source venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# In einem anderen Terminal:
curl http://127.0.0.1:8080/api/docs
```

---

## Aufräumen

```bash
# Server venv entfernen
rm -rf server/venv

# Rust Build-Cache leeren
cd client/src-tauri && cargo clean

# Docker aufräumen
docker compose down -v
```

Alle generierten Dateien (`venv/`, `target/`, `data/`, `__pycache__/`) sind in `.gitignore` eingetragen und landen nicht im Repository.
