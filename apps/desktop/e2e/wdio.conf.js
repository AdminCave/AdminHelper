// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// WebdriverIO + tauri-driver config for the AdminHelper desktop app, adapted
// from the official Tauri v2 example (tauri-apps/webdriver-example). On Linux
// tauri-driver proxies to WebKitWebDriver (Debian package `webkit2gtk-driver`),
// which must be on PATH, and the app must be built first (onPrepare does that).
// See README.md for the full prerequisite list.

import os from 'os';
import fs from 'fs';
import path from 'path';
import { spawn, spawnSync } from 'child_process';
import { fileURLToPath } from 'url';
import net from 'net';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const desktopDir = path.resolve(__dirname, '..');
// Auto-debug artifacts (screenshot + page source on a failing spec). crabbox_iter.sh
// pulls this dir back via -artifact-glob; run.sh exports AH_OUT_DIR (repo-root default).
const ahOutDir = process.env.AH_OUT_DIR || path.resolve(desktopDir, '../../.crabbox-out');
// The debug binary tauri-driver launches. Cargo's package name is `adminhelper`.
const application = path.resolve(desktopDir, 'src-tauri/target/debug/adminhelper');

// WebKitGTK under a virtual framebuffer (Xvfb / headless CI) hangs trying to use
// DMABUF/GPU compositing that isn't there — the WebDriver session then never
// finishes initialising and times out. Force software rendering. The app process
// inherits this env down the chain (wdio → tauri-driver → WebKitWebDriver → app).
process.env.WEBKIT_DISABLE_DMABUF_RENDERER = '1';
process.env.WEBKIT_DISABLE_COMPOSITING_MODE = '1';

let tauriDriver;
let exiting = false;

// Poll until tauri-driver's WebDriver port accepts a connection (or time out).
// Spawning the driver and immediately opening a session races the port bind —
// especially in multi-spec runs where the previous driver may still hold :4444 (4.99).
const waitPort = (port, ms) =>
  new Promise((res, rej) => {
    const t0 = Date.now();
    (function probe() {
      const s = net.connect(port, '127.0.0.1', () => {
        s.destroy();
        res();
      });
      s.on('error', () => {
        s.destroy();
        Date.now() - t0 > ms
          ? rej(new Error('tauri-driver never listened on :' + port))
          : setTimeout(probe, 250);
      });
    })();
  });

export const config = {
  host: '127.0.0.1',
  port: 4444,
  specs: ['./test/specs/**/*.e2e.js'],
  maxInstances: 1,
  capabilities: [
    {
      maxInstances: 1,
      'tauri:options': { application },
    },
  ],
  reporters: ['spec'],
  framework: 'mocha',
  // A single it can legitimately wait longer than 60s (tunnel-connect sums per-step
  // waitUntil budgets up to ~131s); the per-step waitUntils stay the real guards, so
  // lift the Mocha ceiling above their sum (4.36). bail stops a spec after its first
  // failure so dependent its don't pile on misleading follow-up errors/screenshots —
  // per-file (each spec is its own runner), other spec files still run (6.113).
  mochaOpts: { ui: 'bdd', timeout: 180000, bail: true },

  // Build the debug binary tauri-driver will launch. Must be `tauri build`, NOT
  // a plain `cargo build`: a plain debug build points the webview at devUrl
  // (localhost:1420, not served here) instead of the embedded frontend, so the
  // app loads nothing. `tauri build` runs beforeBuildCommand (the UI build) and
  // embeds frontendDist; --no-bundle skips deb/AppImage packaging. Needs the
  // frpc sidecar under src-tauri/binaries/ to exist (see README).
  //
  // --config merges tauri.e2e.conf.json onto the base config, re-enabling
  // withGlobalTauri: the specs drive the app through window.__TAURI__ (only the
  // E2E build exposes it; production ships withGlobalTauri: false).
  onPrepare: () => {
    try { fs.mkdirSync(path.join(ahOutDir, 'screenshots'), { recursive: true }); } catch { /* ignore */ }
    const r = spawnSync(
      'cargo',
      ['tauri', 'build', '--debug', '--no-bundle', '--config', 'tauri.e2e.conf.json'],
      {
        cwd: path.resolve(desktopDir, 'src-tauri'),
        stdio: 'inherit',
        shell: true,
      },
    );
    if (r.status !== 0) throw new Error(`tauri build failed (${r.status})`);
  },

  // Start tauri-driver before the session so it can proxy the WebDriver requests.
  beforeSession: async () => {
    // Prefer an explicit TAURI_DRIVER_BIN over the hardcoded cargo prefix, so a
    // package-installed tauri-driver on another prefix isn't ignored (4.99).
    const bin =
      process.env.TAURI_DRIVER_BIN || path.resolve(os.homedir(), '.cargo', 'bin', 'tauri-driver');
    tauriDriver = spawn(bin, [], {
      stdio: [null, process.stdout, process.stderr],
    });
    tauriDriver.on('error', (error) => {
      console.error('tauri-driver error:', error);
      process.exit(1);
    });
    tauriDriver.on('exit', (code) => {
      if (!exiting) {
        console.error('tauri-driver exited early with code:', code);
        process.exit(1);
      }
    });
    // Wait for :4444 to accept before wdio opens the session (avoids the race with a
    // not-yet-bound or still-releasing driver in multi-spec runs).
    await waitPort(4444, 15000);
  },

  afterSession: () => {
    exiting = true;
    tauriDriver?.kill();
  },

  // On a failing spec, capture what the GUI actually showed — headless debugging is
  // otherwise blind (WebKitWebDriver exposes no console). Best-effort, never throws.
  afterTest: async function (test, _ctx, { passed }) {
    if (passed) return;
    const safe = String(test.title || 'test').replace(/[^a-z0-9]+/gi, '_').slice(0, 60) || 'test';
    try { await browser.saveScreenshot(path.join(ahOutDir, 'screenshots', safe + '.png')); } catch { /* best-effort */ }
    try { fs.writeFileSync(path.join(ahOutDir, 'screenshots', safe + '.html'), await browser.getPageSource()); } catch { /* best-effort */ }
  },
};

// afterSession only runs once a session was created; if session init fails,
// tauri-driver would orphan and hold :4444 against the next run. Kill it on any
// process exit too (mirrors the official Tauri example).
function onShutdown(fn) {
  const cleanup = () => {
    try {
      fn();
    } finally {
      process.exit();
    }
  };
  process.on('exit', fn);
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
  process.on('SIGHUP', cleanup);
}

onShutdown(() => {
  exiting = true;
  tauriDriver?.kill();
});
