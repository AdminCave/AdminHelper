# Desktop end-to-end tests (WebdriverIO + tauri-driver)

Drives the **real** AdminHelper desktop app through a WebDriver session, the way
a user would. This is the only layer that exercises the actual Tauri window +
webview; the Vitest component tests in `../ui` stop at the IPC boundary.

## What it covers today

- **`test/specs/smoke.e2e.js`** — the app launches, the window is titled
  `AdminHelper`, and the Svelte frontend mounts. No backend required (launch +
  render happen before any server call). This is the harness's foundation. Run
  it standalone with `npm test` (headless: `xvfb-run -a npm test`).

> **Not a CI job.** The whole desktop E2E layer — smoke included — runs
> locally/manually, never in CI. The headless WebKit chain (tauri-driver →
> WebKitWebDriver → WebKit under xvfb) drifts with the GitHub runner image and
> ungated upstream tool versions, so it flaked and reddened `main` without
> signalling a real defect. Run it before a release / after touching the desktop
> window or webview.
- **`test/specs/tunnel-create.live.js`** — drives the app against a REAL backend:
  log in through the nginx gateway, then create a connection tunnel via the
  Infrastructure UI. The full path GUI → `api_proxy` → gateway → server →
  Postgres is exercised. This spec is NOT run by `npm test`; it is orchestrated
  by **`../../../scripts/tests/desktop_e2e_live.sh`**, which boots + seeds the
  stack, isolates the app config + keyring, runs the spec, and independently
  re-checks the created tunnel via the server API.
- **`test/specs/tunnel-start.live.js`** — the "test it" half: against a stack
  that also runs `frps`, the app enrolls a device cert, logs in, and the hub
  auto-starts a seeded STCP tunnel. Asserts the GUI tunnel indicator reaches
  "connected"; the orchestrator
  **`../../../scripts/tests/desktop_e2e_tunnel.sh`** then independently checks the
  `frps` log for the desktop's `frpc` login — proving the full PKI + mTLS +
  enrollment chain.
- **`test/specs/*-crud.live.js`** — GUI CRUD journeys against a real stack:
  create/rename/delete a connection, create/rename/delete a tunnel, and
  create/delete a server. Each step is verified by the reloaded list (the
  GUI → gateway → server → DB round-trip). Shared login/navigation helpers live
  in `test/lib/`; orchestrated by
  **`../../../scripts/tests/desktop_e2e_crud.sh`**.
- **`test/specs/provisioning.live.js`** — mint an agent-enrollment token through
  the GUI; the server issues it and the GUI lists it (round-trip). Runs in the
  same `desktop_e2e_crud.sh` boot.
- **`test/specs/settings-mode.live.js`** — switch the app mode (server → local) in
  Settings; the server session ends and the server-only UI (mode badge, the
  Infrastructure nav) changes. Runs last in the `desktop_e2e_crud.sh` boot.
- **`test/specs/login-error.live.js`** — the negative auth path: a wrong password
  surfaces the inline error and never reaches the app shell.
- **`test/specs/logout.live.js`** — signing out ends the session and returns to the
  login screen (the app shell + nav go away).
- **`test/specs/monitoring-alerts.live.js`** — create a webhook alert rule on the
  Monitoring "alerts" tab; the rule appears in the list after the round-trip.
- **`test/specs/connection-editor.live.js`** — create a connection through the
  top-level Connections page editor (the standalone `ConnectionEditor`, distinct
  from the server-detail connections tab that `connection-crud` drives).
- **`test/specs/monitoring-check.live.js`** — create an `agent_resources`
  monitoring check through the GUI on a server a real agent has pushed metrics
  for; the check appears after a reload from the monitoring service. Orchestrated
  by **`../../../scripts/tests/desktop_e2e_monitoring.sh`** (boots monitoring +
  runs a real agent first).
- **`test/specs/ssh-connect.live.js`** / **`web-connect.live.js`** /
  **`rdp-connect.live.js`** — open an SSH / Web / RDP connection through the GUI
  (RDP also drives the password prompt). The desktop spawns `ssh` / the browser /
  `xfreerdp3` as external processes, so the orchestrator
  **`../../../scripts/tests/desktop_e2e_connect.sh`** verifies from the target
  side: the sshd log / the nginx access log (via an `xdg-open` shim on PATH) / the
  xrdp log.
- **`test/specs/tunnel-connect.live.js`** — open SSH / Web / RDP connections that
  each resolve THROUGH an FRP STCP tunnel: enroll → tunnels connect → ssh / the
  browser / xfreerdp3 traverse desktop visitor → frps → a real agent's frpc server
  (one agent, three STCP proxies) → sshd / nginx / xrdp. Orchestrated by
  **`../../../scripts/tests/desktop_e2e_connect_tunnel.sh`** (provisions a real
  agent for the server side, runs its frpc.toml under `snowdreamtech/frpc`).

## Prerequisites (Linux)

1. **WebKitWebDriver** on `PATH` — Debian/Ubuntu: `sudo apt-get install
   webkit2gtk-driver`. tauri-driver proxies to it on Linux.
2. **tauri-driver** + **Tauri CLI**: `cargo install tauri-driver --locked` and
   `cargo install tauri-cli --locked` (the harness builds via `cargo tauri build`).
3. **frpc sidecar** present at
   `../src-tauri/binaries/frpc-<target-triple>` — `cargo build` of the Tauri app
   expects the `externalBin` to resolve (the CI rust job downloads it; do the
   same locally if you've never built the app).
4. A display. Headless CI runs it under `xvfb-run`.
5. `npm ci` in this directory.

## Run

```bash
npm ci
npm test          # onPrepare builds the UI + the debug binary, then drives it
```

`wdio.conf.js` (`onPrepare`) runs
`cargo tauri build --debug --no-bundle --config tauri.e2e.conf.json` in
`../src-tauri` (which builds `../ui` via `beforeBuildCommand` and embeds it), so the
binary tauri-driver launches (`../src-tauri/target/debug/adminhelper`) is always
current. It must be `tauri build`, **not** a plain `cargo build` — the latter
points the webview at the dev URL (`localhost:1420`, not served) instead of the
embedded frontend. The `--config` overlay re-enables `withGlobalTauri` (the specs
reach the app via `window.__TAURI__`); production builds ship it off. Headless rendering env
(`WEBKIT_DISABLE_DMABUF_RENDERER`/`WEBKIT_DISABLE_COMPOSITING_MODE`, needed under
Xvfb) is set by the config automatically.

## CI

Deliberately **no** CI job *runs* this layer — smoke included (headless WebKit
drifts with the runner image; see the note above and `.github/workflows/ci.yml`,
where CI only installs + lints this dir, never launches the app). Run the smoke
locally before a release: `cd apps/desktop/e2e && xvfb-run -a npm test`.

The **live** specs (`*.live.js`, orchestrated by `scripts/tests/desktop_e2e_*.sh`
/ `run.sh e2e` on crabbox) are likewise never in CI — they boot a full stack + frps
and need a secret-service; run them locally/manually (e.g. before a release).
