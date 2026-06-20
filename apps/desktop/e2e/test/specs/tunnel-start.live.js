// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E: start a tunnel and confirm it connects (the "test it" half).
// Orchestrated by scripts/tests/desktop_e2e_tunnel.sh, which boots the stack +
// frps and seeds a server + FRP config + an STCP tunnel. Here the app enrolls a
// device cert (setup), logs in, and AppShell auto-starts the seeded tunnel; we
// assert the GUI tunnel indicator reaches "connected". The orchestrator then
// independently checks the frps log for the frpc login.

const SERVER_URL = process.env.AH_SERVER_URL;
const USER = process.env.AH_ADMIN_USER;
const PASS = process.env.AH_ADMIN_PASS;
const ENROLL_TOKEN = process.env.AH_ENROLL_TOKEN;

describe('AdminHelper desktop — start a tunnel against live frps', () => {
  it('enrolls a device cert (setup) over the certless plane', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });

    // Enrollment is device setup, not the flow under test. Do it via the bridge
    // with explicit self-signed trust (the GUI enroll form doesn't pass it). The
    // cert lands in the run's fresh keyring, where start_tunnel reads it.
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
  });

  it('logs in and the seeded tunnel auto-connects', async () => {
    const inputs = await $$('.login-card input'); // serverUrl, username, password
    await inputs[0].setValue(SERVER_URL);
    await inputs[1].setValue(USER);
    await inputs[2].setValue(PASS);
    await browser.keys('Enter');

    // Login succeeded → app shell. Its onMount auto-starts the seeded tunnel.
    await $('.sidebar-nav').waitForExist({ timeout: 20000 });

    // The indicator goes connecting → connected once frpc has started.
    const indicator = await $('.tunnel-indicator');
    await indicator.waitForExist({ timeout: 15000 });
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) === 'connected',
      { timeout: 30000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
    );
  });
});
