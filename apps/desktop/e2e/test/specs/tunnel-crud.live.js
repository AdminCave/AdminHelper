// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live CRUD of a tunnel through the GUI (create → rename → delete), verified by
// the reloaded list. The seeded FRP config is preselected. Orchestrated by
// scripts/tests/desktop_e2e_crud.sh.

import {
  login,
  gotoInfrastructure,
  openServerTab,
  clickInModal,
  waitForRow,
  openRowByName,
} from '../lib/live.js';

// The list shows the display name the server derives from the seeded server e2e-server and the
// tunnel's own text (R-1210).
const shown = (own) => `e2e-server · ${own} (FRP)`;

describe('Tunnel CRUD via the GUI', () => {
  it('creates, renames and deletes a tunnel', async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab('tunnels');

    // create (the lone seeded FRP config is preselected)
    await $('[data-action="tun-new"]').waitForEnabled({ timeout: 15000 });
    await $('[data-action="tun-new"]').click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await $('.editor-overlay input[name="name"]').setValue('crud-tun');
    let nums = await $$('.editor-overlay input[type="number"]');
    await nums[0].setValue('22'); // local port
    await clickInModal('.btn.primary');
    await waitForRow('.tun-row .tun-name', shown('crud-tun'));

    // rename
    await openRowByName('.tun-row', '.tun-name', shown('crud-tun'));
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await $('.editor-overlay input[name="name"]').setValue('crud-tun-renamed');
    await clickInModal('.btn.primary');
    await waitForRow('.tun-row .tun-name', shown('crud-tun-renamed'));

    // delete
    await openRowByName('.tun-row', '.tun-name', shown('crud-tun-renamed'));
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await clickInModal('.btn.danger');
    await clickInModal('.btn.danger');
    await waitForRow('.tun-row .tun-name', shown('crud-tun-renamed'), false);
  });
});
