# AdminHelper

Part of **[Admin Cave](https://admincave.com)** — tooling that makes admins' lives easier.

A lightweight Windows + Linux connection manager built with **Tauri v2 + Rust** and a typed **Svelte 5 + TypeScript** UI. Manage SSH, RDP, and Web targets in one place with tags, search, and a clean workflow.

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
- **Workspaces**: several servers, sync sources and sets of local connections side by side, each in a window and process of its own; a picker on start opens them
- **Sync workspaces**: load connections from a remote **HTTPS JSON** on startup and on a schedule
- **Secure by design**: passwords are **not stored by default** (optional per-device storage)
- **Localization**: German + English, auto-detected on first start (changeable later)
- **AdminCave design**: monochrome, dark-first theme with an equivalent light mode (toggle in the sidebar footer), bundled Geist font

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
- On Windows RDP, a stored password lives in the Windows Credential Manager in the app's namespace, per workspace and connection. For a start the app writes `TERMSRV/<address>` for this logon session only, which `mstsc` reads, and removes it 60 s later (not yet verified with `mstsc` on Windows).
- Local data files are written with **0600 permissions** on Unix systems.

## Data & settings

The app stores data in the OS-specific *app data directory*:

- `prefs.json` — the settings of all workspaces on this device
- `workspaces.json` — the list of workspaces
- `workspaces/<id>/workspace.json` — kind, name, colour, URL and the settings of one workspace
- `workspaces/<id>/connections.json` (server/sync cache) or `connections.local.json` (local connections)
- `port-registry.json` — the local ports of the tunnel visitors of all workspaces

The files from before workspaces (`settings.json`, `connections*.json`) stay where they were after the move into
workspaces; a `settings.json` that cannot be read is set aside as `settings.json.unreadable-<time>` and **Standard**
starts as a local workspace (see [Troubleshooting](docs/en/admin/troubleshooting.html#unreadable-settings)). Each
process writes its own log: `adminhelper.log` (launcher), `adminhelper-<id>.log` (workspace). You can find the folder
by searching for `workspaces.json` on your system.

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
- In a **Sync workspace**, editing/creating/deleting connections is disabled
- Passwords are **never** included in sync data

### Settings

- **This workspace**: name, colour and URL (shown; the workspace list changes them while the workspace is closed),
  sign-out, self-signed certificates and the pinned certificate, device identity and enrollment token, browser
  certificate, notification rules, and the **interval** of a sync workspace
- **All workspaces on this device**: **language** (German/English), **store passwords locally** (optional, OS
  keychain, RDP only), RDP options (**scaling mode** `auto`, `normal`, `hdpi`, window, performance), OS notifications,
  diagnostics

### Workspaces

A workspace has a fixed kind (**Server**, **Sync** or **Local**), a name, a colour and, for Server and Sync, a URL.
Starting `adminhelper` opens the **launcher**: a picker with all workspaces, the one used last preselected (Enter
opens it). There you create workspaces, and edit or delete a closed one; once the workspace runs, the launcher closes,
and **Workspaces…** in the window brings it back. Each workspace runs in a window and process of its own, with its
own sign-in, tunnel, device identity, stored RDP passwords and connections (the migrated workspaces share the keyring
entries from before); one workspace never runs twice, and a second start of the app opens the launcher. The window
title, a chip at the top of the sidebar, a colour stripe, confirmations, OS notifications (`[<name>] …`) and, on
Linux, the RDP window title name the workspace. Deleting a server workspace first revokes its device at the server;
deleting a local one loses its connections.

On the first start of this version the data so far moves into the workspace **Standard** in the previous mode; local
connections, a sync URL or a server URL the previous mode left unused become the workspaces **Lokal**, **Sync** and
**Server** beside it. They share the keyring entries from before among themselves, so stored passwords and the device
identity stay usable.

### Server workspace (JWT + Tunnel)

In a **server workspace**, the client connects to an AdminHelper server with JWT authentication:

1. Create a **Server** workspace with the server URL in the picker and open it
2. Login with username/password — the session stays in the client's memory; no token in the OS keyring or in the UI
3. Connections are loaded from the server API
4. **frpc** starts automatically as a visitor to establish STCP/HTTPS tunnels
5. Connections with matching tunnels are resolved transparently:
   - SSH/RDP (STCP): `host` → `127.0.0.1`, `port` → the visitor's local port (the visitor port, or a free one from 23000–23999 if that is taken)
   - Web (HTTPS): URL → custom domain
   - Web (STCP): URL → `http://127.0.0.1:<local port>`
6. A tunnel indicator in the sidebar shows connection status
7. Cards show a green **"via Tunnel"** badge for tunneled connections

In a server workspace you sign in with your password every time you open it; the server URL is the workspace's and the username is pre-filled. A user of one installation signs in in one workspace only. While the workspace runs, the client renews the session by itself; if that fails, it returns to the login screen with the notice "Session expired". Sync and local workspaces need no sign-in.

The desktop refuses a connection to a loopback address (`127.0.0.1`, `localhost`, …) whose port the port map gives
the tunnel of another workspace; start the tunnel of this workspace instead. The developer docs name the limits of
this check.

---

## Server (Team mode)

The optional **AdminHelper Server** enables centralized management and shared access to connections across a team.

### Features

- **Web admin panel** for instance administration: users, API keys, hooks, FRP server config
- **Desktop client** as the operational cockpit: server inventory, connections, FRP tunnels,
  monitoring and Ansible are all managed there in a server workspace
- **User roles**: Admin (full access) and User (scoped server access via the desktop client)
- **API keys** for programmatic access and client sync
- **JWT authentication** with refresh-token mechanism
- **FRP tunnel management** with config generation, visitor profiles, and provisioning
- **Monitoring service** with agent-based resource monitoring, templates, and alerting
- **Server management** with tags, PKI/TLS management, and auto-connection
- **PostgreSQL 17** as the shared database for server and monitoring
- **Docker** deployment via GitHub Container Registry (ghcr.io)

### Quick start (one command)

Download and run the installer — it fetches the **latest release's verified
runtime bundle** (the self-contained `docker-compose.yml` + the ops scripts,
**not** the source), brings up the stack, creates the first admin plus a one-time
enrollment token, and leaves mTLS **enforced by default**:

```bash
curl -fsSL https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/install.sh \
  | bash -s -- --domain srm.example.com
# installs the latest published release; pin a specific one with --ref vX.Y.Z
```

It prints the admin login and an **enrollment token**. Redeem the token in the
desktop client in a server workspace under *"Enroll this device with a token"* (server URL + token) — the client
generates its mTLS cert **on-device** — then log in normally; export the browser
`.p12` afterwards from the desktop. Flags: `--admin-password-file <file> … --yes`
(non-interactive; the admin password is the first line of the file, keep the file
readable only by you), `--permissive` (opt out of enforced mTLS). Updates:
`./scripts/update.sh` inside the created `adminhelper/` directory — release-bound
(moves to the latest published release, backup-first, verified bundle, automatic
rollback on a failed health check; `--ref vX.Y.Z` pins, `--check` is a dry run).
To remove a
server install completely (containers, **all** volumes incl. the root CA, the
network, `./data`/`./certs` and the `.env` secrets), run
`./scripts/uninstall.sh` there — it asks per category by default (`--yes` for
non-interactive) and keeps `./backups/` and the images unless you pass
`--purge-backups` / `--rmi`.

<details>
<summary><b>Manual / development setup</b></summary>

The production `docker-compose.yml` is a single self-contained file (images from
ghcr.io; no repo-file bind mounts). For development you can also clone the source:

```bash
git clone https://github.com/AdminCave/AdminHelper.git
cd AdminHelper

cp .env.example .env
# Generate secure random secrets (idempotent):
./scripts/init-secrets.sh

docker compose pull
docker compose up -d
# Then create the first admin + a token via the in-container CLI
# (the password goes over stdin, not into a command line):
read -rsp 'Admin password: ' ADMIN_PASSWORD; echo
printf '%s\n' "$ADMIN_PASSWORD" | docker compose exec -T server python -m app.cli create-admin \
    --username admin --password-stdin
docker compose exec server python -m app.cli mint-enroll-token --username admin
```

Under the enforced default the `:443` data plane needs a client cert, so the
certless bootstrap-token flow below requires a one-time `MTLS_ENFORCE=false`
window (or just use `install.sh`).
</details>

The web UI/API is then reachable at `https://localhost` — served by the built-in TLS gateway (nginx) on `443`, which terminates TLS and proxies to the internal `server` (the `server` and `ca-issuer` have no host port). The gateway's certificate is issued by the internal `ca-issuer` (access-signed by the internal CA), so the browser shows an "untrusted" warning until you trust the internal root CA. Enrollment is exposed on `8444`.

**First login — bootstrap-token flow:**

There is **no** default `admin/admin` login anymore. On the first start (with an empty `ADMIN_PASSWORD`), the server writes a one-time setup token to `data/.bootstrap_token` and shows it in the log:

```bash
docker compose logs server | grep -A2 'Setup-Token'
```

Use it to create the first admin:

```bash
curl -k -X POST https://localhost/api/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"token":"<TOKEN>","username":"admin","password":"<your-password>"}'
```

The response directly contains `access_token` + `refresh_token` — no additional login required. The token file is automatically deleted after the bootstrap.

> **Why `init-secrets.sh`?** The server and monitoring containers share a `MONITOR_API_KEY` as an internal shared secret. If the value in `.env` is empty, the monitoring container generates its own random one — and the server-to-monitoring calls fail with 401, which makes the monitoring page in the web UI appear dead. The init script fixes that. It also fills the four role passwords `SERVER_DB_PASSWORD`, `SCHEDULER_DB_PASSWORD`, `MONITOR_DB_PASSWORD` and `CA_DB_PASSWORD`; without them no service starts.

### Persistent data

The structured data (connections, users, servers, tunnels, monitoring) lives in **PostgreSQL 17** (service `postgres`, image `postgres:17-alpine`). Server and monitoring share a Postgres cluster with two databases: `adminhelper` (created by the Postgres container as the default DB) and `adminhelper_monitor` (created idempotently by the one-shot service `db-init` on every start of the stack). Each service connects with a Postgres role of its own without superuser rights (`ah_server`, `ah_scheduler`, `ah_monitor`, `ah_ca`); `db-init` creates the roles. The Postgres container is reachable only internally within the Compose network (no port mapping); the data lives in the `postgres-data` volume.

File-based server data is stored in the `./data/` directory in the project root (bind mount). This directory is listed in `.gitignore` and is created automatically.

```
./data/           ← bootstrap token, .secret_key, FRP config, Ansible playbooks, certificates
```

### Configuring client sync

1. In the server web interface: create an API key with the **"Read-only"** permission
2. In the desktop client: create a **Sync** workspace in the picker with the URL:
   ```
   https://<server>/api/connections?api_key=<key>
   ```

A sync workspace presents no device certificate. Against an installation that enforces mTLS (the default of
`install.sh`) the sync therefore fails in the TLS handshake: for your own installation take a **Server** workspace
there, which loads the same connections after the sign-in. A sync workspace against your own installation works only
without enforced mTLS (`--permissive`, `MTLS_ENFORCE=false`).

### Server API

```
POST   /api/auth/login          # Login -> JWT
GET    /api/auth/me             # Current user

GET    /api/connections         # Connections (user + API key)
POST   /api/connections         # Create (admin)
PUT    /api/connections/{id}    # Edit (admin)
DELETE /api/connections/{id}    # Delete (admin)

GET    /api/users               # User list (admin)
POST   /api/users               # Create user (admin)
PUT    /api/users/{id}          # Edit user (admin)
DELETE /api/users/{id}          # Delete user (admin)

GET    /api/api-keys            # API keys (admin)
POST   /api/api-keys            # Create API key (admin)
DELETE /api/api-keys/{id}       # Delete API key (admin)

GET    /api/servers              # Server list (admin)
POST   /api/servers              # Create server (admin)
DELETE /api/servers/{id}         # Delete server (admin)

GET    /api/frp/tunnels         # Tunnel list (admin; user: enabled tunnels of assigned servers)
GET    /api/frp/visitors        # Visitor list (admin)
GET    /api/frp/generate/visitor-toml  # Generate visitor config
GET    /api/frp/provision/{id}/config       # Current frpc.toml (sync agent)
GET    /api/frp/provision/{id}/config-hash  # SHA-256 for drift sync

POST   /api/servers/{id}/provision/token     # Create provision token (admin)
GET    /api/servers/{id}/provision/tokens    # List tokens (admin)
POST   /api/servers/{id}/provision/activate  # Redeem token (X-Provision-Token)

GET    /api/monitoring/checks    # Monitoring checks (admin)
GET    /api/monitoring/templates # Monitoring templates (admin)
```

API documentation: `https://localhost/api/docs` (Swagger UI) or `/openapi.json`

### Diagnostics & bug reports

Hit a bug? On the server host, generate a **redacted** diagnostics bundle and attach it to a [GitHub issue](https://github.com/AdminCave/AdminHelper/issues/new/choose):

```bash
./scripts/diagnostics.sh            # writes adminhelper-diagnostics-<ts>.tar.gz
./scripts/diagnostics.sh --tail 1000   # more log lines per service
./scripts/diagnostics.sh --mask-hosts  # also mask IP addresses, the .env host names and the machine name
```

The bundle contains versions, service status, `compose.yml`, a sanitized `.env` (secret values masked) and recent per-service logs. The secrets of the `.env` (SECRET_KEY, passwords, SMTP user), API keys and tokens (in the access logs too), JWT and Bearer tokens are masked automatically; host names and IP addresses (domain, SANs, client addresses, the machine name) stay unless you pass `--mask-hosts`. It turns IP addresses into `<ip>` by their form, and the names and addresses from the host settings of the `.env` (domain, SANs, allowed IPs, trusted proxies, FRP server, SMTP host and sender; of a sender with a display name only the address in angle brackets, not the name) and the machine name into `<host>`; other names, such as those of managed servers or webhook targets, stay — so skim the bundle before sending. Security- and change-relevant actions are additionally recorded in an append-only **audit log** (Web UI → *Audit log*, or `GET /api/audit`).

---

## Monitoring

The **monitoring service** runs as a separate container alongside the server and monitors registered servers through a lightweight agent.

### Features

- **Check types**: Ping, TCP, HTTP, agent-based resource checks, disk-full forecast
- **Agent plugins**: CPU, RAM, Swap, Load, Disk (incl. inodes), Systemd Health, system state (pending reboot, clock sync, security updates, OOM kills; Linux), Docker, ZFS, Proxmox (auto-detected)
- **Templates**: define monitoring configurations as templates and assign them to servers — six built-in standard templates (Linux/Windows/Proxmox/Docker/ZFS/Host Ping) are seeded at startup; assignment via template modal, server dialog (opt-in), server tab, tag binding or the overview's bulk CTA
- **Alerting**: webhook and email notifications with a configurable cooldown, plus damping — `unknown` never notifies, per-metric hysteresis, host-down suppression, and maintenance windows per server or global (one-off/weekly, IANA time zone)
- **Recovery alerts**: automatic notification when a check is OK again
- **Overview**: list and tile-grid views with worst-state coloring and a 24 h heartbeat bar per server
- **Personal notifications**: per-user notification hub — a bell with a feed in the desktop client, native OS notifications, and e-mail — with per-user rules (scope all/tag/single server, minimum severity). Also surfaces security (new admin) and lifecycle events. New admin users start with a default rule (all servers / warning / bell).

### Configuration (env)

| Variable | Default | Meaning |
|---|---|---|
| `ALERT_LOG_RETENTION_DAYS` | `90` | Days the monitoring alert log is kept (daily cleanup job). |
| `VM_RETENTION` | `90d` | VictoriaMetrics metric retention (`-retentionPeriod`). Independent of the alert-log knob — the two do not sync. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | empty / `587` / empty / empty / `adminhelper@localhost` | Relay for the e-mail alert channel; the same variables the server uses for notification e-mails. Empty `SMTP_HOST` = e-mail channel off. |
| `SMTP_CA_FILE` | empty | Path inside the container to a PEM file with the relay's CA, in addition to the system CAs (not set by the default compose file; see the operations guide, "Relay with its own CA"). |

### Installing the agent

The **Unified Go Agent** (`adminhelper-agent`) combines FRP sync and monitoring in a single package for Linux and Windows. The recommended rollout is the one-liner the desktop client generates in *Infrastructure → Server → Provisioning* — it sets up the server's signed package repo (GPG-fingerprint-checked), installs the agent and provisions it with a **verified first contact** (`--ca-fp`). The one-time token is not in the one-liner: the tab shows it beside it, and the script asks for it with the input hidden (unattended rollouts pass `--token`):

```bash
curl -fsSL https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install.sh \
  | sudo bash -s -- \
  --server https://<server> \
  --server-id <SERVER-ID> --ca-fp <SHA256-FROM-THE-TAB>
```

Manual alternative (package from the [GitHub release](https://github.com/AdminCave/AdminHelper/releases) assets):

```bash
# Install the DEB:
sudo apt install ./adminhelper-agent_<version>_amd64.deb

# Full provisioning in a single call (server API key + optional monitor + optional FRP);
# --ca-fp (from the provisioning tab) verifies the first contact instead of TOFU:
sudo adminhelper-agent provision \
  --url https://<server> \
  --token <PROVISION-TOKEN> \
  --server-id <SERVER-ID> \
  --ca-fp <SHA256-FROM-THE-TAB>

# Start continuous operation (FRP sync + monitor push every 5 min):
sudo adminhelper-agent run

# Install as a systemd service:
sudo adminhelper-agent service install
```

The `provision` command redeems the token against `/api/servers/{id}/provision/activate`
and installs, depending on the response:

- Server API key (always)
- Monitor agent + key (if the monitor service is reachable)
- FRP client + frpc.toml (if the server has an FRP tunnel)
- **mTLS client certificate**: the agent generates an ECDSA key on-device and enrolls its
  cert at the internal `ca-issuer` (via the gateway). The same cert is used for the server
  pushes and the FRP tunnel and is auto-renewed — no server-minted PKI bundle anymore.

This means provisioning also works for servers **without** an FRP tunnel — up to v0.22.x
the flow was coupled to FRP. Manual setups (e.g. monitoring only) still work
via `adminhelper-agent monitor init --api-key ...`.

**Agent subcommands:**

| Command | Function |
|--------|----------|
| `adminhelper-agent provision` | Initial setup with a provision token (FRP optional, monitor optional) |
| `adminhelper-agent run [--once]` | FRP sync + monitor push (loop or one-time) |
| `adminhelper-agent frpc sync` | One-time FRP config sync |
| `adminhelper-agent monitor init` | Monitoring initial setup (manual, without token) |
| `adminhelper-agent monitor push` | One-time metrics push |
| `adminhelper-agent service install` | Register OS service (systemd/Windows) |
| `adminhelper-agent service uninstall` | Deregister OS service |
| `adminhelper-agent diagnostics` | Write a redacted diagnostics report for a bug report |
| `adminhelper-agent version` | Show version |

The agent automatically detects available subsystems (Docker, ZFS, Proxmox) and collects CPU, RAM, disk, and service metrics. Metrics are stored in **VictoriaMetrics** (90-day retention).

---

## Ansible

The integrated **Ansible management** enables playbook management and local execution in the desktop client.

### Features

- **Playbook CRUD** in the desktop client (server workspace, admin)
- **YAML validation** on creating and editing
- **Tag-based filtering** and search
- **Run workflow** in the desktop client with a 3-step flow:
  1. Select a playbook
  2. Select target servers (individually or by tags)
  3. Run locally via `ansible-playbook`

### Requirements

- `ansible-playbook` must be installed on the desktop machine
- Servers must be created in the desktop client under "Infrastructure"

### API

```
GET    /api/ansible/playbooks              # List all playbooks
POST   /api/ansible/playbooks              # Create playbook (admin)
GET    /api/ansible/playbooks/{id}         # Playbook metadata
GET    /api/ansible/playbooks/{id}/content # Retrieve YAML content
PUT    /api/ansible/playbooks/{id}         # Update playbook (admin)
DELETE /api/ansible/playbooks/{id}         # Delete playbook (admin)
```

The desktop client automatically generates an INI inventory from the selected servers and launches `ansible-playbook` in a native terminal.

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
cd apps/desktop/src-tauri
cargo tauri dev
```

### Build

```bash
cd apps/desktop/src-tauri
cargo tauri build
```

> For Windows, building on **Windows** is recommended for the installer/bundler.

## Project structure

```text
.
├─ apps/                     # all runnable / deployable units live here
│  ├─ server/                # FastAPI backend (modular monolith, 12 modules)
│  │  ├─ app/
│  │  │  ├─ main.py              # app, lifespan, auto migrations, SPA fallback
│  │  │  ├─ core/                # config, auth, database, events, middleware, rate_limit
│  │  │  └─ modules/             # users, connections, servers, frp, hooks, api_keys, ansible,
│  │  │                          #   monitoring_proxy, audit, enrollment, notifications, provisioning
│  │  ├─ alembic/               # DB migrations
│  │  └─ requirements.txt
│  ├─ monitoring/            # standalone FastAPI microservice (own DB)
│  │  ├─ app/
│  │  │  ├─ main.py
│  │  │  ├─ models.py            # Checks, States, Templates, AlertRules, AgentKeys
│  │  │  ├─ checkers/            # agent, smart, http, ping, tcp, plugins, forecast
│  │  │  ├─ routers/             # admin, agent, alerts, checks, maintenance, templates
│  │  │  ├─ core/                # auth, config, database, victoria
│  │  │  └─ scheduler.py         # APScheduler for pull checks
│  │  └─ Dockerfile             # built by docker.yml (own context)
│  ├─ ca-issuer/             # Python/FastAPI PKI enrollment plane (own mTLS, own pytest suite)
│  ├─ gateway/               # nginx reverse proxy: TLS/header/mTLS termination, rate limit
│  ├─ agent/                 # unified Go agent (Linux + Windows)
│  │  ├─ cmd/adminhelper-agent/  # Cobra CLI (run, frpc, monitor, service, version)
│  │  ├─ internal/               # config, frpc, monitor, service
│  │  ├─ deb/, rpm/              # package metadata
│  │  ├─ systemd/                # adminhelper-agent.service + .timer
│  │  └─ Makefile                # build-linux, build-windows, deb, rpm
│  ├─ web/                   # PRODUCTION: Svelte 5 + TS web admin panel
│  │  ├─ src/
│  │  │  ├─ lib/                 # API modules + stores + i18n + hash router + UI components + utils
│  │  │  ├─ pages/               # production pages + Login + placeholder
│  │  │  ├─ modals/              # modal components
│  │  │  └─ App.svelte, main.ts
│  │  └─ tests/e2e/              # Playwright E2E specs (*.spec.ts)
│  └─ desktop/               # Tauri desktop client (backend + UI together)
│     ├─ src-tauri/          # Rust/Tauri backend
│     │  ├─ src/
│     │  │  ├─ main.rs            # invoke_handler with all Tauri commands
│     │  │  ├─ commands.rs        # IPC interface
│     │  │  ├─ auth.rs            # JWT login and logout
│     │  │  ├─ session.rs         # in-memory session, one renewal path
│     │  │  ├─ frpc.rs            # frpc sidecar process
│     │  │  ├─ tunnel.rs          # tunnel mapping + connection resolution
│     │  │  ├─ connection/        # SSH/RDP/Web connection logic
│     │  │  ├─ password.rs        # OS keyring (com.admincave.adminhelper)
│     │  │  ├─ ansible.rs         # inventory generation + playbook execution
│     │  │  └─ ...
│     │  ├─ binaries/            # frpc sidecar (gitignored, CI download)
│     │  └─ capabilities/        # Tauri v2 security permissions (strictly scoped)
│     └─ ui/                 # PRODUCTION: Svelte 5 + TS desktop frontend
│        ├─ src/
│        │  ├─ lib/{bridge,stores,models,api,i18n,utils}/  # typed Tauri IPC wrappers, stores, …
│        │  ├─ components/       # Svelte components (AppShell, Login, …)
│        │  ├─ pages/            # 5 pages (Dashboard, Connections, Infrastructure, Monitoring, Ansible)
│        │  └─ main.ts
│        └─ vitest.setup.ts      # Vitest setup; the unit tests sit next to the code (src/**/*.test.ts)
├─ docs/                     # documentation (DE + EN, static HTML)
├─ scripts/                  # ops/db helpers (init-secrets, pg-backup)
├─ data/                     # server data (gitignored, bind mount)
├─ Dockerfile                # multi-stage: Vite build (apps/web) → Python runtime (server image)
├─ docker-compose.yml
├─ docker-compose.override.yml  # local dev overrides (gitignored)
├─ .github/workflows/        # CI/CD (GitHub Actions): ci, docker, release
└─ .env.example
```

---
