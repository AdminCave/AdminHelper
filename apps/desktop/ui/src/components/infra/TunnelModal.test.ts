// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Create-a-tunnel flow at the component level: mount the real TunnelModal, drive
// the form, and assert the snake_case payload handed to frpApi.createTunnel plus
// the stcp/https conditional fields. The IPC/server boundary is mocked (frpApi),
// so this needs no Tauri runtime, server or frpc — it verifies the "anlegen" UI
// logic. Live tunnel start/connect is covered separately (Rust unit tests for
// tunnel resolution; the from-outside integration test for the server path).

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { setLanguage } from '$lib/i18n';

vi.mock('$lib/api/frp', () => ({
  frpApi: {
    createTunnel: vi.fn(async () => ({ id: 'tun-1' })),
    updateTunnel: vi.fn(async () => ({ id: 'tun-1' })),
    removeTunnel: vi.fn(async () => {}),
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
      token: 't',
      refreshToken: 'r',
      username: 'admin',
      isAdmin: true,
    }),
  };
});

import TunnelModal from './TunnelModal.svelte';
import { frpApi } from '$lib/api/frp';
import { reportError } from '$lib/stores/statusBar';
import type { FrpConfig } from '$lib/api/types';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const configs: FrpConfig[] = [
  { id: 'cfg-1', name: 'FRP A', serverAddr: 'frp.example', bindPort: 7000 },
];

function openModal(props: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const utils = render(TunnelModal, {
    props: { open: true, editing: null, serverId: 'srv-1', configs, onClose, onSaved, ...props },
  });
  return { ...utils, onClose, onSaved };
}

// Label-based lookups (6.115): robust against field reorder / placeholder changes, unlike the old
// placeholder match and `select[1]` index which quietly fill the wrong field when the form changes.
const nameInput = (c: HTMLElement) => within(c).getByLabelText('Name') as HTMLInputElement;
const numberInputs = (c: HTMLElement) =>
  Array.from(c.querySelectorAll('input[type="number"]')) as HTMLInputElement[];
const typeSelect = (c: HTMLElement) => within(c).getByLabelText('Typ') as HTMLSelectElement;
const saveBtn = (c: HTMLElement) => c.querySelector('.btn.primary') as HTMLButtonElement;

describe('TunnelModal create flow', () => {
  it('builds an stcp payload and calls createTunnel (config preselected for a lone config)', async () => {
    const { container, onSaved, onClose } = openModal();
    await tick();

    await fireEvent.input(nameInput(container), { target: { value: 'k01-ssh' } });
    await fireEvent.input(numberInputs(container)[0], { target: { value: '22' } });
    await fireEvent.click(saveBtn(container));
    await tick();

    expect(frpApi.createTunnel).toHaveBeenCalledTimes(1);
    expect(vi.mocked(frpApi.createTunnel).mock.calls[0][1]).toEqual({
      server_id: 'srv-1',
      frp_config_id: 'cfg-1', // the only config is preselected on open
      name: 'k01-ssh',
      tunnel_type: 'stcp',
      protocol: 'ssh',
      local_ip: '127.0.0.1',
      local_port: 22,
      secret_key: null,
      custom_domains: null,
      visitor_port: null,
      auto_create_connection: false,
      auto_connection_username: null,
      tags: [],
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('switches to https: drops the stcp fields, shows custom domains, nulls secret/visitor', async () => {
    const { container } = openModal();
    await tick();

    // stcp default exposes two number inputs (local port + visitor port).
    expect(numberInputs(container)).toHaveLength(2);

    await fireEvent.change(typeSelect(container), { target: { value: 'https' } });
    await tick();

    // https has only the local port; visitor port is gone, custom domains appears.
    expect(numberInputs(container)).toHaveLength(1);
    const domains = container.querySelector(
      'input[placeholder="tunnel.example.net"]',
    ) as HTMLInputElement;
    expect(domains).toBeTruthy();

    await fireEvent.input(nameInput(container), { target: { value: 'k01-web' } });
    await fireEvent.input(numberInputs(container)[0], { target: { value: '8006' } });
    await fireEvent.input(domains, { target: { value: 'tunnel.example.net' } });
    await fireEvent.click(saveBtn(container));
    await tick();

    expect(vi.mocked(frpApi.createTunnel).mock.calls[0][1]).toMatchObject({
      tunnel_type: 'https',
      custom_domains: 'tunnel.example.net',
      secret_key: null,
      visitor_port: null,
    });
  });

  it('blocks save and reports an error when no FRP config is selected', async () => {
    // No lone config to preselect -> frpConfigId stays empty -> validation fails.
    const { container } = openModal({ configs: [] });
    await tick();

    await fireEvent.input(nameInput(container), { target: { value: 'x' } });
    await fireEvent.input(numberInputs(container)[0], { target: { value: '22' } });
    await fireEvent.click(saveBtn(container));
    await tick();

    expect(reportError).toHaveBeenCalledTimes(1);
    expect(frpApi.createTunnel).not.toHaveBeenCalled();
  });
});
