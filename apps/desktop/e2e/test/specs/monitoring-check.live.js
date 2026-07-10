// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: create an agent_resources monitoring check through the GUI on the seeded
// server (which a real agent has already pushed metrics for). The check appears
// in the list after a reload from the monitoring service (GUI → api_proxy →
// gateway → server → monitoring). Orchestrated by desktop_e2e_monitoring.sh.

import {
  login,
  gotoInfrastructure,
  openServerTab,
  clickInModal,
  waitForRow,
} from '../lib/live.js';

describe('Monitoring check via the GUI', () => {
  it('creates an agent_resources check on the seeded server', async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab('monitoring');

    await $('.mon-toolbar .btn.primary').click();
    await $('.editor-overlay .editor-panel').waitForExist({ timeout: 10000 });
    await $('.editor-overlay input[type="text"]').setValue('cpu-check');
    const selects = await $$('.editor-overlay select'); // checkType, interval, severity
    await selects[0].selectByAttribute('value', 'agent_resources');
    await clickInModal('.btn.primary'); // save -> POST /api/monitoring/checks

    await waitForRow('.mon-row .mon-name', 'cpu-check');
  });
});
