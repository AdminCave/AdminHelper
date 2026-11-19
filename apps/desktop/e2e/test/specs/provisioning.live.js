// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: generate an agent-enrollment (provisioning) token through the GUI. The
// provisioning dialog loads the platform catalog from the server, the server mints
// the token, and the token appears in the existing-tokens table of the tab — that
// reload is the round-trip verification. Orchestrated by
// scripts/tests/desktop_e2e_crud.sh.

import { login, gotoInfrastructure, openServerTab } from '../lib/live.js';

describe('Provisioning token via the GUI', () => {
  it('mints an enrollment token for the seeded server', async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab('provisioning');

    await $('[data-action="prov-open"]').click();
    // Windows is in the catalog whether or not the stack ships a package repo, and its
    // re-register command takes a token: the one platform that always offers the button.
    const platform = await $('#prov-platform');
    await platform.waitForExist({ timeout: 30000 });
    await platform.selectByAttribute('value', 'windows');

    await $('[data-action="prov-mint"]').click();

    // the command and the freshly minted token are shown...
    await $('[data-testid="provision-command"]').waitForExist({ timeout: 30000 });
    await $('[data-testid="prov-token"]').waitForExist({ timeout: 30000 });
    // ...and the token appears in the existing-tokens table (server round-trip)
    await browser.waitUntil(async () => (await $$('.prov-table tbody tr')).length >= 1, {
      timeout: 30000,
      timeoutMsg: 'minted token never appeared in the table',
    });
  });
});
