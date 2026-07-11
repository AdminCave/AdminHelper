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

describe('Tunnel CRUD via the GUI', () => {
  it('creates, renames and deletes a tunnel', async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab('tunnels');

    // create (the lone seeded FRP config is preselected)
    await $('.tun-toolbar .btn.primary').waitForEnabled({ timeout: 15000 });
    await $('.tun-toolbar .btn.primary').click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await $('.editor-overlay input[placeholder="k01-lnx1-ssh"]').setValue('crud-tun');
    let nums = await $$('.editor-overlay input[type="number"]');
    await nums[0].setValue('22'); // local port
    await clickInModal('.btn.primary');
    await waitForRow('.tun-row .tun-name', 'crud-tun');

    // rename
    await openRowByName('.tun-row', '.tun-name', 'crud-tun');
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await $('.editor-overlay input[placeholder="k01-lnx1-ssh"]').setValue('crud-tun-renamed');
    await clickInModal('.btn.primary');
    await waitForRow('.tun-row .tun-name', 'crud-tun-renamed');

    // delete
    await openRowByName('.tun-row', '.tun-name', 'crud-tun-renamed');
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await clickInModal('.btn.danger');
    await clickInModal('.btn.danger');
    await waitForRow('.tun-row .tun-name', 'crud-tun-renamed', false);
  });
});
