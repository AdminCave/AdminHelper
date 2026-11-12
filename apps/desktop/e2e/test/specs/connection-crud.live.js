// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live CRUD of a server-detail connection through the GUI. Each step is verified
// by the list itself: the tab reloads from the server after every mutation, so
// "appears / renamed / gone" in the list IS the GUI → gateway → server → DB
// round-trip. Orchestrated by scripts/tests/desktop_e2e_crud.sh.

import {
  login,
  gotoInfrastructure,
  openServerTab,
  clickInModal,
  waitForRow,
  openRowByName,
} from '../lib/live.js';

// A connection of a server shows the display name the server derives from the seeded server
// e2e-server and the connection's own text (R-1210).
const shown = (own) => `e2e-server · ${own}`;

describe('Connection CRUD via the GUI', () => {
  it('creates, renames and deletes a connection on the seeded server', async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab('connections');

    // create (ssh kind by default: an own text, the host starts at the server's address)
    await $('[data-action="conn-new"]').click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    let inputs = await $$('.editor-overlay input[type="text"]'); // [0]=own text, [1]=host
    await inputs[0].setValue('crud-conn');
    await inputs[1].setValue('10.0.0.9');
    await clickInModal('.btn.primary');
    await waitForRow('.conn-row .conn-name', shown('crud-conn'));

    // rename
    await openRowByName('.conn-row', '.conn-name', shown('crud-conn'));
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    inputs = await $$('.editor-overlay input[type="text"]');
    await inputs[0].setValue('crud-conn-renamed');
    await clickInModal('.btn.primary');
    await waitForRow('.conn-row .conn-name', shown('crud-conn-renamed'));
    await waitForRow('.conn-row .conn-name', shown('crud-conn'), false);

    // delete (two-step danger button)
    await openRowByName('.conn-row', '.conn-name', shown('crud-conn-renamed'));
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await clickInModal('.btn.danger'); // arm the confirm
    await clickInModal('.btn.danger'); // confirm delete
    await waitForRow('.conn-row .conn-name', shown('crud-conn-renamed'), false);
  });
});
