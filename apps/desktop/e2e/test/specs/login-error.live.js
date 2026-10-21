// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: a wrong password surfaces the inline error and never reaches the app
// shell — the negative counterpart to the successful login the other specs rely
// on. Orchestrated by scripts/tests/desktop_e2e_*.sh.

import { USER, fillServerUrlIfAsked } from '../lib/live.js';

describe('Login — wrong credentials', () => {
  it('shows an error and stays on the login screen', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });
    await fillServerUrlIfAsked();
    // By field type, not position: a workspace with its URL has no URL field.
    await $('.login-card input[type="text"]').setValue(USER);
    await $('.login-card input[type="password"]').setValue('wrong-password-for-the-e2e');
    await browser.keys('Enter');

    // The inline error fills in and the app shell never mounts.
    await browser.waitUntil(async () => (await $('.login-error').getText()).trim().length > 0, {
      timeout: 15000,
      timeoutMsg: 'no login error surfaced for a wrong password',
    });
    await expect($('.sidebar-nav')).not.toBeExisting();
  });
});
