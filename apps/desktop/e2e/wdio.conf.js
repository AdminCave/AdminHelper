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
  mochaOpts: { ui: 'bdd', timeout: 60000 },

  // Build the debug binary tauri-driver will launch. Must be `tauri build`, NOT
  // a plain `cargo build`: a plain debug build points the webview at devUrl
  // (localhost:1420, not served here) instead of the embedded frontend, so the
  // app loads nothing. `tauri build` runs beforeBuildCommand (the UI build) and
  // embeds frontendDist; --no-bundle skips deb/AppImage packaging. Needs the
  // frpc sidecar under src-tauri/binaries/ to exist (see README).
  onPrepare: () => {
    try { fs.mkdirSync(path.join(ahOutDir, 'screenshots'), { recursive: true }); } catch { /* ignore */ }
    const r = spawnSync('cargo', ['tauri', 'build', '--debug', '--no-bundle'], {
      cwd: path.resolve(desktopDir, 'src-tauri'),
      stdio: 'inherit',
      shell: true,
    });
    if (r.status !== 0) throw new Error(`tauri build failed (${r.status})`);
  },

  // Start tauri-driver before the session so it can proxy the WebDriver requests.
  beforeSession: () => {
    tauriDriver = spawn(path.resolve(os.homedir(), '.cargo', 'bin', 'tauri-driver'), [], {
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
