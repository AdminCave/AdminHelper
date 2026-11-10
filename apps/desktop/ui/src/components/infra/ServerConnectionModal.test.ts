// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Create-a-connection flow at the component level: mount the real
// ServerConnectionModal, drive the form, and assert the payload handed to
// connectionsApi plus the ssh/web conditional fields. The IPC/server boundary is
// mocked (connectionsApi), so no Tauri runtime or server is needed — this covers
// the "anlegen" UI logic; actually opening SSH/RDP/web is platform behaviour
// verified manually.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { setLanguage } from '$lib/i18n';

vi.mock('$lib/api/connections', () => ({
  connectionsApi: {
    create: vi.fn(async () => ({ id: 'conn-1' })),
    update: vi.fn(async () => ({ id: 'conn-1' })),
    remove: vi.fn(async () => {}),
  },
}));
vi.mock('$lib/stores/statusBar', () => ({
  showStatus: vi.fn(),
  reportError: vi.fn(),
}));
vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return {
    session: readable({
      serverUrl: 'https://test.local',
      username: 'admin',
      isAdmin: true,
    }),
  };
});

import ServerConnectionModal from './ServerConnectionModal.svelte';
import { connectionsApi } from '$lib/api/connections';
import { reportError } from '$lib/stores/statusBar';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const SERVER = { id: 'srv-1', name: 'web01.example.org', hostname: 'web01.example.org' };

function openModal(props: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const utils = render(ServerConnectionModal, {
    props: { open: true, target: null, server: SERVER, onClose, onSaved, ...props },
  });
  return { ...utils, onClose, onSaved };
}

const textInputs = (c: HTMLElement) =>
  Array.from(c.querySelectorAll('input[type="text"]')) as HTMLInputElement[];
const numberInputs = (c: HTMLElement) =>
  Array.from(c.querySelectorAll('input[type="number"]')) as HTMLInputElement[];
const kindSelect = (c: HTMLElement) => c.querySelector('select') as HTMLSelectElement;
const saveBtn = (c: HTMLElement) => c.querySelector('.btn.primary') as HTMLButtonElement;

describe('ServerConnectionModal create flow', () => {
  it('builds an ssh payload and calls connectionsApi.create', async () => {
    const { container, onSaved, onClose } = openModal();
    await tick();

    const [name, host, username, keyPath] = textInputs(container);
    await fireEvent.input(name, { target: { value: 'db' } });
    await fireEvent.input(host, { target: { value: '10.0.0.5' } });
    await fireEvent.input(numberInputs(container)[0], { target: { value: '22' } });
    await fireEvent.input(username, { target: { value: 'root' } });
    await fireEvent.input(keyPath, { target: { value: '/home/me/.ssh/id_ed25519' } });
    await fireEvent.click(saveBtn(container));
    await tick();

    expect(connectionsApi.create).toHaveBeenCalledTimes(1);
    expect(vi.mocked(connectionsApi.create).mock.calls[0][1]).toEqual({
      name: 'db',
      label: 'db',
      kind: 'ssh',
      host: '10.0.0.5',
      port: 22,
      username: 'root',
      domain: null,
      keyPath: '/home/me/.ssh/id_ed25519',
      url: null,
      notes: null,
      tags: [],
      trustCert: false,
      serverId: 'srv-1',
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('switching to web swaps host/port for a URL field and builds a web payload', async () => {
    const { container } = openModal();
    await tick();

    expect(textInputs(container).length).toBe(5); // ssh: name, host, username, keyPath, tags

    await fireEvent.change(kindSelect(container), { target: { value: 'web' } });
    await tick();

    expect(container.querySelector('input[type="url"]')).toBeTruthy();
    expect(numberInputs(container)).toHaveLength(0); // no port field for web
    expect(textInputs(container).length).toBe(2); // web: name, tags only

    await fireEvent.input(textInputs(container)[0], { target: { value: 'proxmox' } });
    await fireEvent.input(container.querySelector('input[type="url"]') as HTMLInputElement, {
      target: { value: 'https://pve.example:8006' },
    });
    await fireEvent.click(saveBtn(container));
    await tick();

    expect(vi.mocked(connectionsApi.create).mock.calls[0][1]).toMatchObject({
      kind: 'web',
      url: 'https://pve.example:8006',
      host: null,
      port: null,
    });
  });

  it('blocks save and reports an error when the required host is missing', async () => {
    const { container } = openModal();
    await tick();

    // The host starts at the server's address; emptied, ssh lacks one -> validation fails.
    await fireEvent.input(textInputs(container)[0], { target: { value: 'incomplete' } });
    await fireEvent.input(textInputs(container)[1], { target: { value: '' } });
    await fireEvent.click(saveBtn(container));
    await tick();

    expect(reportError).toHaveBeenCalledTimes(1);
    expect(connectionsApi.create).not.toHaveBeenCalled();
  });
});

describe('ServerConnectionModal names (R-1210)', () => {
  it('starts at the server address and shows the derived display name', async () => {
    const { container, getByTestId } = openModal();
    await tick();
    const [own, host] = textInputs(container);
    expect(host.value).toBe('web01.example.org');
    expect(own.placeholder).toBe('SSH');
    expect(getByTestId('shown-as').textContent).toContain('web01.example.org · SSH');
    await fireEvent.input(own, { target: { value: 'root' } });
    expect(getByTestId('shown-as').textContent).toContain('web01.example.org · root');
  });

  it('saves without an own text: the label is empty, the name the server name', async () => {
    const { container } = openModal();
    await tick();
    await fireEvent.click(saveBtn(container));
    await tick();
    expect(vi.mocked(connectionsApi.create).mock.calls[0][1]).toMatchObject({
      name: 'web01.example.org',
      label: '',
      host: 'web01.example.org',
      serverId: 'srv-1',
    });
  });

  it('edits the stored own text, not the display name', async () => {
    const target = {
      id: 'c-1',
      name: 'web01.example.org · backup',
      label: 'backup',
      kind: 'ssh',
      host: 'web01.example.org',
      serverId: 'srv-1',
    };
    const { container } = openModal({ target });
    await tick();
    expect(textInputs(container)[0].value).toBe('backup');
  });

  it('keeps the host of an existing web connection and marks one over a tunnel', async () => {
    const target = {
      id: 'c-web',
      name: 'web01.example.org · Web (FRP)',
      label: '',
      kind: 'web',
      host: '127.0.0.1',
      port: 6005,
      url: 'http://127.0.0.1:6005',
      serverId: 'srv-1',
    };
    const { container, getByTestId } = openModal({ target });
    await tick();
    expect(getByTestId('shown-as').textContent).toContain('web01.example.org · Web (FRP)');
    await fireEvent.click(saveBtn(container));
    await tick();
    expect(vi.mocked(connectionsApi.update).mock.calls[0][2]).toMatchObject({
      kind: 'web',
      host: '127.0.0.1',
    });
  });
});
