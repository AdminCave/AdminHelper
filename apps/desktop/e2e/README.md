# Desktop end-to-end tests (WebdriverIO + tauri-driver)

Drives the **real** AdminHelper desktop app through a WebDriver session, the way
a user would. This is the only layer that exercises the actual Tauri window +
webview; the Vitest component tests in `../ui` stop at the IPC boundary.

## What it covers today

- **`test/specs/smoke.e2e.js`** — the app launches, the window is titled
  `AdminHelper`, and the Svelte frontend mounts. A second start of the same
  binary hands over to the running window and exits, and the window stays alive;
  on Linux that needs a D-Bus session bus (any desktop session has one, a bare
  shell gets one from `dbus-run-session`). No backend required (launch +
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
- **`test/specs/workspace-picker.live.js`** — the picker of the launcher (no
  `AH_E2E_WORKSPACE`): it lists the migrated "Standard" as a server workspace with
  the note on the migration once, then a local workspace is made with a colour,
  renamed and deleted (the question names it and warns of the data lost). Its own
  `wdio` run at the end of `desktop_e2e_crud.sh`, which then checks that only
  `workspaces/standard/` is left.
- **`test/specs/login-error.live.js`** — the negative auth path: a wrong password
  surfaces the inline error and never reaches the app shell. Orchestrated by
  **`../../../scripts/tests/desktop_e2e_misc.sh`**.
- **`test/specs/logout.live.js`** — signing out ends the session and returns to the
  login screen (the app shell + nav go away). Runs in the same
  `desktop_e2e_misc.sh` boot.
- **`test/specs/monitoring-alerts.live.js`** — create a webhook alert rule on the
  Monitoring "alerts" tab; the rule appears in the list after the round-trip. Runs
  in the same `desktop_e2e_misc.sh` boot (which brings monitoring up for it).
- **`test/specs/connection-editor.live.js`** — create a connection through the
  top-level Connections page editor (the standalone `ConnectionEditor`, distinct
  from the server-detail connections tab that `connection-crud` drives). Runs in
  the same `desktop_e2e_misc.sh` boot.
- **`test/specs/theme-toggle.live.js`** — the sidebar-footer theme toggle flips
  dark↔light and the choice survives a reload (the FOUC inline script re-applies
  it before the first paint). Runs in the same `desktop_e2e_misc.sh` boot.
- **`test/specs/monitoring-check.live.js`** — create an `agent_resources`
  monitoring check through the GUI on a server a real agent has pushed metrics
  for; the check appears after a reload from the monitoring service. Orchestrated
  by **`../../../scripts/tests/desktop_e2e_monitoring.sh`** (boots monitoring +
  runs a real agent first). A second step accepts the template suggestion: the
  server's Monitoring tab suggests "Linux Server — Standard" (checkbox value
  `linux-base`; on a host with Docker also "Docker Host", which the step
  unchecks), assigning it creates "Agent Heartbeat" and "System Resources" and
  ends the suggestion, then the step removes the assignment again. The step
  needs a server whose agent was built from this tree: only such an agent
  reports the `host` block the suggestion comes from, and
  `desktop_e2e_monitoring.sh` builds it (`make build-linux`). The multibox
  desktop stage runs this spec too; a partial run
  `multibox.sh --agents 0 --desktop` has no such server and fails at this step.
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
- **`test/specs/workspace-add-server.live.js`** — in the launcher (no
  `AH_E2E_WORKSPACE`): makes the server workspace "Kunde B" of a second
  installation through the picker and its editor and writes its id into a file
  for the spec below. Orchestrated by
  **`../../../scripts/tests/desktop_e2e_workspaces.sh`**.
- **`test/specs/two-installations.workspaces.js`** — two workspace processes at
  once, through `wdio.workspaces.conf.js` (WebdriverIO multiremote, the sessions
  `wsA` and `wsB`, a tauri-driver each; `npm test` does not run it): "Standard" at
  stack a and "Kunde B" at stack b, two stacks with two PKIs. A second start of
  "Standard" ends with exit 3; `wsB` holds no device identity while `wsA`
  registers; then each window registers at its stack, signs in and starts its
  tunnel, both visitors at the same server port on different local ports, and
  opens its SSH connection through its own tunnel. Orchestrated by the same
  `desktop_e2e_workspaces.sh` run (stack b on `127.0.0.2`, a fresh app data dir and
  keyring), which then checks from the targets that each SSH target saw exactly one
  SSH client, and that each workspace dir holds the connection of its own server
  only. Both workspaces start with `--workspace`: opening one from the picker is
  proven by the Rust tests alone.
- **`test/specs/workspace-delete-server.live.js`** — in the launcher (no
  `AH_E2E_WORKSPACE`), after the spec above: deletes "Kunde B" in the picker,
  confirms the question and expects a delete without the note of a revoke left
  undone (`localOnly`); the workspace is gone from the picker and from Rust. Its
  purge finds the identity of `wsB` in the keyring the runs before left under the
  same `XDG_DATA_HOME`. The same `desktop_e2e_workspaces.sh` run then checks at
  stack b that this device, open before, is revoked by itself, and that
  `workspaces/<id of Kunde B>/` is gone.

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
current. A failed build stops the run (exit 1) before any spec starts: `onPrepare`
throws a `SevereServiceError`, the only error wdio does not just log and run past,
so the specs never drive an older binary. It must be `tauri build`, **not** a plain
`cargo build` — the latter
points the webview at the dev URL (`localhost:1420`, not served) instead of the
embedded frontend. The `--config` overlay re-enables `withGlobalTauri` (the specs
reach the app via `window.__TAURI__`); production builds ship it off. Headless rendering env
(`WEBKIT_DISABLE_DMABUF_RENDERER`/`WEBKIT_DISABLE_COMPOSITING_MODE`, needed under
Xvfb) is set by the config automatically.

## CI

Deliberately **no** CI job *runs* this layer — smoke included (headless WebKit
drifts with the runner image; see the note above and `.github/workflows/ci.yml`,
where CI only installs + lints this dir, never launches the app; `npm run lint` also
runs the unit tests under `test/unit/`, which need neither a display nor Rust: one of
them starts the real wdio launcher with a fake `cargo` and checks that the failed build
stops it before any worker starts). Run
the smoke locally before a release: `cd apps/desktop/e2e && xvfb-run -a npm test`.

The **live** specs (`*.live.js`, orchestrated by `scripts/tests/desktop_e2e_*.sh`
/ `run.sh e2e` on a VM) are likewise never in CI — they boot a full stack + frps
and need a secret-service; run them locally/manually (e.g. before a release).
