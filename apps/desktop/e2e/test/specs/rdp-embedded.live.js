// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: the RDP session in a tab of AdminHelper (R-1098) against xrdp 0.10 with the graphics
// pipeline (scripts/tests/xrdp-gfx), seeded as `rdp-embedded` by desktop_e2e_connect.sh. The
// settings put RDP into AdminHelper, the password prompt starts the tab, the unknown certificate
// is confirmed, the tab shows the desktop, a typed command reaches the server's xterm, and
// "Disconnect" ends it. What the GUI cannot see the orchestrator checks in the container: the
// session of e2e, the graphics pipeline and the file the typed command made. In between
// (R-1100): a smaller window gives the session a new resolution without a reconnect, the frame
// rate before and after goes to the log (IronRDP #447), and a fixed desktop at 1:1 and at 50 %
// takes a click on the same desktop point to the same coordinate.

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

// What the tab sends from here on: the mouse messages of the frame socket, and whether an
// overlay (connecting, reconnecting, ended) covered the picture.
async function watchSession() {
  await browser.execute((rdp) => {
    const seen = { mouse: [], overlay: false };
    window.__rdpSeen = seen;
    const send = WebSocket.prototype.send;
    WebSocket.prototype.send = function (data) {
      if (typeof data === 'string' && data.startsWith('{"t":"mouse"')) seen.mouse.push(JSON.parse(data));
      return send.call(this, data);
    };
    new MutationObserver(() => {
      if (document.querySelector(`${rdp} .rdp-overlay`)) seen.overlay = true;
    }).observe(document.querySelector(rdp), { childList: true, subtree: true });
  }, RDP);
}

const seen = () => browser.execute(() => window.__rdpSeen);

// The resolution and the frame rate in the foot: "1280×720 · — · 12 fps · …".
async function footFigures() {
  const text = await $(`${RDP} .rdp-foot span`).getText();
  const size = /(\d+)×(\d+)/.exec(text);
  const fps = /(\d+) fps/.exec(text);
  return {
    width: size ? Number(size[1]) : 0,
    height: size ? Number(size[2]) : 0,
    fps: fps ? Number(fps[1]) : null,
  };
}

const canvasSize = () =>
  browser.execute((sel) => {
    const canvas = document.querySelector(sel);
    return { width: canvas.width, height: canvas.height };
  }, CANVAS);

// A pointer move onto the desktop point (x, y) as the canvas shows it now, and the coordinate
// the tab sent for it.
async function moveTo(x, y) {
  const before = (await seen()).mouse.length;
  await browser.execute(
    (sel, px, py) => {
      const canvas = document.querySelector(sel);
      const box = canvas.getBoundingClientRect();
      const clientX = box.left + (px * box.width) / canvas.width;
      const clientY = box.top + (py * box.height) / canvas.height;
      canvas.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX, clientY, pointerId: 1 }));
    },
    CANVAS,
    x,
    y,
  );
  await browser.waitUntil(async () => (await seen()).mouse.length > before, {
    timeout: 5000,
    timeoutMsg: 'the tab sent no mouse message for a move over the picture',
  });
  const { mouse } = await seen();
  return mouse.at(-1);
}

async function chooseWindowMode(mode) {
  await browser.execute(
    (sel, value) => {
      const el = document.querySelector(sel);
      el.value = value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    },
    `${RDP} .rdp-bar select[id^="rdp-window-"]`,
    mode,
  );
}

const ZOOM_OUT = `${RDP} .rdp-bar button:is([aria-label="Verkleinern"], [aria-label="Zoom out"])`;

// Marks of the orchestrator's watcher on the container (desktop_e2e_connect.sh).
function mark(name) {
  const dir = process.env.AH_RDP_MARKS;
  if (!dir) throw new Error('AH_RDP_MARKS is not set: run through scripts/tests/desktop_e2e_connect.sh');
  return existsSync(join(dir, name));
}

describe('RDP in a tab of AdminHelper (R-1098)', () => {
  it('shows the remote desktop, sends keys to it, follows the window, zooms and disconnects', async () => {
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

    // Resize (R-1100): a smaller window, after the pause the session has the size of the tab,
    // the same picture without a reconnect.
    await watchSession();
    await browser.pause(3000); // a second of stats at least, for the frame rate before
    const before = await footFigures();
    expect(before.width).toBeGreaterThan(0);
    const { width: winWidth, height: winHeight } = await browser.getWindowSize();
    await browser.setWindowSize(winWidth - 240, winHeight - 160);
    await browser.waitUntil(
      async () => {
        const now = await footFigures();
        const canvas = await canvasSize();
        return (
          now.width > 0 &&
          (now.width !== before.width || now.height !== before.height) &&
          now.width === canvas.width &&
          now.height === canvas.height
        );
      },
      { timeout: 20000, interval: 250, timeoutMsg: 'the session never took the new size of the tab' },
    );
    await browser.pause(3000);
    const after = await footFigures();
    console.log(
      `[rdp-embedded] resize ${before.width}x${before.height} -> ${after.width}x${after.height}, ` +
        `fps before ${before.fps}, after ${after.fps}`,
    );
    expect((await seen()).overlay).toBe(false);

    // Fixed at 1280x720 (no custom size seeded): at 1:1 and at 50 % a move onto the same desktop
    // point arrives as the same coordinate.
    await chooseWindowMode('custom');
    await browser.waitUntil(
      async () => {
        const now = await footFigures();
        return now.width === 1280 && now.height === 720;
      },
      { timeout: 20000, interval: 250, timeoutMsg: 'the fixed desktop never had 1280x720' },
    );
    const full = await moveTo(400, 300);
    await jsClick(await $(ZOOM_OUT));
    await jsClick(await $(ZOOM_OUT));
    await $(`${RDP} .rdp-zoom`).waitUntil(async function () {
      return (await this.getText()) === '50 %';
    }, { timeout: 5000, timeoutMsg: 'the zoom never showed 50 %' });
    const half = await moveTo(400, 300);
    for (const at of [full, half]) {
      expect(Math.abs(at.x - 400)).toBeLessThanOrEqual(1);
      expect(Math.abs(at.y - 300)).toBeLessThanOrEqual(1);
    }
    expect((await seen()).overlay).toBe(false);

    await jsClick(await $(DISCONNECT));
    await browser.waitUntil(
      async () => browser.execute((sel) => document.querySelector(sel)?.classList.contains('hidden'), CANVAS),
      { timeout: 15000, timeoutMsg: 'the tab still showed the session after "Disconnect"' },
    );
    expect(await $(`${RDP} .rdp-overlay`).isExisting()).toBe(true);
  });
});
