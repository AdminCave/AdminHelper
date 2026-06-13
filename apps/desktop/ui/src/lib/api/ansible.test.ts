// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { PlaybookInput } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { ansibleApi } from './ansible';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);
const input: PlaybookInput = {
  name: 'reboot',
  filename: 'reboot.yml',
  description: '',
  tags: [],
  content: '- hosts: all',
};

describe('ansibleApi', () => {
  beforeEach(() => proxy.mockClear());

  it('fetchPlaybooks → GET /api/ansible/playbooks', async () => {
    await ansibleApi.fetchPlaybooks(session);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/ansible/playbooks',
      undefined,
      false,
    );
  });

  it('fetchContent → GET /api/ansible/playbooks/:id/content', async () => {
    await ansibleApi.fetchContent(session, 'p1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/ansible/playbooks/p1/content',
      undefined,
      false,
    );
  });

  it('fetchServers → GET /api/servers', async () => {
    await ansibleApi.fetchServers(session);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/servers',
      undefined,
      false,
    );
  });

  it('createPlaybook → POST /api/ansible/playbooks', async () => {
    await ansibleApi.createPlaybook(session, input);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'POST',
      '/api/ansible/playbooks',
      JSON.stringify(input),
      false,
    );
  });

  it('updatePlaybook → PUT /api/ansible/playbooks/:id', async () => {
    await ansibleApi.updatePlaybook(session, 'p1', input);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'PUT',
      '/api/ansible/playbooks/p1',
      JSON.stringify(input),
      false,
    );
  });

  it('removePlaybook → DELETE /api/ansible/playbooks/:id', async () => {
    await ansibleApi.removePlaybook(session, 'p1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'DELETE',
      '/api/ansible/playbooks/p1',
      undefined,
      false,
    );
  });
});
