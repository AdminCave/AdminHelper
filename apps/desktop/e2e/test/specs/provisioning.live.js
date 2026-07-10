// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: generate an agent-enrollment (provisioning) token through the GUI. The
// server mints the token; the GUI shows the ready-to-run provision command and
// lists the token in the existing-tokens table — that reload is the round-trip
// verification. Orchestrated by scripts/tests/desktop_e2e_crud.sh.

import { login, gotoInfrastructure, openServerTab } from '../lib/live.js';

describe('Provisioning token via the GUI', () => {
  it('mints an enrollment token for the seeded server', async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab('provisioning');

    await $('.prov .btn.primary').click();

    // the provision command (carrying the freshly minted token) is shown...
    await $('.cmd-box').waitForExist({ timeout: 15000 });
    // ...and the token appears in the existing-tokens table (server round-trip)
    await browser.waitUntil(async () => (await $$('.prov-table tbody tr')).length >= 1, {
      timeout: 15000,
      timeoutMsg: 'minted token never appeared in the table',
    });
  });
});
