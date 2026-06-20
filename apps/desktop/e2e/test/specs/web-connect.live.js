// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open a Web connection through the GUI. The desktop calls open::that(url)
// (xdg-open) — an external launch, not the webview. The orchestrator
// (desktop_e2e_connect.sh) puts an xdg-open shim on PATH that fetches the URL, so
// it verifies from the target side via the nginx access log.

import { login, clickItemByName } from '../lib/live.js';

describe('Open a Web connection through the GUI', () => {
  it('launches the browser for the seeded web target on connect', async () => {
    await login();

    const nav = await $$('.sidebar-nav .sidebar-item'); // dashboard / connections / infrastructure
    await nav[1].click();
    await $('.card').waitForExist({ timeout: 15000 });

    await clickItemByName('.card', '.card-title', 'web-direct'); // -> open::that(url) -> xdg-open shim

    await browser.pause(4000);
  });
});
