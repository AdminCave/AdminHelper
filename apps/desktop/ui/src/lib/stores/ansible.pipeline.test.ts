// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The non-trivial ansible store logic (6.41): runPlaybook's pipeline order
// (fetchContent -> generateInventory -> writePlaybook -> launch) with the running-flag reset in the
// finally even on failure, and toggleTag's all-selected group toggle. A hung running flag would block
// the wizard forever; the plain selection tests don't touch either.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { Playbook, Server } from '$lib/api/types';

const h = vi.hoisted(() => ({
  session: { serverUrl: 'https://x', token: 't' } as unknown,
  fetchPlaybooks: vi.fn(),
  fetchServers: vi.fn(),
  fetchContent: vi.fn(),
  generateInventory: vi.fn(),
  writePlaybook: vi.fn(),
  launch: vi.fn(),
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
vi.mock('$lib/bridge', () => ({
  ansibleGenerateInventory: h.generateInventory,
  ansibleWritePlaybook: h.writePlaybook,
  ansibleLaunch: h.launch,
}));
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

    const order: string[] = [];
    h.fetchContent.mockImplementation(async () => {
      order.push('fetchContent');
      return { content: 'yaml' };
    });
    h.generateInventory.mockImplementation(async () => {
      order.push('generateInventory');
      return '/inv';
    });
    h.writePlaybook.mockImplementation(async () => {
      order.push('writePlaybook');
      return '/pb';
    });
    h.launch.mockImplementation(async () => {
      order.push('launch');
      throw new Error('no terminal');
    });

    await runPlaybook();

    expect(order).toEqual(['fetchContent', 'generateInventory', 'writePlaybook', 'launch']);
    expect(get(ansibleRunning)).toBe(false); // reset in finally despite the launch failure
    expect(h.reportError).toHaveBeenCalled();
  });

  it('does nothing without a selected playbook or servers', async () => {
    await seed();
    // No playbook selected -> pipeline is not entered.
    toggleServer('s1');
    await runPlaybook();
    expect(h.fetchContent).not.toHaveBeenCalled();
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
