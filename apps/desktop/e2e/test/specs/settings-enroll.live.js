// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E (R-0212): a signed-in user whose device has no identity registers it
// in the settings, without signing out, and the tunnel starts afterwards.
// Orchestrated by scripts/tests/desktop_e2e_tunnel.sh after tunnel-start.live.js,
// against the same permissive stack and seeded STCP tunnel, with a one-time
// token of its own (AH_SETTINGS_ENROLL_TOKEN): every token is single-use.

import { login, jsClick, SERVER_URL } from '../lib/live.js';

const TOKEN = process.env.AH_SETTINGS_ENROLL_TOKEN;

describe('AdminHelper desktop — enroll from the settings, then the tunnel connects', () => {
  it('starts without a device identity', async () => {
    if (!TOKEN) {
      throw new Error(
        'AH_SETTINGS_ENROLL_TOKEN ist nicht gesetzt — über scripts/tests/desktop_e2e_tunnel.sh starten.',
      );
    }
    await $('.login-card').waitForExist({ timeout: 20000 });
    // Setup, not the flow under test: clear whatever identity the keyring holds
    // through the bridge, not through the native confirm dialog of the settings.
    const err = await browser.executeAsync(
      (url, done) => {
        window.__TAURI__.core
          .invoke('reset_device_identity', { serverUrl: url })
          .then(() => done(null))
          .catch((e) => done(String((e && e.message) || e)));
      },
      SERVER_URL,
    );
    expect(err).toBe(null);
  });

  it('signs in, registers the device in the settings, and the tunnel connects', async () => {
    await login();

    // AppShell starts the tunnel at login, which fails without a certificate. Wait
    // until that attempt is over: it must not be connected, or the check at the end
    // proves nothing, and a late answer must not overwrite the state after enrolling.
    const indicator = await $('.tunnel-indicator');
    await indicator.waitForExist({ timeout: 15000 });
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) !== 'connecting',
      { timeout: 30000, timeoutMsg: 'the tunnel start at login never finished' },
    );
    expect(await indicator.getAttribute('data-status')).not.toBe('connected');

    // The gear in the sidebar footer opens the settings (as in settings-mode.live.js).
    await $('.sidebar-bottom .sidebar-item').click();
    await $('.sm-panel').waitForExist({ timeout: 10000 });
    const token = await $('.sm-panel [data-action="enroll-token"]');
    await token.waitForExist({ timeout: 10000 });
    await token.setValue(TOKEN);
    await jsClick(await $('.sm-panel [data-action="enroll-submit"]'));

    // Registered: the block switches to the reset.
    await $('.sm-panel [data-action="device-reset"]').waitForExist({
      timeout: 30000,
      timeoutMsg: 'the settings never offered the reset after the enrollment',
    });

    // The enrollment starts the tunnel again, now with the certificate.
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) === 'connected',
      { timeout: 30000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
    );
  });
});
