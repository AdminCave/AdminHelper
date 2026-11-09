// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The Ansible page (R-1064): the playbook rail, the detail head with edit and run, the target
// picker (servers via checkboxes, tags via chips) and the run gate. The ansible store runs for real
// against a mocked API and bridge; the playbook modal is stubbed.
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/svelte';
import type { Playbook, Server } from '$lib/api/types';
import type { Connection, ResolvedConnection, TunnelMapping } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  fetchPlaybooks: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  fetchServers: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  ansibleRun: vi.fn(async (..._a: unknown[]) => undefined),
  openAnsible: vi.fn(async (..._a: unknown[]) => true),
  sshConsole: 'external' as 'external' | 'embedded',
  modal: vi.fn(),
  reportError: vi.fn(),
  resolveConnection: vi.fn(),
  connections: [] as unknown[],
  mappings: [] as unknown[],
}));

vi.mock('$lib/api/ansible', () => ({
  ansibleApi: { fetchPlaybooks: h.fetchPlaybooks, fetchServers: h.fetchServers },
}));
vi.mock('$lib/bridge', () => ({
  ansibleRun: h.ansibleRun,
  resolveConnection: h.resolveConnection,
}));
vi.mock('$lib/stores/connections', async () => {
  const { readable } = await import('svelte/store');
  return {
    connections: readable<unknown[]>([], (set) => {
      set(h.connections);
    }),
  };
});
vi.mock('$lib/stores/tunnel', () => ({ getMappings: () => h.mappings }));
vi.mock('$lib/stores/session', () => ({
  currentSession: () => ({ serverUrl: 'https://srv.example', username: 'a', isAdmin: true }),
  sessionStore: {
    subscribe(fn: (v: unknown) => void) {
      fn({ settings: { sshConsole: h.sshConsole } });
      return () => {};
    },
  },
}));
vi.mock('$lib/stores/terminals', () => ({ openAnsible: h.openAnsible }));
vi.mock('$lib/stores/statusBar', () => ({ showStatus: vi.fn(), reportError: h.reportError }));
vi.mock('../components/ansible/PlaybookModal.svelte', () => ({ default: h.modal }));

import { setLanguage } from '$lib/i18n';
import { clearSelection } from '$lib/stores/ansible';
import Ansible from './Ansible.svelte';

const playbooks: Playbook[] = [
  {
    id: 'p1',
    name: 'apt-upgrade',
    filename: 'apt-upgrade.yml',
    description: 'Pakete',
    tags: ['linux'],
  },
  { id: 'p2', name: 'reboot', filename: 'reboot.yml' },
];
const servers: Server[] = [
  { id: 's1', name: 'web-01', hostname: 'web-01.example', tags: ['prod'] },
  { id: 's2', name: 'db-01', hostname: 'db-01.example', tags: ['prod', 'db'] },
];

function items(): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.pb-item'));
}
function action(name: string): HTMLButtonElement {
  return document.querySelector(`[data-action="${name}"]`) as HTMLButtonElement;
}

async function mount() {
  render(Ansible);
  await waitFor(() => expect(items()).toHaveLength(2));
}

beforeAll(() => setLanguage('de'));
beforeEach(() => {
  h.fetchPlaybooks.mockReset();
  h.fetchPlaybooks.mockResolvedValue(playbooks);
  h.fetchServers.mockReset();
  h.fetchServers.mockResolvedValue(servers);
  h.ansibleRun.mockReset();
  h.ansibleRun.mockResolvedValue(undefined);
  h.openAnsible.mockClear();
  h.sshConsole = 'external';
  h.modal.mockReset();
  h.reportError.mockReset();
  h.connections = [];
  h.mappings = [];
  h.resolveConnection.mockReset();
  h.resolveConnection.mockImplementation(
    async (connection: Connection): Promise<ResolvedConnection> => ({
      connection,
      viaTunnel: false,
    }),
  );
  clearSelection();
});
afterEach(() => cleanup());

describe('Ansible', () => {
  it('lists the playbooks in the rail and prompts until one is chosen', async () => {
    await mount();
    expect(items().map((b) => b.querySelector('.pb-item-name')?.textContent)).toEqual([
      'apt-upgrade',
      'reboot',
    ]);
    expect(items()[0].querySelector('.pb-item-file')?.textContent).toBe('apt-upgrade.yml');
    expect(items()[0].querySelector('.pb-item-desc')?.textContent).toBe('Pakete');
    expect(document.querySelector('.ansible-detail')?.textContent).toContain(
      'Waehle links ein Playbook.',
    );
    expect(action('playbook-run')).toBeNull();
    expect(action('playbook-new').textContent?.trim()).toBe('Playbook');
  });

  it('opens a playbook in the detail pane and marks it active', async () => {
    await mount();
    await fireEvent.click(items()[1]);
    expect(items()[1].classList.contains('active')).toBe(true);
    expect(items()[1].getAttribute('aria-current')).toBe('true');
    expect(items()[0].getAttribute('aria-current')).toBeNull();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('reboot');
    expect(action('playbook-edit').textContent?.trim()).toBe('Bearbeiten');
  });

  it('gates the run on a selected server and runs on the chosen targets', async () => {
    await mount();
    await fireEvent.click(items()[0]);
    expect(action('playbook-run').disabled).toBe(true);
    expect(document.querySelector('.pb-summary')?.textContent).toContain(
      'Waehle ein Playbook und mindestens einen Server.',
    );
    const box = screen.getByRole('checkbox', { name: /db-01/ }) as HTMLInputElement;
    await fireEvent.click(box);
    expect(box.checked).toBe(true);
    expect(action('playbook-run').disabled).toBe(false);
    expect(document.querySelector('.pb-summary')?.textContent).toMatch(/apt-upgrade\s+auf\s+1/);
    await fireEvent.click(action('playbook-run'));
    await waitFor(() => expect(h.ansibleRun).toHaveBeenCalledTimes(1));
    expect(h.ansibleRun.mock.calls[0][0]).toBe('p1');
    expect(h.ansibleRun.mock.calls[0][2]).toBe(false);
    expect(h.openAnsible).not.toHaveBeenCalled();
  });

  it('runs a dry run in a terminal tab when the terminal is embedded (R-1073)', async () => {
    h.sshConsole = 'embedded';
    await mount();
    await fireEvent.click(items()[0]);
    await fireEvent.click(screen.getByRole('checkbox', { name: /db-01/ }));
    const check = screen.getByRole('checkbox', { name: /--check/ }) as HTMLInputElement;
    expect(check.checked).toBe(false);
    await fireEvent.click(check);
    expect(check.checked).toBe(true);
    await fireEvent.click(action('playbook-run'));
    await waitFor(() => expect(h.openAnsible).toHaveBeenCalledTimes(1));
    expect(h.openAnsible).toHaveBeenCalledWith(
      'p1',
      'apt-upgrade',
      [{ hostname: 'db-01.example', groups: ['prod', 'db'] }],
      true,
    );
    expect(h.ansibleRun).not.toHaveBeenCalled();
  });

  it('hands the dry run to the OS terminal as well', async () => {
    await mount();
    await fireEvent.click(items()[0]);
    await fireEvent.click(screen.getByRole('checkbox', { name: /web-01/ }));
    await fireEvent.click(screen.getByRole('checkbox', { name: /--check/ }));
    await fireEvent.click(action('playbook-run'));
    await waitFor(() => expect(h.ansibleRun).toHaveBeenCalledTimes(1));
    expect(h.ansibleRun.mock.calls[0][2]).toBe(true);
  });

  it('switches to tag targets and selects every server of a tag', async () => {
    await mount();
    await fireEvent.click(items()[0]);
    await fireEvent.click(screen.getByRole('radio', { name: 'Nach Tags' }));
    // No server checkboxes left; the dry run (R-1073) is the only one.
    expect(screen.getAllByRole('checkbox')).toEqual([
      screen.getByRole('checkbox', { name: /--check/ }),
    ]);
    const chips = Array.from(document.querySelectorAll<HTMLButtonElement>('.pb-tag-chip'));
    expect(chips.map((c) => c.textContent?.trim())).toEqual(['db (1)', 'prod (2)']);
    await fireEvent.click(chips[1]);
    expect(chips[1].getAttribute('aria-pressed')).toBe('true');
    expect(chips[0].getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('.pb-summary')?.textContent).toMatch(/auf\s+2/);
    expect(action('playbook-run').disabled).toBe(false);
  });
  describe('reaches each server like Verbinden (R-1202)', () => {
    const ssh = (id: string, serverId: string, over: Partial<Connection> = {}): Connection => ({
      id,
      name: id,
      kind: 'ssh',
      host: '192.0.2.20',
      port: 22,
      username: 'ops',
      tags: [],
      trustCert: false,
      serverId,
      ...over,
    });
    const stcp: TunnelMapping = {
      id: 't1',
      serverId: 's2',
      tunnelType: 'stcp',
      protocol: 'tcp',
      localPort: 22,
      visitorPort: 6022,
      customDomains: null,
      connectionId: null,
      enabled: true,
      name: 'db-ssh',
    };

    function row(name: RegExp): HTMLElement {
      return screen.getByRole('checkbox', { name }).closest('.pb-server') as HTMLElement;
    }

    async function choose(...names: RegExp[]) {
      await mount();
      await fireEvent.click(items()[0]);
      for (const name of names) await fireEvent.click(screen.getByRole('checkbox', { name }));
    }

    it('marks a server without SSH connection and offers a choice where it has several', async () => {
      h.connections = [
        ssh('db-zeta', 's2'),
        ssh('db-rdp', 's2', { kind: 'rdp' }),
        ssh('db-alpha', 's2'),
      ];
      await choose();
      expect(
        row(/web-01/)
          .querySelector('.pb-server-hostname')
          ?.textContent?.trim(),
      ).toBe('Hostname');
      expect(row(/db-01/).querySelector('.pb-server-hostname')).toBeNull();
      const via = screen.getByRole('combobox', {
        name: 'SSH-Verbindung fuer db-01',
      }) as HTMLSelectElement;
      expect(Array.from(via.options).map((o) => o.value)).toEqual(['db-alpha', 'db-zeta']);
      expect(via.value).toBe('db-alpha');
    });

    it('runs over the chosen connection, resolved, and over the hostname without one', async () => {
      h.connections = [ssh('db-alpha', 's2'), ssh('db-zeta', 's2', { host: '127.0.0.1' })];
      h.resolveConnection.mockImplementation(async (connection: Connection) => ({
        connection: { ...connection, port: 23001 },
        viaTunnel: true,
        tunnelName: 'db-ssh',
        tunnelType: 'stcp',
      }));
      await choose(/web-01/, /db-01/);
      const via = screen.getByRole('combobox', { name: 'SSH-Verbindung fuer db-01' });
      await fireEvent.change(via, { target: { value: 'db-zeta' } });
      await fireEvent.click(action('playbook-run'));
      await waitFor(() => expect(h.ansibleRun).toHaveBeenCalledTimes(1));
      expect(h.resolveConnection).toHaveBeenCalledTimes(1);
      expect(h.ansibleRun.mock.calls[0][1]).toEqual([
        { hostname: 'web-01.example', groups: ['prod'] },
        {
          hostname: 'db-01.example',
          groups: ['prod', 'db'],
          connection: { ...ssh('db-zeta', 's2', { host: '127.0.0.1' }), port: 23001 },
        },
      ]);
    });

    it('starts one run when clicked again while the targets resolve', async () => {
      h.connections = [ssh('db-alpha', 's2')];
      let release: () => void = () => {};
      h.resolveConnection.mockImplementation(
        (connection: Connection) =>
          new Promise<ResolvedConnection>((resolve) => {
            release = () => resolve({ connection, viaTunnel: false });
          }),
      );
      await choose(/db-01/);
      await fireEvent.click(action('playbook-run'));
      await waitFor(() => expect(h.resolveConnection).toHaveBeenCalledTimes(1));
      expect(action('playbook-run').disabled).toBe(true);
      await fireEvent.click(action('playbook-run'));
      release();
      await waitFor(() => expect(h.ansibleRun).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(action('playbook-run').disabled).toBe(false));
      expect(h.resolveConnection).toHaveBeenCalledTimes(1);
      expect(h.ansibleRun).toHaveBeenCalledTimes(1);
    });

    it('starts nothing when the tunnel visitor of a server does not run', async () => {
      h.connections = [ssh('db-auto', 's2', { host: '127.0.0.1', port: 6022 })];
      h.mappings = [stcp];
      await choose(/db-01/);
      await fireEvent.click(action('playbook-run'));
      await waitFor(() => expect(h.reportError).toHaveBeenCalledTimes(1));
      expect(h.reportError.mock.calls[0][0]).toContain('db-01');
      expect(h.reportError.mock.calls[0][0]).toContain('Tunnel');
      expect(h.ansibleRun).not.toHaveBeenCalled();
      expect(h.openAnsible).not.toHaveBeenCalled();
    });

    it('starts nothing when Rust refuses the target of a server', async () => {
      h.sshConsole = 'embedded';
      h.connections = [ssh('db-alpha', 's2', { host: '127.0.0.1', port: 23005 })];
      h.resolveConnection.mockRejectedValue(
        'port 23005 on this machine belongs to the tunnel of another workspace',
      );
      await choose(/db-01/);
      await fireEvent.click(action('playbook-run'));
      await waitFor(() => expect(h.reportError).toHaveBeenCalledTimes(1));
      expect(h.reportError.mock.calls[0][0]).toMatch(/db-01.*port 23005/);
      expect(h.openAnsible).not.toHaveBeenCalled();
    });
  });
});
