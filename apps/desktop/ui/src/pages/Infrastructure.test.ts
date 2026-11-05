// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The infrastructure page (R-1064): the server rail with search and "+ Server", the detail head
// with its edit action, the tabs and the overview panel. The data-fetching tabs and the modal are
// stubbed; the infra store runs for real against a mocked server API.
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import type { Server } from '$lib/api/types';

const h = vi.hoisted(() => ({
  list: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  connectionsTab: vi.fn(),
  tunnelsTab: vi.fn(),
  monitoringTab: vi.fn(),
  provisioningTab: vi.fn(),
}));

vi.mock('$lib/api/servers', () => ({
  serversApi: { list: h.list, create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('$lib/api/monitoring', () => ({ monitoringApi: { assignTemplate: vi.fn() } }));
vi.mock('$lib/stores/session', () => ({
  currentSession: () => ({ serverUrl: 'https://srv.example', username: 'a', isAdmin: true }),
}));
vi.mock('$lib/stores/statusBar', () => ({ showStatus: vi.fn(), reportError: vi.fn() }));
vi.mock('../components/infra/ServerModal.svelte', () => ({ default: vi.fn() }));
vi.mock('../components/infra/tabs/ConnectionsTab.svelte', () => ({ default: h.connectionsTab }));
vi.mock('../components/infra/tabs/TunnelsTab.svelte', () => ({ default: h.tunnelsTab }));
vi.mock('../components/infra/tabs/MonitoringTab.svelte', () => ({ default: h.monitoringTab }));
vi.mock('../components/infra/tabs/ProvisioningTab.svelte', () => ({
  default: h.provisioningTab,
}));

import { setLanguage } from '$lib/i18n';
import {
  serverEditor,
  closeServerEditor,
  setInfraSearch,
  setSelectedServer,
} from '$lib/stores/infra';
import Infrastructure from './Infrastructure.svelte';

const servers: Server[] = [
  {
    id: 's2',
    name: 'web-01',
    hostname: 'web-01.example',
    osType: 'Debian 13',
    tags: ['prod', 'web'],
    notes: 'Frontend',
  },
  { id: 's1', name: 'db-01', hostname: 'db-01.example', osType: 'Windows Server 2025' },
];

function names(): string[] {
  return Array.from(document.querySelectorAll('.srv-item .srv-item-name')).map(
    (n) => n.textContent ?? '',
  );
}

async function mount() {
  render(Infrastructure);
  await waitFor(() => expect(names()).toHaveLength(2));
}

beforeAll(() => setLanguage('de'));
beforeEach(() => {
  h.list.mockReset();
  h.list.mockResolvedValue(servers);
  for (const f of [h.connectionsTab, h.tunnelsTab, h.monitoringTab, h.provisioningTab])
    f.mockReset();
  setInfraSearch('');
  setSelectedServer(null);
  closeServerEditor();
});
afterEach(() => cleanup());

describe('Infrastructure', () => {
  it('lists the servers by name and opens the first one with its overview', async () => {
    await mount();
    expect(names()).toEqual(['db-01', 'web-01']);
    const active = document.querySelector('.srv-item.active');
    expect(active?.querySelector('.srv-item-name')?.textContent).toBe('db-01');
    expect(active?.getAttribute('aria-current')).toBe('true');
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('db-01');
    expect(screen.getByRole('tab', { name: 'Übersicht' }).getAttribute('aria-selected')).toBe(
      'true',
    );
    expect(screen.getByText('Stammdaten')).toBeTruthy();
    const dd = Array.from(document.querySelectorAll('.srv-overview dd')).map((n) => n.textContent);
    expect(dd).toEqual(['db-01.example', 'Windows Server 2025', '—', '—']);
  });

  it('shows host and tags in the rail and the tags in the overview', async () => {
    await mount();
    const web = Array.from(document.querySelectorAll('.srv-item'))[1];
    expect(web.querySelector('.srv-item-host')?.textContent).toBe('web-01.example');
    expect(
      Array.from(web.querySelectorAll('.srv-item-tags > *')).map((n) => n.textContent?.trim()),
    ).toEqual(['prod', 'web']);
    await fireEvent.click(web);
    expect(web.classList.contains('active')).toBe(true);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('web-01');
    const dd = Array.from(document.querySelectorAll('.srv-overview dd')).map((n) => n.textContent);
    expect(dd).toEqual(['web-01.example', 'Debian 13', 'prod, web', 'Frontend']);
  });

  it('filters the rail by the search and clears it again', async () => {
    await mount();
    const search = screen.getByRole('searchbox') as HTMLInputElement;
    await fireEvent.input(search, { target: { value: 'prod' } });
    expect(names()).toEqual(['web-01']);
    await fireEvent.input(search, { target: { value: 'nothing-matches' } });
    expect(names()).toEqual([]);
    expect(screen.getByText('Keine Server')).toBeTruthy();
    await fireEvent.input(search, { target: { value: '' } });
    expect(names()).toEqual(['db-01', 'web-01']);
  });

  it('switches the tabs and hands the selected server to the tab', async () => {
    await mount();
    const tab = screen.getByRole('tab', { name: 'Verbindungen' });
    expect(tab.getAttribute('data-tab')).toBe('connections');
    await fireEvent.click(tab);
    expect(tab.getAttribute('aria-selected')).toBe('true');
    expect(document.querySelector('.srv-overview')).toBeNull();
    expect(h.connectionsTab).toHaveBeenCalled();
    const props = h.connectionsTab.mock.calls.at(-1)?.[1] as { server: Server };
    expect(props.server.id).toBe('s1');
    await fireEvent.click(screen.getByRole('tab', { name: 'Provisionierung' }));
    expect(h.provisioningTab).toHaveBeenCalled();
  });

  it('opens the editor empty from "+ Server" and with the server from "Bearbeiten"', async () => {
    await mount();
    const add = document.querySelector('[data-action="server-new"]') as HTMLButtonElement;
    expect(add.textContent?.trim()).toBe('Server');
    await fireEvent.click(add);
    expect(get(serverEditor)).toEqual({ open: true, target: null });
    closeServerEditor();
    const edit = document.querySelector('[data-action="server-edit"]') as HTMLButtonElement;
    expect(edit.textContent?.trim()).toBe('Bearbeiten');
    await fireEvent.click(edit);
    expect(get(serverEditor).open).toBe(true);
    expect(get(serverEditor).target?.id).toBe('s1');
  });
});
