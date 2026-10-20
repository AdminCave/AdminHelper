// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-alert-quality T15 (R-0424): the check editor carries consecutive_oks,
// the ok results in a row before a reported problem is cleared. The field shows the
// check's value (2 for a new check), and what the user enters is what gets saved.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorCheck } from '$lib/api/types';

const mocks = vi.hoisted(() => ({
  createCheck: vi.fn().mockResolvedValue({}),
  updateCheck: vi.fn().mockResolvedValue({}),
}));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { createCheck: mocks.createCheck, updateCheck: mocks.updateCheck },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { session: writable({ session: {}, settings: {} }) };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import { setLanguage } from '$lib/i18n';
import MonitorCheckModal from './MonitorCheckModal.svelte';

const OKS = 'OKs bis Entwarnung';

beforeEach(() => {
  setLanguage('de');
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function field(container: HTMLElement, label: string): HTMLInputElement {
  const match = Array.from(container.querySelectorAll('label.field')).find(
    (f) => f.querySelector('.field-label')?.textContent?.trim() === label,
  );
  if (!match) throw new Error(`no field labelled ${label}`);
  return match.querySelector('input') as HTMLInputElement;
}

function existing(over: Partial<MonitorCheck> = {}): MonitorCheck {
  return {
    id: 'chk-1',
    serverId: 'srv-1',
    name: 'Ping',
    checkType: 'ping',
    interval: '1m',
    severity: 'warning',
    consecutiveFails: 3,
    consecutiveOks: 4,
    enabled: true,
    config: { target: 'host.example' },
    ...over,
  };
}

async function mount(target: MonitorCheck | null) {
  const r = render(MonitorCheckModal, {
    props: { open: true, target, serverId: 'srv-1', onClose: vi.fn(), onSaved: vi.fn() },
  });
  await tick();
  return r;
}

describe('MonitorCheckModal consecutive_oks (monitoring-alert-quality T15)', () => {
  it('starts a new check at 2, within 1 to 100', async () => {
    const { container } = await mount(null);
    const input = field(container, OKS);
    expect(input.type).toBe('number');
    expect(input.value).toBe('2');
    expect(input.min).toBe('1');
    expect(input.max).toBe('100');
  });

  it('shows the value of the check being edited', async () => {
    const { container } = await mount(existing());
    expect(field(container, OKS).value).toBe('4');
  });

  it('saves the entered value with a new check', async () => {
    const { container, getByText } = await mount(null);
    await fireEvent.input(field(container, 'Name'), { target: { value: 'Ping' } });
    await fireEvent.input(field(container, OKS), { target: { value: '5' } });
    await fireEvent.click(getByText('Speichern'));

    await waitFor(() => expect(mocks.createCheck).toHaveBeenCalledTimes(1));
    expect(mocks.createCheck.mock.calls[0][1]).toMatchObject({
      name: 'Ping',
      server_id: 'srv-1',
      consecutive_fails: 3,
      consecutive_oks: 5,
    });
  });

  it('saves the entered value with an edited check', async () => {
    const { container, getByText } = await mount(existing());
    await fireEvent.input(field(container, OKS), { target: { value: '1' } });
    await fireEvent.click(getByText('Speichern'));

    await waitFor(() => expect(mocks.updateCheck).toHaveBeenCalledTimes(1));
    expect(mocks.updateCheck.mock.calls[0][1]).toBe('chk-1');
    expect(mocks.updateCheck.mock.calls[0][2]).toMatchObject({ consecutive_oks: 1 });
    expect(mocks.createCheck).not.toHaveBeenCalled();
  });

  it('labels the field in English too', async () => {
    setLanguage('en');
    const { container } = await mount(existing());
    expect(field(container, 'Consecutive OKs before recovery').value).toBe('4');
  });
});
