// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: signing out ends the session and returns to the login screen — the app
// shell + its nav go away. Orchestrated by scripts/tests/desktop_e2e_*.sh.
// R-0430: the session lives in the Rust process, the webview holds no token. A
// page and api_proxy load with method and path alone, and after the sign-out the
// same call finds no session.

import { login, gotoInfrastructure } from '../lib/live.js';

// The text of session::no_session() (apps/desktop/src-tauri/src/session.rs).
const NO_SESSION = 'Keine aktive Sitzung — Anfrage abgelehnt';

// api_proxy through the bridge as the UI calls it: method and path, no server URL,
// no token. The rejection comes back as { error }, so its text reaches the assertion.
function proxyGet(path) {
  return browser.executeAsync((p, done) => {
    window.__TAURI__.core
      .invoke('api_proxy', { method: 'GET', path: p })
      .then((value) => done({ value }))
      .catch((e) => done({ error: String((e && e.message) || e) }));
  }, path);
}

describe('Logout', () => {
  it('signs in: a page and api_proxy load without a token in the webview (R-0430)', async () => {
    await login();
    // The Infrastructure page lists servers through api_proxy; the seeded one shows up.
    await gotoInfrastructure();

    const servers = await proxyGet('/api/servers');
    expect(servers.error).toBeUndefined();
    expect(Array.isArray(servers.value)).toBe(true);
    expect(servers.value.length).toBeGreaterThan(0);
  });

  it('signs out and returns to the login screen; api_proxy then has no session', async () => {
    // The sign-out reloads the window (logoutAndReload), and the login card can show on
    // the old document before that. Only the reloaded one lacks this mark.
    await browser.execute(() => {
      window.__ahBeforeSignOut = true;
    });
    // The "Sign out" button — the only ghost/small button in the header's right side.
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
    await expect($('.sidebar-nav')).not.toBeExisting();

    // The same call as above: Rust dropped the session, so nothing goes out.
    expect(await proxyGet('/api/servers')).toEqual({ error: NO_SESSION });
  });
});
