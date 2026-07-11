// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live E2E: create a connection tunnel through the REAL app against a REAL backend
// (booted + seeded by scripts/tests/desktop_e2e_live.sh) — the full path GUI →
// api_proxy → nginx gateway → server → Postgres. The orchestrator then re-checks
// the tunnel via the server API.

import { login, gotoInfrastructure, openServerTab } from '../lib/live.js';

const TUNNEL_NAME = 'e2e-ssh';

describe('AdminHelper desktop — create a tunnel against a live server', () => {
  it('logs in and opens Infrastructure → the seeded server → the Tunnels tab', async () => {
    await login(); // shared helper — the login was duplicated inline across the tunnel specs (2.16)
    await gotoInfrastructure();
    await openServerTab('tunnels');
    // The "add tunnel" button enables only once the seeded FRP config loads.
    await $('.tun-toolbar .btn.primary').waitForEnabled({ timeout: 15000 });
  });

  it('creates a tunnel via the modal and sees it in the list', async () => {
    await $('.tun-toolbar .btn.primary').click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });

    // The lone seeded FRP config is preselected; fill name + local port. Select the
    // name field by its stable name= attr, not the placeholder example text (4.35).
    await $('.editor-panel input[name="name"]').setValue(TUNNEL_NAME);
    const numbers = await $$('.editor-panel input[type="number"]');
    await numbers[0].setValue('22'); // local port (stcp also has a visitor port)

    // Save → real POST /api/frp/tunnels. Click via JS: the fixed status bar overlaps
    // the modal's bottom action row, so a coordinate click is intercepted.
    const saveBtn = await $('.editor-panel .btn.primary');
    await browser.execute((el) => el.click(), saveBtn);

    // The modal closes and TunnelsTab reloads from the server.
    await browser.waitUntil(
      async () => {
        for (const n of await $$('.tun-row .tun-name')) {
          if ((await n.getText()) === TUNNEL_NAME) return true;
        }
        return false;
      },
      { timeout: 15000, timeoutMsg: 'the created tunnel never appeared in the list' },
    );
  });
});
