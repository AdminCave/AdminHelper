// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// WebdriverIO multiremote config: two workspace processes of the app at the same time,
// wsA and wsB, each in its own WebDriver session behind its own tauri-driver. Only side
// by side does it show that two frpc with the same server port run next to each other.
// AH_E2E_WORKSPACE_A and AH_E2E_WORKSPACE_B name the workspaces (test/lib/app-args.js);
// build, reporters and Mocha are those of wdio.conf.js. The specs (*.workspaces.js)
// reach the sessions as the globals wsA and wsB (webdriver.io/docs/multiremote).
// Importing wdio.conf.js also sets WEBKIT_DISABLE_DMABUF_RENDERER and
// WEBKIT_DISABLE_COMPOSITING_MODE, which both drivers and apps inherit under Xvfb.

import os from 'os';
import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';
import { config as base, ahOutDir, application, waitPort } from './wdio.conf.js';
import { workspaceSessions } from './test/lib/app-args.js';

// A missing, bad or doubled id stops here, while wdio loads the config.
const sessions = workspaceSessions(process.env);

let drivers = [];
let exiting = false;

export const config = {
  specs: ['./test/specs/**/*.workspaces.js'],
  maxInstances: 1,
  // An object instead of a list is multiremote: one worker drives all sessions. Each
  // entry carries its own connection; tauri-driver listens on 127.0.0.1 only.
  capabilities: Object.fromEntries(
    sessions.map(({ name, port, args }) => [
      name,
      {
        hostname: '127.0.0.1',
        port,
        capabilities: { 'tauri:options': { application, args } },
      },
    ]),
  ),
  reporters: base.reporters,
  framework: base.framework,
  mochaOpts: base.mochaOpts,
  onPrepare: base.onPrepare,

  // One tauri-driver per session, each with its own pair of ports; both have to listen
  // before wdio opens the sessions.
  beforeSession: async () => {
    const bin =
      process.env.TAURI_DRIVER_BIN || path.resolve(os.homedir(), '.cargo', 'bin', 'tauri-driver');
    drivers = sessions.map(({ name, port, nativePort }) => {
      const driver = spawn(bin, ['--port', String(port), '--native-port', String(nativePort)], {
        stdio: [null, process.stdout, process.stderr],
      });
      driver.on('error', (error) => {
        console.error(`tauri-driver (${name}) error:`, error);
        process.exit(1);
      });
      driver.on('exit', (code) => {
        if (!exiting) {
          console.error(`tauri-driver (${name}) exited early with code:`, code);
          process.exit(1);
        }
      });
      return driver;
    });
    await Promise.all(sessions.map(({ port }) => waitPort(port, 15000)));
  },

  afterSession: () => {
    exiting = true;
    for (const driver of drivers) driver.kill();
  },

  // As in wdio.conf.js, once per session: the multiremote browser would write both
  // screenshots to one file and hand back the page sources as a list.
  afterTest: async function (test, _ctx, { passed }) {
    if (passed) return;
    const safe = String(test.title || 'test').replace(/[^a-z0-9]+/gi, '_').slice(0, 60) || 'test';
    for (const name of browser.instances) {
      const session = browser.getInstance(name);
      const file = path.join(ahOutDir, 'screenshots', `${safe}-${name}`);
      try { await session.saveScreenshot(file + '.png'); } catch { /* best-effort */ }
      try { fs.writeFileSync(file + '.html', await session.getPageSource()); } catch { /* best-effort */ }
    }
  },
};

// afterSession only runs once the sessions were created; without this the drivers of a
// failed start would hold their ports against the next run. SIGINT, SIGTERM and SIGHUP
// end in process.exit() through the handlers wdio.conf.js registers when imported.
process.on('exit', () => {
  exiting = true;
  for (const driver of drivers) driver.kill();
});
