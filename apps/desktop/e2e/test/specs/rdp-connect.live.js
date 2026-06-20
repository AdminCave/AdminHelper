// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open an RDP connection through the GUI. On Linux the desktop always shows
// a password prompt for RDP first (this also exercises that journey); confirming
// it runs the preflight + spawns xfreerdp3 to the target. The desktop launches
// xfreerdp3 as an external process, so the orchestrator (desktop_e2e_connect.sh)
// verifies from the target side via the xrdp log.

import { login, clickItemByName, jsClick } from '../lib/live.js';

describe('Open an RDP connection through the GUI', () => {
  it('launches xfreerdp3 to the target after the password prompt', async () => {
    await login();

    const nav = await $$('.sidebar-nav .sidebar-item'); // dashboard / connections / infrastructure
    await nav[1].click();
    await $('.card').waitForExist({ timeout: 15000 });

    await clickItemByName('.card', '.card-title', 'rdp-direct'); // -> RDP password prompt

    await $('.pw-panel').waitForExist({ timeout: 10000 });
    await $('.pw-panel input[type="password"]').setValue('e2e');
    await jsClick(await $('.pw-panel .btn.primary')); // Verbinden -> preflight + xfreerdp3

    // Give xfreerdp3 time to reach xrdp (verified container-side via the xrdp log).
    await browser.pause(7000);
  });
});
