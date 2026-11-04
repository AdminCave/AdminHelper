// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The Ansible page (R-1064): the playbook rail, the detail head with edit and run, the target
// picker (servers via checkboxes, tags via chips) and the run gate. The ansible store runs for real
// against a mocked API and bridge; the playbook modal is stubbed.
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/svelte';
import type { Playbook, Server } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchPlaybooks: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  fetchServers: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  ansibleRun: vi.fn(async (..._a: unknown[]) => undefined),
  modal: vi.fn(),
}));

vi.mock('$lib/api/ansible', () => ({
  ansibleApi: { fetchPlaybooks: h.fetchPlaybooks, fetchServers: h.fetchServers },
}));
vi.mock('$lib/bridge', () => ({ ansibleRun: h.ansibleRun }));
vi.mock('$lib/stores/session', () => ({
  currentSession: () => ({ serverUrl: 'https://srv.example', username: 'a', isAdmin: true }),
}));
vi.mock('$lib/stores/statusBar', () => ({ showStatus: vi.fn(), reportError: vi.fn() }));
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
  h.modal.mockReset();
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
  });

  it('switches to tag targets and selects every server of a tag', async () => {
    await mount();
    await fireEvent.click(items()[0]);
    await fireEvent.click(screen.getByRole('radio', { name: 'Nach Tags' }));
    expect(screen.queryByRole('checkbox')).toBeNull();
    const chips = Array.from(document.querySelectorAll<HTMLButtonElement>('.pb-tag-chip'));
    expect(chips.map((c) => c.textContent?.trim())).toEqual(['db (1)', 'prod (2)']);
    await fireEvent.click(chips[1]);
    expect(chips[1].getAttribute('aria-pressed')).toBe('true');
    expect(chips[0].getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('.pb-summary')?.textContent).toMatch(/auf\s+2/);
    expect(action('playbook-run').disabled).toBe(false);
  });
});
