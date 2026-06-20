# Desktop end-to-end tests (WebdriverIO + tauri-driver)

Drives the **real** AdminHelper desktop app through a WebDriver session, the way
a user would. This is the only layer that exercises the actual Tauri window +
webview; the Vitest component tests in `../ui` stop at the IPC boundary.

## What it covers today

- **`test/specs/smoke.e2e.js`** — the app launches, the window is titled
  `AdminHelper`, and the Svelte frontend mounts. No backend required (launch +
  render happen before any server call). This is the harness's foundation. Run
  it standalone with `npm test`.
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

`wdio.conf.js` (`onPrepare`) runs `cargo tauri build --debug --no-bundle` in
`../src-tauri` (which builds `../ui` via `beforeBuildCommand` and embeds it), so the
binary tauri-driver launches (`../src-tauri/target/debug/adminhelper`) is always
current. It must be `tauri build`, **not** a plain `cargo build` — the latter
points the webview at the dev URL (`localhost:1420`, not served) instead of the
embedded frontend. Headless rendering env
(`WEBKIT_DISABLE_DMABUF_RENDERER`/`WEBKIT_DISABLE_COMPOSITING_MODE`, needed under
Xvfb) is set by the config automatically.

## CI

Only the **smoke** spec runs in CI: the `desktop-e2e` job (GitHub Actions) runs
`npm test`, gated to `main` pushes + manual dispatch — it builds the app and
drives a real window, so it is deliberately not a per-PR gate. See
`.github/workflows/ci.yml`.

The **live** specs (`*.live.js`, orchestrated by `scripts/tests/desktop_e2e_*.sh`)
are NOT wired into CI — they boot a full stack + frps and need a secret-service;
run them locally/manually (e.g. before a release).
