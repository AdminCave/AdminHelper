// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: the RDP session in a tab of AdminHelper (R-1098) against xrdp 0.10 with the graphics
// pipeline (scripts/tests/xrdp-gfx), seeded as `rdp-embedded` by desktop_e2e_connect.sh. The
// settings put RDP into AdminHelper, the password prompt starts the tab, the unknown certificate
// is confirmed, the tab shows the desktop, a typed command reaches the server's xterm, and
// "Disconnect" ends it. What the GUI cannot see the orchestrator checks in the container: the
// session of e2e, the graphics pipeline and the file the typed command made.

import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { login, connectByName, CONN_ROW, jsClick } from '../lib/live.js';

const RDP = '.rdp';
const CANVAS = `${RDP} .rdp-view canvas`;
// The icon buttons carry only their label, in either UI language.
const DISCONNECT = `${RDP} .rdp-head button:is([aria-label="Trennen"], [aria-label="Disconnect"])`;

// The command the orchestrator looks for: `touch ahkey` in the home of e2e. Enter first ends
// whatever an earlier try left half typed.
const COMMAND = ['Enter', 'KeyT', 'KeyO', 'KeyU', 'KeyC', 'KeyH', 'Space', 'KeyA', 'KeyH', 'KeyK', 'KeyE', 'KeyY', 'Enter'];

async function chooseAdminHelperForRdp() {
  await $('.sidebar-bottom .sidebar-item').click();
  await $('.sm-panel').waitForExist({ timeout: 10000 });
  await $('.sm-panel [data-section="rdp"]').click();
  const select = await $('.sm-panel [data-field="rdp-client"]');
  await select.waitForDisplayed({ timeout: 10000 });
  // Set in the page like jsClick: Svelte's bind:value listens to change.
  await browser.execute((el) => {
    el.value = 'embedded';
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, select);
  await jsClick(await $('.sm-panel [data-action="settings-save"]'));
  await $('.sm-panel').waitForExist({ reverse: true, timeout: 10000 });
}

// A pointer press grabs the keyboard; then keys go to the session as scancodes. Dispatched in
// the page with their `code`, so WebKitWebDriver's key actions (and their layout) play no part.
async function typeIntoSession(codes) {
  await browser.execute(
    (canvas, list) => {
      const at = { bubbles: true, clientX: 20, clientY: 20, buttons: 0, pointerId: 1 };
      canvas.dispatchEvent(new PointerEvent('pointerdown', { ...at, buttons: 1 }));
      canvas.dispatchEvent(new PointerEvent('pointerup', at));
      const view = canvas.closest('.rdp-view');
      for (const code of list) {
        for (const type of ['keydown', 'keyup']) {
          view.dispatchEvent(new KeyboardEvent(type, { code, bubbles: true, cancelable: true }));
        }
      }
    },
    await $(CANVAS),
    codes,
  );
}

// Marks of the orchestrator's watcher on the container (desktop_e2e_connect.sh).
function mark(name) {
  const dir = process.env.AH_RDP_MARKS;
  if (!dir) throw new Error('AH_RDP_MARKS is not set: run through scripts/tests/desktop_e2e_connect.sh');
  return existsSync(join(dir, name));
}

describe('RDP in a tab of AdminHelper (R-1098)', () => {
  it('shows the remote desktop, sends keys to it and disconnects', async () => {
    await login();
    await chooseAdminHelperForRdp();

    const nav = await $$('.sidebar-nav .sidebar-item'); // dashboard / connections / infrastructure
    await nav[1].click();
    await $(CONN_ROW).waitForExist({ timeout: 15000 });

    await connectByName('rdp-embedded');
    await $('.pw-panel').waitForExist({ timeout: 10000 });
    await $('.pw-panel input[type="password"]').setValue('e2e');
    await jsClick(await $('.pw-panel .btn.primary'));

    // The container makes its certificate at every start: unknown, so the tab asks first.
    const trust = await $('.modal-panel .modal-footer .ui-btn-primary');
    await trust.waitForExist({
      timeout: 30000,
      timeoutMsg: 'the tab never asked to confirm the certificate',
    });
    await jsClick(trust);

    // Connected: the canvas shows, and the first frame gave it the desktop's size (a canvas
    // nobody drew on keeps 300x150).
    await browser.waitUntil(
      async () =>
        browser.execute((sel) => {
          const canvas = document.querySelector(sel);
          return (
            canvas !== null &&
            !canvas.classList.contains('hidden') &&
            canvas.width > 300 &&
            canvas.height > 150
          );
        }, CANVAS),
      { timeout: 45000, timeoutMsg: 'the tab never showed a picture of the remote desktop' },
    );

    // The first picture is xrdp's own screen; keys reach the xterm only once the session of
    // e2e is up and its window is there. So: wait for the session, then type until the file
    // the command makes shows in the container.
    await browser.waitUntil(async () => mark('session'), {
      timeout: 30000,
      interval: 500,
      timeoutMsg: 'xrdp never logged the session of e2e on',
    });
    let arrived = false;
    for (let attempt = 0; attempt < 5 && !arrived; attempt++) {
      await typeIntoSession(COMMAND);
      arrived = await browser
        .waitUntil(async () => mark('key'), { timeout: 4000, interval: 250 })
        .catch(() => false);
    }
    expect(arrived).toBe(true);

    await jsClick(await $(DISCONNECT));
    await browser.waitUntil(
      async () => browser.execute((sel) => document.querySelector(sel)?.classList.contains('hidden'), CANVAS),
      { timeout: 15000, timeoutMsg: 'the tab still showed the session after "Disconnect"' },
    );
    expect(await $(`${RDP} .rdp-overlay`).isExisting()).toBe(true);
  });
});
