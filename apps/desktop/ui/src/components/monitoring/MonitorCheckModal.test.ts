// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-linux-base-v2 T20 (R-0423): an OOM kill is in one report only, so
// picking system_state in the check form suggests one fail in a row (like the
// built-in template); the field stays editable.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorCheck } from '$lib/api/types';

const mocks = vi.hoisted(() => ({
  createCheck: vi.fn().mockResolvedValue({}),
  fetchStatus: vi.fn().mockResolvedValue([]),
  rebaseline: vi.fn().mockResolvedValue({}),
  confirmDialog: vi.fn().mockResolvedValue(true),
}));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: {
    createCheck: mocks.createCheck,
    fetchStatus: mocks.fetchStatus,
    rebaseline: mocks.rebaseline,
  },
}));
vi.mock('../ui/ConfirmDialog.svelte', () => ({ confirmDialog: mocks.confirmDialog }));
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

// monitoring-linux-base-v2 T28: leaving system_state with the suggested 1
// untouched brings back the value from before the pick, not a fixed 3; the form
// forgets it when it opens again.
describe('MonitorCheckModal fails from before system_state (T28)', () => {
  const FAILS = 'Fehlversuche bis Alarm';

  it('goes back to the value from before the pick', async () => {
    const { container } = await mount();
    await fireEvent.input(field(container, FAILS), { target: { value: '5' } });
    await pickType(container, 'system_state');
    expect(field(container, FAILS).value).toBe('1');

    await pickType(container, 'ping');
    expect(field(container, FAILS).value).toBe('5');
  });

  it('forgets the value from before when the form opens again', async () => {
    const props = {
      open: true,
      target: null,
      serverId: 'srv-1',
      onClose: vi.fn(),
      onSaved: vi.fn(),
    };
    const { container, rerender } = await mount();
    await fireEvent.input(field(container, FAILS), { target: { value: '5' } });
    await pickType(container, 'system_state');

    const stored: MonitorCheck = {
      id: 'm1',
      name: 'System',
      serverId: 'srv-1',
      checkType: 'system_state',
      interval: '5m',
      severity: 'warning',
      consecutiveFails: 1,
      enabled: true,
      config: {},
    };
    await rerender({ ...props, open: false });
    await rerender({ ...props, target: stored });
    await tick();
    expect(field(container, FAILS).value).toBe('1');

    await pickType(container, 'ping');
    expect(field(container, FAILS).value).toBe('3');
  });
});

// R-1224 T11: a central check — the monitoring service probes a public endpoint
// itself; its partner is one of the server's agent probes, and a central dns
// check without expected addresses can learn its baseline again.
describe('MonitorCheckModal central (R-1224)', () => {
  function stored(config: MonitorCheck['config']): MonitorCheck {
    return {
      id: 'c1',
      name: 'DNS',
      serverId: 'srv-1',
      checkType: 'central',
      interval: '15m',
      severity: 'warning',
      enabled: true,
      config,
    };
  }

  async function mountStored(target: MonitorCheck, onSaved = vi.fn()) {
    const r = render(MonitorCheckModal, {
      props: { open: true, target, serverId: 'srv-1', onClose: vi.fn(), onSaved },
    });
    await tick();
    return r;
  }

  function options(el: HTMLInputElement | HTMLSelectElement): string[] {
    return Array.from((el as HTMLSelectElement).options).map((o) => o.value);
  }

  it('creates a central check with the trimmed host and the interval of its sensor', async () => {
    const { container, getByText } = await mount();
    await fireEvent.input(field(container, 'Name'), { target: { value: 'Web' } });
    await pickType(container, 'central');
    expect(field(container, 'Intervall').value).toBe('1h');
    expect(options(field(container, 'Intervall'))).toEqual([
      '15m',
      '30m',
      '1h',
      '6h',
      '12h',
      '24h',
    ]);

    await fireEvent.change(field(container, 'Fühler'), { target: { value: 'rdap' } });
    await tick();
    expect(options(field(container, 'Intervall'))).toEqual(['24h']);
    expect(field(container, 'Intervall').value).toBe('24h');

    await fireEvent.change(field(container, 'Fühler'), { target: { value: 'tls' } });
    await tick();
    await fireEvent.input(field(container, 'Host'), { target: { value: ' web.example ' } });
    await fireEvent.click(getByText('Speichern'));

    await waitFor(() => expect(mocks.createCheck).toHaveBeenCalledTimes(1));
    expect(mocks.createCheck.mock.calls[0][1]).toMatchObject({
      name: 'Web',
      check_type: 'central',
      interval: '1h',
      config: { sensor: 'tls', host: 'web.example', port: 443 },
    });
  });

  it('loads the checks only for a central check and offers those of its server', async () => {
    mocks.fetchStatus.mockResolvedValueOnce([
      { ...stored({ sensor: 'tls' }), id: 'p1', name: 'own', checkType: 'probe' },
      {
        ...stored({ sensor: 'tls' }),
        id: 'p2',
        name: 'other',
        checkType: 'probe',
        serverId: 'srv-2',
      },
    ]);
    const { container } = await mount();
    await pickType(container, 'ping');
    expect(mocks.fetchStatus).not.toHaveBeenCalled();

    await pickType(container, 'central');
    await waitFor(() => expect(options(field(container, 'Agent-Partner'))).toEqual(['', 'p1']));
    await pickType(container, 'ping');
    await pickType(container, 'central');
    expect(mocks.fetchStatus).toHaveBeenCalledTimes(1);
  });

  it('ignores a late answer from an earlier opening', async () => {
    let answerFirst: (all: MonitorCheck[]) => void = () => {};
    mocks.fetchStatus
      .mockReturnValueOnce(new Promise<MonitorCheck[]>((resolve) => (answerFirst = resolve)))
      .mockResolvedValueOnce([
        {
          ...stored({ sensor: 'tls' }),
          id: 'new',
          name: 'new',
          checkType: 'probe',
          serverId: 'srv-2',
        },
      ]);
    const first = stored({ sensor: 'tls' });
    const second = { ...first, id: 'c2', serverId: 'srv-2' };
    const props = { onClose: vi.fn(), onSaved: vi.fn(), serverId: 'srv-1' };
    const { container, rerender } = render(MonitorCheckModal, {
      props: { ...props, open: true, target: first },
    });
    await tick();
    await rerender({ ...props, open: false, target: first });
    await rerender({ ...props, open: true, target: second });
    await waitFor(() => expect(options(field(container, 'Agent-Partner'))).toEqual(['', 'new']));

    answerFirst([{ ...stored({ sensor: 'tls' }), id: 'old', name: 'old', checkType: 'probe' }]);
    await tick();
    await tick();
    expect(options(field(container, 'Agent-Partner'))).toEqual(['', 'new']);
  });

  it('learns the baseline again after the confirmation', async () => {
    const onSaved = vi.fn();
    const { getByText } = await mountStored(
      stored({ sensor: 'dns', host: 'example.org' }),
      onSaved,
    );
    await fireEvent.click(getByText('Basislinie neu lernen'));

    await waitFor(() => expect(mocks.rebaseline).toHaveBeenCalledTimes(1));
    expect(mocks.confirmDialog).toHaveBeenCalledTimes(1);
    expect(mocks.rebaseline.mock.calls[0][1]).toBe('c1');
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('keeps the baseline when the confirmation is declined', async () => {
    mocks.confirmDialog.mockResolvedValueOnce(false);
    const onSaved = vi.fn();
    const { getByText } = await mountStored(
      stored({ sensor: 'dns', host: 'example.org' }),
      onSaved,
    );
    await fireEvent.click(getByText('Basislinie neu lernen'));

    await waitFor(() => expect(mocks.confirmDialog).toHaveBeenCalledTimes(1));
    await tick();
    expect(mocks.rebaseline).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('offers no relearning where no baseline is learned', async () => {
    for (const config of [
      { sensor: 'dns', host: 'example.org', params: { expected: ['192.0.2.1'] } },
      { sensor: 'tls', host: 'example.org', port: 443 },
    ]) {
      const { queryByText } = await mountStored(stored(config));
      expect(queryByText('Basislinie neu lernen')).toBeNull();
      cleanup();
    }
  });
});
