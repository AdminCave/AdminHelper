// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: switch the app mode in Settings (server → local). Saving ends the server
// session and reloads into local mode, so the server-only UI (the Infrastructure
// nav item, the tunnel indicator) goes away and the sidebar mode badge changes —
// the observable side effect of the switch. Runs LAST in desktop_e2e_crud.sh
// because it persists mode=local to the run's settings.

import { login, jsClick } from '../lib/live.js';

describe('Switch the app mode in Settings', () => {
  it('switches from server to local and the server-only UI goes away', async () => {
    await login(); // logs into server mode

    const navBefore = (await $$('.sidebar-nav .sidebar-item')).length;
    const badgeBefore = await $('.sidebar-bottom .sidebar-badge').getText();

    // Open settings (the gear in the sidebar footer), switch to local, save.
    await $('.sidebar-bottom .sidebar-item').click();
    await $('.sm-panel').waitForExist({ timeout: 10000 });
    await $('.sm-panel input[value="local"]').click();
    await jsClick(await $('.sm-panel .btn.primary')); // save -> serverLogout + reload(local)

    // The mode badge changes and a server-only nav item disappears.
    await browser.waitUntil(
      async () => (await $('.sidebar-bottom .sidebar-badge').getText()) !== badgeBefore,
      { timeout: 15000, timeoutMsg: 'the mode badge never changed' },
    );
    const navAfter = (await $$('.sidebar-nav .sidebar-item')).length;
    expect(navAfter).toBeLessThan(navBefore);
  });
});
