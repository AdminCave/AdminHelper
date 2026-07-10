// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: a wrong password surfaces the inline error and never reaches the app
// shell — the negative counterpart to the successful login the other specs rely
// on. Orchestrated by scripts/tests/desktop_e2e_*.sh.

import { SERVER_URL, USER } from '../lib/live.js';

describe('Login — wrong credentials', () => {
  it('shows an error and stays on the login screen', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });
    const inputs = await $$('.login-card input'); // [0]=serverUrl, [1]=username, [2]=password
    await inputs[0].setValue(SERVER_URL);
    await inputs[1].setValue(USER);
    await inputs[2].setValue('wrong-password-for-the-e2e');
    await browser.keys('Enter');

    // The inline error fills in and the app shell never mounts.
    await browser.waitUntil(async () => (await $('.login-error').getText()).trim().length > 0, {
      timeout: 15000,
      timeoutMsg: 'no login error surfaced for a wrong password',
    });
    await expect($('.sidebar-nav')).not.toBeExisting();
  });
});
