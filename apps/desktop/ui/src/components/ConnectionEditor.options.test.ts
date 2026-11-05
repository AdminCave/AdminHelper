// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Per-connection options (R-1066): SSH on the Options tab, RDP on the Display tab, the SSH
// sign-in method on Sign-in. A field left on "Global" or empty is not saved, so the global
// setting holds.

import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { setLanguage } from '$lib/i18n';

const h = vi.hoisted(() => ({
  upsert: vi.fn(async (..._a: unknown[]) => {}),
  error: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({}));
vi.mock('$lib/stores/connections', () => ({ upsert: h.upsert, remove: vi.fn() }));
vi.mock('$lib/stores/connectFlow', () => ({ initiateConnect: vi.fn() }));
vi.mock('$lib/stores/session', async () => {
  const { writable, get } = await import('svelte/store');
  const session = writable(null);
  return { settings: writable(null), session, currentSession: () => get(session) };
});
vi.mock('$lib/api/servers', () => ({ serversApi: { list: vi.fn(async () => []) } }));
vi.mock('$lib/stores/statusBar', async (orig) => ({
  ...(await orig<object>()),
  reportError: h.error,
}));

import { emptyConnection } from '$lib/models/connection';
import type { Connection } from '$lib/bridge/types';
import { openEditor, closeEditor } from '$lib/stores/editor';
import ConnectionEditor from './ConnectionEditor.svelte';

async function open(conn: Connection): Promise<HTMLElement> {
  openEditor(conn);
  const { container } = render(ConnectionEditor);
  await tick();
  return container;
}

const selectTab = (c: HTMLElement, id: string): Promise<boolean> =>
  fireEvent.click(c.querySelector<HTMLElement>(`[role="tab"][data-tab="${id}"]`)!);

async function choose(c: HTMLElement, name: string, value: string): Promise<void> {
  const el = c.querySelector<HTMLSelectElement>(`select[name="${name}"]`)!;
  el.value = value;
  await fireEvent.change(el);
}

async function type(el: HTMLInputElement, value: string): Promise<void> {
  await fireEvent.input(el, { target: { value } });
}

const field = (c: HTMLElement, name: string, i = 0): HTMLInputElement =>
  c.querySelectorAll<HTMLInputElement>(`[name="${name}"]`)[i];

async function save(c: HTMLElement): Promise<Connection | undefined> {
  await fireEvent.click(c.querySelector<HTMLElement>('.btn.save')!);
  return (h.upsert.mock.calls.at(-1) as [Connection] | undefined)?.[0];
}

beforeAll(() => setLanguage('en'));

afterEach(() => {
  cleanup();
  closeEditor();
  h.upsert.mockClear();
  h.error.mockClear();
});

const ssh = (): Connection => ({ ...emptyConnection('ssh'), name: 'web01', host: 'web01.lan' });
const rdp = (): Connection => ({ ...emptyConnection('rdp'), name: 'dc01', host: 'dc01.lan' });

describe('ConnectionEditor SSH options', () => {
  it('saves jump host, forwards, toggles, keepalive and sign-in method', async () => {
    const c = await open(ssh());
    await selectTab(c, 'auth');
    await choose(c, 'authMethod', 'agent');

    await selectTab(c, 'options');
    await type(field(c, 'jumpHost'), ' ops@bastion:2222 ');
    await fireEvent.click(c.querySelector<HTMLElement>('[data-testid="forward-add"]')!);
    await fireEvent.click(c.querySelector<HTMLElement>('[data-testid="forward-add"]')!);
    await type(field(c, 'forwardListen', 0), '8080');
    await type(field(c, 'forwardTarget', 0), 'intranet:80');
    const second = c.querySelectorAll<HTMLSelectElement>('select[name="forwardType"]')[1];
    second.value = 'D';
    await fireEvent.change(second);
    await type(field(c, 'forwardListen', 1), '1080');
    // A dynamic forward has no target field.
    expect(c.querySelectorAll('[name="forwardTarget"]')).toHaveLength(1);
    await choose(c, 'agentForwarding', 'off');
    await choose(c, 'compression', 'on');
    await type(field(c, 'keepalive'), '30');

    const saved = await save(c);
    expect(saved?.options).toEqual({
      ssh: {
        jumpHost: 'ops@bastion:2222',
        forwards: [
          { type: 'L', listen: '8080', target: 'intranet:80' },
          { type: 'D', listen: '1080' },
        ],
        agentForwarding: false,
        compression: true,
        keepalive: 30,
        authMethod: 'agent',
      },
    });
  });

  it('saves no options when everything stays on Global or empty', async () => {
    const c = await open(ssh());
    await selectTab(c, 'options');
    await fireEvent.click(c.querySelector<HTMLElement>('[data-testid="forward-add"]')!);
    expect((await save(c))?.options).toBeNull();
  });

  it('loads saved options, and Global clears a value', async () => {
    const c = await open({
      ...ssh(),
      options: {
        ssh: {
          compression: true,
          keepalive: 15,
          forwards: [{ type: 'R', listen: '9000', target: 'localhost:9000' }],
        },
      },
    });
    await selectTab(c, 'options');
    expect(c.querySelector<HTMLSelectElement>('select[name="compression"]')?.value).toBe('on');
    expect(field(c, 'keepalive').value).toBe('15');
    expect(field(c, 'forwardTarget').value).toBe('localhost:9000');

    await choose(c, 'compression', '');
    await type(field(c, 'keepalive'), '');
    await fireEvent.click(c.querySelector<HTMLElement>('[data-testid="forward-row"] button')!);
    expect((await save(c))?.options).toBeNull();
  });

  it('refuses a keepalive out of range and a local forward without target', async () => {
    const c = await open(ssh());
    await selectTab(c, 'options');
    await type(field(c, 'keepalive'), '0');
    expect(await save(c)).toBeUndefined();
    expect(h.error).toHaveBeenLastCalledWith('Keepalive must be between 1 and 3600 seconds');

    await type(field(c, 'keepalive'), '');
    await fireEvent.click(c.querySelector<HTMLElement>('[data-testid="forward-add"]')!);
    await type(field(c, 'forwardListen'), '8080');
    expect(await save(c)).toBeUndefined();
    expect(h.error).toHaveBeenLastCalledWith('Local and remote forwards need a target host:port');
  });
});

describe('ConnectionEditor RDP display options', () => {
  it('saves display, redirections, security and gateway', async () => {
    const c = await open(rdp());
    expect(c.querySelector('[role="tab"][data-tab="options"]')).toBeNull();
    await selectTab(c, 'display');
    await choose(c, 'scalingMode', 'hdpi');
    await choose(c, 'windowMode', 'custom');
    await type(field(c, 'customSize'), '1280x720');
    await choose(c, 'performanceProfile', 'lan');
    await choose(c, 'drives', 'on');
    await choose(c, 'audio', 'remote');
    await choose(c, 'printers', 'off');
    await choose(c, 'nla', 'on');
    await type(field(c, 'gateway'), 'rdgw.example.org:443');

    expect((await save(c))?.options).toEqual({
      rdp: {
        scalingMode: 'hdpi',
        windowMode: 'custom',
        customSize: '1280x720',
        performanceProfile: 'lan',
        drives: true,
        audio: 'remote',
        printers: false,
        nla: true,
        gateway: 'rdgw.example.org:443',
      },
    });
  });

  it('keeps only the options of the saved kind', async () => {
    const c = await open({
      ...rdp(),
      options: { rdp: { nla: false }, ssh: { compression: true } },
    });
    expect((await save(c))?.options).toEqual({ rdp: { nla: false } });
  });

  it('refuses an invalid custom size', async () => {
    const c = await open(rdp());
    await selectTab(c, 'display');
    await type(field(c, 'customSize'), '1920x');
    expect(await save(c)).toBeUndefined();
    expect(h.error).toHaveBeenLastCalledWith('Invalid RDP size (e.g. 1920x1080).');
  });
});
