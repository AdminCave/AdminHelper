// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E (R-0212): a signed-in user whose device has no identity registers it
// in the settings, without signing out, and the tunnel starts afterwards.
// Orchestrated by scripts/tests/desktop_e2e_tunnel.sh after tunnel-start.live.js,
// against the same permissive stack and seeded STCP tunnel, with a one-time
// token of its own (AH_SETTINGS_ENROLL_TOKEN): every token is single-use.
// The third step (R-0246) starts where the second ends: it resets the identity
// while the tunnel runs and registers again with a third token
// (AH_SETTINGS_REENROLL_TOKEN), so a new frpc has to replace the old one.

import { login, jsClick, SERVER_URL } from '../lib/live.js';

const TOKEN = process.env.AH_SETTINGS_ENROLL_TOKEN;
const REENROLL_TOKEN = process.env.AH_SETTINGS_REENROLL_TOKEN;

// A Tauri command through the bridge; resolves to { value } or { error }.
function invoke(cmd, args = {}) {
  return browser.executeAsync(
    (c, a, done) => {
      window.__TAURI__.core
        .invoke(c, a)
        .then((value) => done({ value }))
        .catch((e) => done({ error: String((e && e.message) || e) }));
    },
    cmd,
    args,
  );
}

async function openSettings() {
  // The gear in the sidebar footer opens the settings (as in settings-mode.live.js).
  await $('.sidebar-bottom .sidebar-item').click();
  await $('.sm-panel').waitForExist({ timeout: 10000 });
}

async function registerInSettings(token) {
  const field = await $('.sm-panel [data-action="enroll-token"]');
  await field.waitForExist({ timeout: 10000 });
  await field.setValue(token);
  await jsClick(await $('.sm-panel [data-action="enroll-submit"]'));
  // Registered: the block switches to the reset.
  await $('.sm-panel [data-action="device-reset"]').waitForExist({
    timeout: 30000,
    timeoutMsg: 'the settings never offered the reset after the enrollment',
  });
}

describe('AdminHelper desktop — enroll from the settings, then the tunnel connects', () => {
  it('starts without a device identity', async () => {
    for (const [name, value] of Object.entries({
      AH_SETTINGS_ENROLL_TOKEN: TOKEN,
      AH_SETTINGS_REENROLL_TOKEN: REENROLL_TOKEN,
    })) {
      if (!value) {
        throw new Error(
          `${name} ist nicht gesetzt — über scripts/tests/desktop_e2e_tunnel.sh starten.`,
        );
      }
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

    await openSettings();
    await registerInSettings(TOKEN);

    // The enrollment starts the tunnel again, now with the certificate.
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) === 'connected',
      { timeout: 30000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
    );
  });

  it('registers again after a reset while the tunnel runs, and a new frpc takes over (R-0246)', async () => {
    // Where the second step ends: signed in, identity from the settings, tunnel connected.
    const before = (await invoke('tunnel_status')).value;
    expect(before && before.running).toBe(true);
    expect(before.connectedSince).toBeTruthy();

    // The reset clears the keyring, not the frpc process: the tunnel keeps running on
    // the old identity, the case onEnroll stops before it starts (#102, T7).
    const reset = await invoke('reset_device_identity', { serverUrl: SERVER_URL });
    expect(reset.error).toBeUndefined();

    // The settings read the identity when they open; reopen them for the token field.
    await jsClick(await $('.sm-panel .panel-header button'));
    await $('.sm-panel').waitForExist({ reverse: true, timeout: 10000 });
    await openSettings();
    await registerInSettings(REENROLL_TOKEN);

    // A new frpc runs: start_frpc sets connected_since on every start. The indicator
    // alone proves nothing here, it may still read "connected" from the step before.
    await browser.waitUntil(
      async () => {
        const now = (await invoke('tunnel_status')).value;
        return Boolean(
          now && now.running && now.connectedSince && now.connectedSince !== before.connectedSince,
        );
      },
      { timeout: 30000, timeoutMsg: 'no new frpc after registering again' },
    );
    await browser.waitUntil(
      async () => (await $('.tunnel-indicator').getAttribute('data-status')) === 'connected',
      { timeout: 30000, timeoutMsg: 'the tunnel indicator never reached "connected" again' },
    );
  });
});
