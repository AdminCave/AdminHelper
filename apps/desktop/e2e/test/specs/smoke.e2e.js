// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Smoke E2E: prove the whole chain works — the Tauri window opens, loads the
// embedded Svelte frontend, and mounts it. This is the cheapest meaningful
// end-to-end check and needs NO backend (it asserts only the launch + render,
// which happen before any server call). The live "create a tunnel and test it"
// flow — which needs the real stack (see scripts/tests/integration_stack_test.sh)
// plus frpc — is the next increment built on this harness.
//
// The last case starts the same binary a second time: it has to hand over to the
// running instance and leave it alive. Before tauri-plugin-single-instance,
// GApplication made the running instance re-run its setup, and it died.

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// Linux only: the hand-over runs over the D-Bus session bus, and without one the
// plugin silently does nothing. Resolved the way the plugin's zbus resolves it.
function sessionBus() {
  if (process.env.DBUS_SESSION_BUS_ADDRESS) return process.env.DBUS_SESSION_BUS_ADDRESS;
  const sock = path.join(process.env.XDG_RUNTIME_DIR || `/run/user/${process.getuid()}`, 'bus');
  try {
    if (fs.statSync(sock).isSocket()) return `unix:path=${sock}`;
  } catch {
    // no socket, no bus
  }
  return null;
}

// Starts the binary with this worker's environment — the one tauri-driver and the
// first instance inherited — and resolves when it exits or after timeoutMs.
function launchAgain(application, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(application, [], { stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const keep = (chunk) => {
      output = (output + chunk).slice(-4000);
    };
    child.stdout.on('data', keep);
    child.stderr.on('data', keep);
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      resolve({ timedOut: true, output });
    }, timeoutMs);
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ error, output });
    });
    child.on('exit', (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, output });
    });
  });
}

describe('AdminHelper desktop app', () => {
  before(async () => {
    // Wait for the embedded frontend to load and Svelte to mount before
    // asserting — the webview takes a beat to render after the session starts.
    await browser.waitUntil(
      async () =>
        browser.execute(
          () =>
            document.readyState === 'complete' &&
            !!document.querySelector('#app')?.firstElementChild,
        ),
      { timeout: 20000, timeoutMsg: 'embedded frontend did not load / Svelte did not mount' },
    );
  });

  it('opens a window titled AdminHelper', async () => {
    expect(await browser.getTitle()).toBe('AdminHelper');
  });

  it('mounts the Svelte app into #app', async () => {
    await expect($('#app')).toExist();
  });

  // Last on purpose: without the hand-over this case takes the app down.
  it('keeps the running window alive when the app is started a second time', async () => {
    if (process.platform === 'linux' && !sessionBus()) {
      throw new Error(
        'no D-Bus session bus (DBUS_SESSION_BUS_ADDRESS unset, no $XDG_RUNTIME_DIR/bus): ' +
          'the second-start check needs one, run the smoke under dbus-run-session',
      );
    }
    const application = browser.requestedCapabilities['tauri:options']?.application;
    if (!application) {
      throw new Error('the session capabilities name no tauri:options.application');
    }

    const second = await launchAgain(application, 20000);
    const tail = `\n--- second launch, last output ---\n${second.output}`;
    if (second.error) {
      throw new Error(`could not start ${application} a second time: ${second.error.message}`);
    }
    if (second.timedOut) {
      throw new Error(
        `the second launch still ran after 20 s instead of handing over to the first instance${tail}`,
      );
    }
    if (second.code !== 0) {
      throw new Error(
        `the second launch ended with ${second.signal ?? `exit code ${second.code}`}, not 0${tail}`,
      );
    }

    // Several looks, not one: the running instance dies a moment after the
    // hand-over, once it has re-run its setup.
    const until = Date.now() + 5000;
    do {
      let title;
      try {
        title = await browser.getTitle();
      } catch (error) {
        throw new Error(
          `the running instance stopped answering after the second launch: ${error.message}${tail}`,
          { cause: error },
        );
      }
      expect(title).toBe('AdminHelper');
      await browser.pause(500);
    } while (Date.now() < until);
    await expect($('#app')).toExist();
  });
});
