// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: signing out ends the session and returns to the login screen — the app
// shell + its nav go away. Orchestrated by scripts/tests/desktop_e2e_*.sh.

import { login } from '../lib/live.js';

describe('Logout', () => {
  it('signs out and returns to the login screen', async () => {
    await login();
    // The "Sign out" button — the only ghost/small button in the header's right side.
    await $('.content-header-right .btn.ghost.small').click();
    await $('.login-card').waitForExist({ timeout: 15000 });
    await expect($('.sidebar-nav')).not.toBeExisting();
  });
});
