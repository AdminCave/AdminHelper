// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open an SSH connection through the GUI. Double-clicking a connection row runs
// initiateConnect -> the desktop spawns ssh in a terminal (an external process,
// not the webview), so there is nothing in the GUI to assert — the orchestrator
// (desktop_e2e_connect.sh) verifies from the target side via the sshd log.

import { login, connectByName, CONN_ROW } from '../lib/live.js';

describe('Open an SSH connection through the GUI', () => {
  it('launches ssh to the seeded target on connect', async () => {
    await login();

    const nav = await $$('.sidebar-nav .sidebar-item'); // dashboard / connections / infrastructure
    await nav[1].click();
    await $(CONN_ROW).waitForExist({ timeout: 15000 });

    await connectByName('ssh-direct'); // -> spawns ssh to the target

    // Give the spawned ssh time to reach the sshd container (verified there).
    await browser.pause(5000);
  });
});
