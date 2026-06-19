# Desktop end-to-end tests (WebdriverIO + tauri-driver)

Drives the **real** AdminHelper desktop app through a WebDriver session, the way
a user would. This is the only layer that exercises the actual Tauri window +
webview; the Vitest component tests in `../ui` stop at the IPC boundary.

## What it covers today

- **`test/specs/smoke.e2e.js`** — the app launches, the window is titled
  `AdminHelper`, and the Svelte frontend mounts. No backend required (launch +
  render happen before any server call). This is the harness's foundation.

The live **"create a connection with a tunnel and test it"** flow needs the full
backend stack (`../../../scripts/tests/integration_stack_test.sh` boots it) plus
a running `frpc`, and a way to seed an authenticated session. It builds on this
harness and is the planned next increment — see the repo CHANGELOG.

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

Runs in the `desktop-e2e` job (GitHub Actions), gated to `main` pushes + manual
dispatch — it builds the app and drives a real window, so it is deliberately not
a per-PR gate. See `.github/workflows/ci.yml`.
