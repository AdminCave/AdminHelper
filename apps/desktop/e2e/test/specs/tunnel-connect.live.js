// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open SSH / Web / RDP connections that each resolve THROUGH an FRP STCP
// tunnel. The app enrolls a device cert (setup), logs in, AppShell auto-starts
// the visitor tunnels, and opening each linked connection sends ssh / the browser
// / xfreerdp3 to the tunnel's local port — desktop frpc visitor → frps → agent
// frpc server → the real target container. All three paths are verified at the
// target containers by desktop_e2e_connect_tunnel.sh.

import { clickItemByName, jsClick } from '../lib/live.js';

const SERVER_URL = process.env.AH_SERVER_URL;
const USER = process.env.AH_ADMIN_USER;
const PASS = process.env.AH_ADMIN_PASS;
const ENROLL_TOKEN = process.env.AH_ENROLL_TOKEN;

describe('Open SSH/Web/RDP connections over FRP tunnels', () => {
  it('enrolls, the tunnels connect, and opens each connection through its tunnel', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });

    // Device enrollment (setup) via the bridge with explicit self-signed trust.
    const err = await browser.executeAsync(
      (url, token, done) => {
        window.__TAURI__.core
          .invoke('enroll_with_token', { serverUrl: url, token, allowSelfSigned: true })
          .then(() => done(null))
          .catch((e) => done(String((e && e.message) || e)));
      },
      SERVER_URL,
      ENROLL_TOKEN,
    );
    expect(err).toBe(null);

    const inputs = await $$('.login-card input'); // serverUrl, username, password
    await inputs[0].setValue(SERVER_URL);
    await inputs[1].setValue(USER);
    await inputs[2].setValue(PASS);
    await browser.keys('Enter');
    await $('.sidebar-nav').waitForExist({ timeout: 20000 });

    // The seeded tunnels auto-start; wait until the visitor side is connected.
    const indicator = await $('.tunnel-indicator');
    await indicator.waitForExist({ timeout: 15000 });
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) === 'connected',
      { timeout: 40000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
    );

    const nav = await $$('.sidebar-nav .sidebar-item');
    await nav[1].click(); // connections
    await $('.card').waitForExist({ timeout: 15000 });

    // SSH over tunnel (no prompt) and Web over tunnel (xdg-open shim).
    await clickItemByName('.card', '.card-title', 'ssh-tunnel');
    await browser.pause(2000);
    await clickItemByName('.card', '.card-title', 'web-tunnel');
    await browser.pause(2000);

    // RDP over tunnel — the desktop shows a password prompt first.
    await clickItemByName('.card', '.card-title', 'rdp-tunnel');
    await $('.pw-panel').waitForExist({ timeout: 10000 });
    await $('.pw-panel input[type="password"]').setValue('e2e');
    await jsClick(await $('.pw-panel .btn.primary'));

    // Let all three traverse their tunnels (verified at the target containers).
    await browser.pause(7000);
  });
});
