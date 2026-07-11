// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: create a connection through the TOP-LEVEL Connections page editor (the
// standalone ConnectionEditor, distinct from the server-detail connections tab
// that connection-crud drives). The new card appearing in the list is the GUI →
// gateway → server → DB round-trip. Orchestrated by scripts/tests/desktop_e2e_*.sh.

import { login, clickInModal, waitForRow } from '../lib/live.js';

describe('Connection editor via the Connections page', () => {
  it('creates a connection through the top-level editor', async () => {
    await login();
    await $('.sidebar-nav [data-nav="connections"]').click();
    await $('.toolbar-right .btn.primary').click(); // "New connection"
    await $('.editor-overlay[role="dialog"]').waitForExist({ timeout: 10000 });

    // ssh kind by default → name + host, selected by field name (not index).
    await $('.editor-overlay input[name="name"]').setValue('editor-conn');
    await $('.editor-overlay input[name="host"]').setValue('10.0.0.42');
    // This editor's primary button is "Connect"; the save action is the .btn.save.
    await clickInModal('.btn.save');

    await waitForRow('.card-title', 'editor-conn');
  });
});
