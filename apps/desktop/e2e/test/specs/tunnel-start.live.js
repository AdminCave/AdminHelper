// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E: start a tunnel and confirm it connects (the "test it" half).
// Orchestrated by scripts/tests/desktop_e2e_tunnel.sh, which boots the stack +
// frps and seeds a server + FRP config + an STCP tunnel. Here the app enrolls a
// device cert (setup), logs in, and AppShell auto-starts the seeded tunnel; we
// assert the GUI tunnel indicator reaches "connected". The orchestrator then
// independently checks the frps log for the frpc login.
// Then (R-0429) the header's sign-out has to stop the tunnel; the window reloads, and
// a new login connects again.
// The last step (R-0402) creates a second STCP tunnel in the GUI while the tunnel
// runs: the running frpc has to take its visitor over by a reload, not a restart.

import { login, gotoInfrastructure, openServerTab, jsClick } from '../lib/live.js';

const SERVER_URL = process.env.AH_SERVER_URL;
const ENROLL_TOKEN = process.env.AH_ENROLL_TOKEN;

// The tunnel desktop_e2e_tunnel.sh seeds, and the one this spec adds next to it.
// The server names each visitor "<tunnel>-visitor" (generate_visitor_toml).
const SEEDED_TUNNEL = 'e2e-ssh';
const ADDED_TUNNEL = 'e2e-ssh-added';
const ADDED_VISITOR = `${ADDED_TUNNEL}-visitor`;

// tunnel_status through the bridge: whether frpc runs, since when, which visitors it applied.
// A rejection fails the spec with its message. It comes back as { rejected }: webdriver takes
// a script result with an `error` key for a failed command (logout.live.js).
async function tunnelStatus() {
  const out = await browser.executeAsync((done) => {
    window.__TAURI__.core
      .invoke('tunnel_status')
      .then((value) => done({ value }))
      .catch((e) => done({ rejected: String((e && e.message) || e) }));
  });
  if (out.rejected !== undefined) throw new Error(`tunnel_status failed: ${out.rejected}`);
  return out.value;
}

// The indicator goes connecting → connected once frpc has started.
async function waitForTunnelConnected() {
  const indicator = await $('.tunnel-indicator');
  await indicator.waitForExist({ timeout: 15000 });
  await browser.waitUntil(
    async () => (await indicator.getAttribute('data-status')) === 'connected',
    { timeout: 30000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
  );
}

describe('AdminHelper desktop — start a tunnel against live frps', () => {
  it('enrolls a device cert (setup) over the certless plane', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });

    // Enrollment is device setup, not the flow under test. Do it via the bridge
    // with explicit self-signed trust, so the spec does not depend on the
    // setting the GUI enroll form reads. The cert lands in the run's fresh
    // keyring, where start_tunnel reads it.
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
    // Shared helper — the inline login was duplicated across the tunnel specs (2.16).
    // Login succeeds → app shell, whose onMount auto-starts the seeded tunnel.
    await login();
    await waitForTunnelConnected();
  });

  it('signs out in the header: the tunnel stops, a new login connects again (R-0429)', async () => {
    // Running before, or "not running" after the sign-out would prove nothing.
    expect(await tunnelStatus()).toMatchObject({ running: true });

    // The sign-out reloads the window (logoutAndReload), and the login card can show on
    // the old document before that. Only the reloaded one lacks this mark.
    await browser.execute(() => {
      window.__ahBeforeSignOut = true;
    });
    // The "Sign out" button, as in logout.live.js.
    await $('.content-header-right .btn.ghost.small').click();
    await browser.waitUntil(
      async () => {
        try {
          return await browser.execute(
            () =>
              window.__ahBeforeSignOut !== true && document.querySelector('.login-card') !== null,
          );
        } catch {
          return false; // the old document went away during the call
        }
      },
      {
        timeout: 20000,
        interval: 250,
        timeoutMsg: 'the sign-out never reloaded the window onto the login screen within 20 s',
      },
    );

    // The tunnel stop ran before the reload; nothing on the login screen starts frpc.
    expect(await tunnelStatus()).toMatchObject({ running: false });

    // A new login in the reloaded window: AppShell starts the tunnel again.
    await login();
    await waitForTunnelConnected();
  });

  it('takes a tunnel created in the GUI over by reload, without a restart (R-0402)', async () => {
    // start_frpc sets connected_since on every start of frpc and a reload keeps it, so
    // the same value after the change means the same process.
    const before = await tunnelStatus();
    expect(before.running).toBe(true);
    expect(before.connectedSince).toBeTruthy();
    expect(before.visitors).toContain(`${SEEDED_TUNNEL}-visitor`);
    expect(before.visitors).not.toContain(ADDED_VISITOR);

    await gotoInfrastructure();
    await openServerTab('tunnels');
    // The "add tunnel" button enables only once the seeded FRP config loads.
    const add = await $('.tun-toolbar .btn.primary');
    await add.waitForEnabled({ timeout: 15000 });
    await add.click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    // STCP is the default type and the lone seeded FRP config is preselected; the
    // server picks secret and visitor port.
    await $('.editor-panel input[name="name"]').setValue(ADDED_TUNNEL);
    const numbers = await $$('.editor-panel input[type="number"]');
    await numbers[0].setValue('22'); // local port
    // Click via JS: the fixed status bar overlaps the modal's bottom action row.
    await jsClick(await $('.editor-panel .btn.primary'));

    // The dialog reconciles right after the save (refreshNow), not at the next 60 s tick.
    let after = null;
    await browser.waitUntil(
      async () => {
        after = await tunnelStatus();
        return Array.isArray(after.visitors) && after.visitors.includes(ADDED_VISITOR);
      },
      {
        timeout: 20000,
        interval: 500,
        timeoutMsg: `the running frpc never took over the visitor "${ADDED_VISITOR}" within 20 s`,
      },
    );
    expect(after.running).toBe(true);
    // A restart would have set a new start time.
    expect(after.connectedSince).toBe(before.connectedSince);
    for (const name of before.visitors) expect(after.visitors).toContain(name);
    expect(await $('.tunnel-indicator').getAttribute('data-status')).toBe('connected');
  });
});
