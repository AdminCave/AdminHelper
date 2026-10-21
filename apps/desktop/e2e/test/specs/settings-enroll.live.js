// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E (R-0212): a signed-in user whose device has no identity registers it
// in the settings, without signing out, and the tunnel starts afterwards.
// Orchestrated by scripts/tests/desktop_e2e_tunnel.sh after tunnel-start.live.js,
// against the same permissive stack and seeded STCP tunnel, with a one-time
// token of its own (AH_SETTINGS_ENROLL_TOKEN): every token is single-use.
// The third step (R-0246) starts where the second ends: it resets the identity
// while the tunnel runs, through the settings' button and the app's own confirm
// dialog (R-0395), and registers again with a third token
// (AH_SETTINGS_REENROLL_TOKEN), so a new frpc has to replace the old one. The reset
// revokes the device at the server first (R-0224): the admin's device list shows the
// old line revoked by the device itself and, after registering again, a new one.
// After each registration the settings name the identity (R-0240): the subject the
// token was minted for and a date in the future.

import { adminDevices, login, jsClick, SERVER_URL } from '../lib/live.js';

const TOKEN = process.env.AH_SETTINGS_ENROLL_TOKEN;
const REENROLL_TOKEN = process.env.AH_SETTINGS_REENROLL_TOKEN;

// A Tauri command through the bridge; resolves to { value } or { rejected }. Not { error }:
// webdriver takes a script result with an `error` key for a failed command (logout.live.js).
function invoke(cmd, args = {}) {
  return browser.executeAsync(
    (c, a, done) => {
      window.__TAURI__.core
        .invoke(c, a)
        .then((value) => done({ value }))
        .catch((e) => done({ rejected: String((e && e.message) || e) }));
    },
    cmd,
    args,
  );
}

async function openSettings() {
  // The gear in the sidebar footer opens the settings.
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

// The line reloads after the enrollment, so wait for it. The issuer names the leaf
// after the token's subject (minted with `--username admin` in desktop_e2e_tunnel.sh),
// and a native leaf lives 90 days: "valid", not "soon".
async function expectIdentityLine() {
  const line = await $('.sm-panel [data-msg="device-identity"]');
  await line.waitForExist({
    timeout: 10000,
    timeoutMsg: 'the settings never showed the device identity line',
  });
  expect(await line.getAttribute('data-state')).toBe('valid');
  expect(await line.$('strong').getText()).toBe('admin');
  // Day first in both UI locales: 13.01.2027 (de-DE), 13/01/2027 (en-GB).
  const text = await line.getText();
  const m = /(\d{2})[./](\d{2})[./](\d{4})/.exec(text);
  expect(m).not.toBe(null);
  const shown = new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  expect(shown.getTime()).toBeGreaterThan(today.getTime());
}

// jsClick skips WebDriver's hit test (lib/live.js), so it also clicks an element that
// something else covers. The point a user clicks, the element's centre, has to hit the
// element itself; otherwise the test names what lies above it.
async function expectOnTop(el, what) {
  const problem = await browser.execute((node) => {
    const r = node.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (hit && node.contains(hit)) return null;
    if (!hit) return 'its centre lies outside the viewport';
    const classes = [...hit.classList].filter((c) => !c.startsWith('svelte-'));
    return `${[hit.tagName.toLowerCase(), ...classes].join('.')} lies above it`;
  }, el);
  if (problem !== null) throw new Error(`${what} is not on top: ${problem}`);
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
    // through the bridge: the settings need a session.
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
    await expectIdentityLine();

    // The enrollment starts the tunnel again, now with the certificate.
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) === 'connected',
      { timeout: 30000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
    );
  });

  it('registers again after a reset while the tunnel runs, and a new frpc takes over (R-0246)', async () => {
    // Where the second step ends: signed in, identity from the settings, tunnel connected,
    // the settings still open.
    const before = (await invoke('tunnel_status')).value;
    expect(before && before.running).toBe(true);
    expect(before.connectedSince).toBeTruthy();

    const linesBefore = adminDevices();
    const activeBefore = new Set(linesBefore.filter((d) => !d.revoked_at).map((d) => d.id));

    // The reset clears the keyring, not the frpc process: the tunnel keeps running on
    // the old identity, the case onEnroll stops before it starts (#102, T7).
    // Through the button, as a user does (R-0395): a reset through the bridge never saw
    // that the button's question failed without a dialog permission.
    const resetMsg = await $('.sm-panel [data-msg="device-reset"]');
    expect(await resetMsg.isExisting()).toBe(false);
    const resetButton = await $('.sm-panel [data-action="device-reset"]');
    const resetLabel = await resetButton.getText();
    await jsClick(resetButton);
    // The question opens in the app's own dialog; its confirm button repeats the label.
    const confirmButton = await $('.confirm-layer .modal-panel .btn.danger');
    await confirmButton.waitForExist({
      timeout: 10000,
      timeoutMsg: 'the reset never asked in the app dialog',
    });
    expect(await confirmButton.getText()).toBe(resetLabel);
    // The question has to lie above the settings that ask it (.confirm-layer over
    // .sm-overlay, App.svelte); a covered one would still take the jsClick.
    await expectOnTop(confirmButton, 'the confirm button');
    await jsClick(confirmButton);
    // A message after the confirmation is the done one: the missing-URL message comes
    // before the question, and a failed reset clears the message.
    await resetMsg.waitForExist({
      timeout: 30000,
      timeoutMsg: 'the settings never reported the reset as done',
    });
    // First revoked at the server, with this very certificate (R-0224): no local-only note.
    expect(await $('.sm-panel [data-msg="device-reset-local"]').isExisting()).toBe(false);
    const revokedBySelf = adminDevices().filter(
      (d) => activeBefore.has(d.id) && d.revoked_reason === 'self',
    );
    expect(revokedBySelf.length).toBe(1);
    // Nothing left for the identity line to name.
    expect(await invoke('device_identity')).toEqual({ value: null });

    // The reset turns the block into the token field in place, as its message asks.
    await registerInSettings(REENROLL_TOKEN);
    await expectIdentityLine();

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

    // Registering again opened a new device line; the revoked one stays revoked.
    const known = new Set(linesBefore.map((d) => d.id));
    const fresh = adminDevices().filter((d) => !d.revoked_at && !known.has(d.id));
    expect(fresh.length).toBe(1);
  });
});
