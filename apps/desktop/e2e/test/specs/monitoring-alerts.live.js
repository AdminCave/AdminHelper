// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: create a webhook alert rule on the Monitoring "alerts" tab and see it
// appear in the rule list (GUI → gateway → monitoring service → DB round-trip).
// Orchestrated by scripts/tests/desktop_e2e_*.sh.

import { login, clickInModal, waitForRow } from '../lib/live.js';

describe('Monitoring alert rule via the GUI', () => {
  it('creates a webhook alert rule on the alerts tab', async () => {
    await login();
    await $('.sidebar-nav [data-nav="monitoring"]').click();
    // Switch to the alerts tab by its stable id (the tab button, not the content div).
    await $('.mon-tabs [data-tab="alerts"]').click();

    await $('.mon-alert-toolbar .btn.primary').waitForExist({ timeout: 15000 });
    await $('.mon-alert-toolbar .btn.primary').click();

    // channel defaults to webhook → name + webhookUrl are the required fields.
    await $('.editor-overlay .editor-panel').waitForExist({ timeout: 10000 });
    await $('.editor-overlay input[type="text"]').setValue('e2e-cpu-alert');
    await $('.editor-overlay input[type="url"]').setValue('https://hooks.example.com/e2e');
    await clickInModal('.btn.primary'); // save -> POST alert rule

    await waitForRow('.mon-alert-name', 'e2e-cpu-alert');
  });
});
