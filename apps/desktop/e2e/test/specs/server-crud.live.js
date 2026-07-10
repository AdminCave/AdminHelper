// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live create + delete of a server through the GUI, verified by the reloaded
// server list. Orchestrated by scripts/tests/desktop_e2e_crud.sh.

import { login, gotoInfrastructure, clickInModal, waitForRow, clickItemByName } from '../lib/live.js';

describe('Server CRUD via the GUI', () => {
  it('creates and deletes a server', async () => {
    await login();
    await gotoInfrastructure();

    // create via "+ Add Server" (ServerModal: name, hostname, ...)
    await $('.infra-toolbar .btn.primary').click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    // Fill by field name, not input index — a reordered/added field would otherwise
    // silently populate the wrong column (4.33). The inputs carry name="…" attrs.
    await $('.editor-overlay input[name="name"]').setValue('crud-server');
    await $('.editor-overlay input[name="hostname"]').setValue('crud.example');
    await clickInModal('.btn.primary');
    await waitForRow('.srv-item .srv-item-name', 'crud-server');

    // select it, open its editor (detail header "Edit"), delete (two-step)
    await clickItemByName('.srv-item', '.srv-item-name', 'crud-server');
    await $('.srv-head .btn.small').click();
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });
    await clickInModal('.btn.danger');
    await clickInModal('.btn.danger');
    await waitForRow('.srv-item .srv-item-name', 'crud-server', false);
  });
});
