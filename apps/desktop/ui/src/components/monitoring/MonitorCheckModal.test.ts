// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-linux-base-v2 T20 (R-0423): an OOM kill is in one report only, so
// picking system_state in the check form suggests one fail in a row (like the
// built-in template); the field stays editable.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

const mocks = vi.hoisted(() => ({
  createCheck: vi.fn().mockResolvedValue({}),
}));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { createCheck: mocks.createCheck },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { session: writable({ session: {}, settings: {} }) };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import { setLanguage } from '$lib/i18n';
import MonitorCheckModal from './MonitorCheckModal.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function field(container: HTMLElement, label: string): HTMLInputElement | HTMLSelectElement {
  const match = Array.from(container.querySelectorAll('label.field')).find((f) =>
    f.querySelector('.field-label')?.textContent?.includes(label),
  );
  if (!match) throw new Error(`no field labelled ${label}`);
  return match.querySelector('input, select') as HTMLInputElement | HTMLSelectElement;
}

async function mount() {
  const r = render(MonitorCheckModal, {
    props: { open: true, target: null, serverId: 'srv-1', onClose: vi.fn(), onSaved: vi.fn() },
  });
  await tick();
  return r;
}

async function pickType(container: HTMLElement, type: string): Promise<void> {
  await fireEvent.change(field(container, 'Typ'), { target: { value: type } });
  await tick();
}

describe('MonitorCheckModal system_state (R-0423)', () => {
  it('offers system_state and suggests one fail in a row for it', async () => {
    const { container } = await mount();
    const options = Array.from((field(container, 'Typ') as HTMLSelectElement).options);
    expect(options.map((o) => o.value)).toContain('system_state');
    expect(field(container, 'Fehlversuche bis Alarm').value).toBe('3');

    await pickType(container, 'system_state');
    expect(field(container, 'Fehlversuche bis Alarm').value).toBe('1');
    // The form below the type follows it: the four switches of the type.
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(4);
  });

  it('saves a value changed after the suggestion', async () => {
    const { container, getByText } = await mount();
    await fireEvent.input(field(container, 'Name'), { target: { value: 'System' } });
    await pickType(container, 'system_state');
    await fireEvent.input(field(container, 'Fehlversuche bis Alarm'), { target: { value: '2' } });
    await fireEvent.click(getByText('Speichern'));

    await waitFor(() => expect(mocks.createCheck).toHaveBeenCalledTimes(1));
    expect(mocks.createCheck.mock.calls[0][1]).toMatchObject({
      name: 'System',
      check_type: 'system_state',
      consecutive_fails: 2,
      config: {},
    });
  });

  it('goes back to 3 when the type is left with the 1 untouched, keeps a changed value', async () => {
    const { container } = await mount();
    await pickType(container, 'system_state');
    await pickType(container, 'ping');
    expect(field(container, 'Fehlversuche bis Alarm').value).toBe('3');

    await pickType(container, 'system_state');
    await fireEvent.input(field(container, 'Fehlversuche bis Alarm'), { target: { value: '2' } });
    await pickType(container, 'ping');
    expect(field(container, 'Fehlversuche bis Alarm').value).toBe('2');
  });
});
