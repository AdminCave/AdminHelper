// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T15: the server-create dialog gains an opt-in monitoring-template dropdown.
// Create without a selection passes null (no assign); with a selection the
// template id travels as saveServer's third argument; editing shows no dropdown.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

const mocks = vi.hoisted(() => ({
  saveServer: vi.fn().mockResolvedValue(true),
  deleteServer: vi.fn().mockResolvedValue(true),
  closeServerEditor: vi.fn(),
  fetchTemplates: vi.fn().mockResolvedValue([
    { id: 'tpl-custom', name: 'Custom' },
    { id: 'tpl-linux', name: 'Linux Server — Standard', builtinSlug: 'linux-base' },
  ]),
  editorState: { open: true, target: null as unknown },
}));

vi.mock('$lib/stores/infra', async () => {
  const { writable } = await import('svelte/store');
  return {
    serverEditor: writable(mocks.editorState),
    closeServerEditor: mocks.closeServerEditor,
    saveServer: mocks.saveServer,
    deleteServer: mocks.deleteServer,
  };
});
vi.mock('$lib/stores/session', () => ({
  currentSession: () => ({ session: {}, settings: {} }),
}));
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { fetchTemplates: mocks.fetchTemplates },
}));
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import { setLanguage } from '$lib/i18n';
import ServerModal from './ServerModal.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function mountAndFill() {
  const utils = render(ServerModal);
  await tick();
  const name = utils.container.querySelector('input[name="name"]') as HTMLInputElement;
  const hostname = utils.container.querySelector('input[name="hostname"]') as HTMLInputElement;
  await fireEvent.input(name, { target: { value: 'web01' } });
  await fireEvent.input(hostname, { target: { value: 'web01.example' } });
  return utils;
}

describe('ServerModal monitoring-template opt-in', () => {
  it('creates without a selection and passes null as template', async () => {
    const { getByText } = await mountAndFill();
    await fireEvent.click(getByText('Speichern'));
    await waitFor(() =>
      expect(mocks.saveServer).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'web01', hostname: 'web01.example' }),
        null,
        null,
      ),
    );
  });

  it('passes the selected template id and lists built-ins first', async () => {
    const { container, getByText } = await mountAndFill();
    await waitFor(() => {
      const select = container.querySelector('.field select') as HTMLSelectElement;
      expect(select.options.length).toBe(3);
    });
    const select = container.querySelector('.field select') as HTMLSelectElement;
    // Built-in sorted before the custom template, empty option first.
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['', 'tpl-linux', 'tpl-custom']);
    await fireEvent.change(select, { target: { value: 'tpl-linux' } });
    await fireEvent.click(getByText('Speichern'));
    await waitFor(() =>
      expect(mocks.saveServer).toHaveBeenCalledWith(expect.anything(), null, 'tpl-linux'),
    );
  });

  it('editing an existing server shows no template dropdown', async () => {
    mocks.editorState.target = { id: 'srv-1', name: 'web01', hostname: 'web01.example' };
    const { container } = render(ServerModal);
    await tick();
    expect(container.querySelector('.field select')).toBeNull();
    mocks.editorState.target = null;
  });
});
