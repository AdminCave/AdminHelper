// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The non-trivial ansible store logic (6.41): runPlaybook hands the run to the backend in one call
// (ansibleRun with the playbook id and the targets; the backend loads the playbook itself) with the
// running-flag reset in the finally even on failure, and toggleTag's all-selected group toggle. A hung
// running flag would block the wizard forever; the plain selection tests don't touch either.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { Playbook, Server } from '$lib/api/types';

const h = vi.hoisted(() => ({
  session: { serverUrl: 'https://x' } as unknown,
  fetchPlaybooks: vi.fn(),
  fetchServers: vi.fn(),
  fetchContent: vi.fn(),
  run: vi.fn(),
  reportError: vi.fn(),
}));

vi.mock('./session', () => ({ currentSession: () => h.session }));
vi.mock('$lib/api/ansible', () => ({
  ansibleApi: {
    fetchPlaybooks: h.fetchPlaybooks,
    fetchServers: h.fetchServers,
    fetchContent: h.fetchContent,
  },
}));
vi.mock('$lib/bridge', () => ({ ansibleRun: h.run }));
vi.mock('./statusBar', () => ({ reportError: h.reportError, showStatus: vi.fn() }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));

import {
  loadAnsibleData,
  selectPlaybook,
  toggleServer,
  toggleTag,
  runPlaybook,
  clearSelection,
  ansibleSelectedServerIds,
  ansibleRunning,
  ansibleLoadError,
} from './ansible';

const pb = { id: 'pb1', name: 'Deploy', filename: 'deploy.yml' } as unknown as Playbook;
const srvA = { id: 's1', name: 'web', hostname: 'web.lan', tags: ['web'] } as unknown as Server;
const srvB = { id: 's2', name: 'app', hostname: 'app.lan', tags: ['web'] } as unknown as Server;

async function seed() {
  h.fetchPlaybooks.mockResolvedValue([pb]);
  h.fetchServers.mockResolvedValue([srvA, srvB]);
  await loadAnsibleData();
}

describe('ansible store: runPlaybook + toggleTag (6.41)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearSelection();
  });

  it('runs the pipeline in order and resets running (+reports) on failure', async () => {
    await seed();
    selectPlaybook(pb.id);
    toggleServer('s1');

    h.run.mockRejectedValue(new Error('no terminal'));

    await runPlaybook();

    // One call with the id and the targets: the content never passes through the UI.
    expect(h.run.mock.calls).toEqual([[pb.id, [{ hostname: 'web.lan', groups: ['web'] }]]]);
    expect(h.fetchContent).not.toHaveBeenCalled();
    expect(get(ansibleRunning)).toBe(false); // reset in finally despite the run failure
    expect(h.reportError).toHaveBeenCalledWith('no terminal');
  });

  it('does nothing without a selected playbook or servers', async () => {
    await seed();
    // No playbook selected -> pipeline is not entered.
    toggleServer('s1');
    await runPlaybook();
    expect(h.run).not.toHaveBeenCalled();
  });

  it('toggleTag selects the whole group, then deselects it when fully selected', async () => {
    await seed();
    toggleTag('web'); // s1 + s2 share tag "web"
    expect([...get(ansibleSelectedServerIds)].sort()).toEqual(['s1', 's2']);
    toggleTag('web'); // all selected -> deselect the group
    expect([...get(ansibleSelectedServerIds)]).toEqual([]);
    // Partial selection -> toggle adds the rest instead of deselecting.
    toggleServer('s1');
    toggleTag('web');
    expect([...get(ansibleSelectedServerIds)].sort()).toEqual(['s1', 's2']);
  });
});

// R-0261: a network error from the backend carries the ERR_* codes in its source chain
// (error.rs); they are for the code, the page shows the prose.
const PIN_MISMATCH =
  'error sending request: client error (Connect): ' +
  'ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für x hat sich geändert';
const PROSE =
  'error sending request: client error (Connect): ' +
  'AdminHelper TOFU: Das Server-Zertifikat für x hat sich geändert';

describe('ansible store: a failed load without the machine codes (R-0261)', () => {
  it('keeps the prose for the page', async () => {
    h.fetchPlaybooks.mockRejectedValueOnce(PIN_MISMATCH);
    h.fetchServers.mockResolvedValueOnce([]);
    await loadAnsibleData();
    expect(get(ansibleLoadError)).toBe(PROSE);
  });
});
