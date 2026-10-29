// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-templates T11: a standard template the user changed does not take a
// newer shipped version by itself; the template list says "Update verfügbar", and the
// badge opens a comparison of the current and the shipped definitions per def_id with
// "Übernehmen". The list and the modal run as on the page, against the real store, so
// the reload after taking the update has to reach the list.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const h = vi.hoisted(() => ({
  session: { username: 'admin', serverUrl: 'https://srv.example' },
  fetchTemplates: vi.fn(),
  fetchBuiltinUpdate: vi.fn(),
  applyBuiltinUpdate: vi.fn(),
}));

vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return {
    currentSession: () => h.session,
    sessionStore: readable({ session: h.session, settings: {}, ready: true }),
  };
});

// Only the calls under test; anything else the list reached for would fail loudly.
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: {
    fetchTemplates: h.fetchTemplates,
    fetchBuiltinUpdate: h.fetchBuiltinUpdate,
    applyBuiltinUpdate: h.applyBuiltinUpdate,
  },
}));

import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import type { MonitoringBuiltinUpdate, MonitoringTemplateFull } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { clearStatus, status } from '$lib/stores/statusBar';
import { IpcError } from '$lib/utils/errors';
import MonitoringTemplates from './MonitoringTemplates.svelte';

const BADGE = 'Update verfügbar';
const APPLY = 'Übernehmen';

function tpl(over: Partial<MonitoringTemplateFull> = {}): MonitoringTemplateFull {
  return {
    id: 'tpl-linux',
    name: 'Linux Server',
    builtinSlug: 'linux-server',
    builtinVersion: 1,
    builtinEdited: true,
    builtinUpdateAvailable: true,
    checkDefinitions: [],
    alertDefinitions: [],
    assignments: [],
    ...over,
  };
}

// Canonical form as the server sends it: a key at its schema default is left out.
function update(over: Partial<MonitoringBuiltinUpdate> = {}): MonitoringBuiltinUpdate {
  return {
    currentVersion: 1,
    shippedVersion: 2,
    current: {
      checkDefinitions: [
        // changed: the user set 1m (default 5m); the new version disables it
        {
          def_id: 'cpu',
          name: 'CPU',
          check_type: 'agent_resources',
          interval: '1m',
          config: { cpu_warn: 80, cpu_crit: 90 },
        },
        // the same on both sides, its config only in another key order
        {
          def_id: 'zfs',
          name: 'ZFS',
          check_type: 'zfs_health',
          config: { capacity_warn: 80, capacity_crit: 90 },
        },
        // gone from the shipped version
        { def_id: 'legacy', name: 'Legacy Ping', check_type: 'ping' },
      ],
      alertDefinitions: [],
    },
    shipped: {
      checkDefinitions: [
        {
          def_id: 'cpu',
          name: 'CPU',
          check_type: 'agent_resources',
          enabled: false,
          config: { cpu_crit: 90, cpu_warn: 80 },
        },
        {
          def_id: 'zfs',
          name: 'ZFS',
          check_type: 'zfs_health',
          config: { capacity_crit: 90, capacity_warn: 80 },
        },
        // new in the shipped version
        { def_id: 'mem', name: 'Memory', check_type: 'agent_resources' },
      ],
      alertDefinitions: [],
    },
    ...over,
  };
}

setLanguage('de');
beforeEach(() => {
  h.fetchTemplates.mockReset();
  h.fetchBuiltinUpdate.mockReset();
  h.applyBuiltinUpdate.mockReset();
});
afterEach(() => {
  cleanup();
  clearStatus();
});

async function mountList(templates: MonitoringTemplateFull[]): Promise<HTMLElement> {
  h.fetchTemplates.mockResolvedValue(templates);
  const { container } = render(MonitoringTemplates);
  await waitFor(() =>
    expect(container.querySelectorAll('.mon-tpl-card')).toHaveLength(templates.length),
  );
  return container;
}

function badges(root: HTMLElement): HTMLButtonElement[] {
  return [...root.querySelectorAll<HTMLButtonElement>('button')].filter(
    (b) => b.textContent?.trim() === BADGE,
  );
}

function dialog(root: HTMLElement): HTMLElement | null {
  return root.querySelector<HTMLElement>('[role="dialog"]');
}

function applyButton(dlg: HTMLElement): HTMLButtonElement {
  const found = [...dlg.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === APPLY,
  );
  expect(found).toBeDefined();
  return found!;
}

function row(dlg: HTMLElement, defId: string): HTMLElement | null {
  return dlg.querySelector<HTMLElement>(`[data-def="${defId}"]`);
}

// Field rows of a changed definition as [label, current, shipped].
function fieldRows(el: HTMLElement): string[][] {
  return [...el.querySelectorAll<HTMLElement>('.bu-field-row')].map((r) =>
    [...r.querySelectorAll<HTMLElement>('.bu-cell')].map((c) => c.textContent?.trim() ?? ''),
  );
}

// Opens the comparison of the template behind the (only) badge.
async function openUpdate(root: HTMLElement, data = update()): Promise<HTMLElement> {
  h.fetchBuiltinUpdate.mockResolvedValue(data);
  await fireEvent.click(badges(root)[0]);
  return waitFor(() => {
    const dlg = dialog(root);
    expect(dlg).not.toBeNull();
    expect(row(dlg!, 'cpu') ?? dlg!.querySelector('.bu-none')).not.toBeNull();
    return dlg!;
  });
}

describe('MonitoringTemplates — badge "Update verfügbar" (T11)', () => {
  it('shows the badge only on a template with an update', async () => {
    const root = await mountList([
      tpl(),
      tpl({ id: 'tpl-docker', name: 'Docker', builtinUpdateAvailable: false }),
      tpl({
        id: 'tpl-own',
        name: 'Eigenes',
        builtinSlug: null,
        builtinVersion: null,
        builtinEdited: false,
        builtinUpdateAvailable: false,
      }),
    ]);
    const found = badges(root);
    expect(found).toHaveLength(1);
    expect(found[0].closest('.mon-tpl-card')?.textContent).toContain('Linux Server');
  });

  it('opens the comparison for that template', async () => {
    const root = await mountList([tpl()]);
    const dlg = await openUpdate(root);
    expect(h.fetchBuiltinUpdate).toHaveBeenCalledTimes(1);
    expect(h.fetchBuiltinUpdate).toHaveBeenCalledWith(h.session, 'tpl-linux');
    expect(dlg.textContent).toContain('Version 1 → 2');
    expect(dlg.textContent).toContain('angepasste Felder einzelner Checks bleiben erhalten');
  });
});

describe('BuiltinUpdateModal — comparison per def_id (T11)', () => {
  it('names new, removed and changed definitions, the changes with their fields', async () => {
    const root = await mountList([tpl()]);
    const dlg = await openUpdate(root);

    expect(row(dlg, 'mem')?.textContent).toContain('Memory');
    expect(row(dlg, 'mem')?.textContent).toContain('neu');
    expect(row(dlg, 'legacy')?.textContent).toContain('Legacy Ping');
    expect(row(dlg, 'legacy')?.textContent).toContain('entfernt');
    expect(row(dlg, 'cpu')?.textContent).toContain('geändert');
    // A side without the key holds the schema default: 5m, enabled.
    expect(fieldRows(row(dlg, 'cpu')!)).toEqual([
      ['Aktiviert', 'Ja', 'Nein'],
      ['Intervall', '1m', '5m'],
    ]);
    // Same keys and values, only in another order: no change.
    expect(row(dlg, 'zfs')).toBeNull();
  });

  it('shows changed alert definitions too, since taking the update replaces them', async () => {
    const root = await mountList([tpl()]);
    const data = update();
    data.current.alertDefinitions = [
      { def_id: 'ops-mail', name: 'Ops Mail', channel: 'email', cooldown_minutes: 10 },
    ];
    const dlg = await openUpdate(root, data);
    expect(row(dlg, 'ops-mail')?.textContent).toContain('Ops Mail');
    expect(row(dlg, 'ops-mail')?.textContent).toContain('entfernt');
  });

  it('says so when the definitions do not differ', async () => {
    const root = await mountList([tpl()]);
    const same = update().shipped;
    const dlg = await openUpdate(root, update({ current: same }));
    expect(dlg.querySelector('.bu-none')?.textContent).toContain('unterscheiden sich nicht');
    expect(applyButton(dlg).disabled).toBe(false);
  });

  it('offers no apply before the comparison is there', async () => {
    const root = await mountList([tpl()]);
    h.fetchBuiltinUpdate.mockReturnValue(new Promise(() => {}));
    await fireEvent.click(badges(root)[0]);
    const dlg = await waitFor(() => {
      const found = dialog(root);
      expect(found).not.toBeNull();
      return found!;
    });
    expect(applyButton(dlg).disabled).toBe(true);
  });

  it('a failed load closes the modal and reports the error', async () => {
    const root = await mountList([tpl()]);
    h.fetchBuiltinUpdate.mockRejectedValue('HTTP 404: {"detail":"Standard template not found"}');
    await fireEvent.click(badges(root)[0]);
    await waitFor(() =>
      expect(get(status)).toMatchObject({
        isError: true,
        text: 'HTTP 404: {"detail":"Standard template not found"}',
      }),
    );
    await waitFor(() => expect(dialog(root)).toBeNull());
  });
});

describe('BuiltinUpdateModal — taking the update (T11)', () => {
  it('takes it once on a double click, reloads the list and closes', async () => {
    const root = await mountList([tpl()]);
    const dlg = await openUpdate(root);
    let answer!: (v: MonitoringTemplateFull) => void;
    h.applyBuiltinUpdate.mockReturnValue(new Promise((r) => (answer = r)));
    h.fetchTemplates.mockResolvedValue([
      tpl({ builtinVersion: 2, builtinEdited: false, builtinUpdateAvailable: false }),
    ]);

    const btn = applyButton(dlg);
    await fireEvent.click(btn);
    await fireEvent.click(btn);
    expect(h.applyBuiltinUpdate).toHaveBeenCalledTimes(1);
    expect(h.applyBuiltinUpdate).toHaveBeenCalledWith(h.session, 'tpl-linux');
    expect(btn.disabled).toBe(true);

    answer(tpl({ builtinVersion: 2, builtinUpdateAvailable: false }));
    await waitFor(() => expect(dialog(root)).toBeNull());
    expect(h.fetchTemplates).toHaveBeenCalledTimes(2);
    expect(badges(root)).toHaveLength(0);
    expect(get(status)).toMatchObject({ isError: false, text: 'Update übernommen' });
    expect(h.applyBuiltinUpdate).toHaveBeenCalledTimes(1);
  });

  it('a 409 (taken meanwhile) explains itself and reloads the list', async () => {
    const root = await mountList([tpl()]);
    const dlg = await openUpdate(root);
    h.applyBuiltinUpdate.mockRejectedValue(new IpcError('No update available', 'ERR_HTTP', 409));
    h.fetchTemplates.mockResolvedValue([
      tpl({ builtinVersion: 2, builtinEdited: false, builtinUpdateAvailable: false }),
    ]);

    await fireEvent.click(applyButton(dlg));

    await waitFor(() => expect(dialog(root)).toBeNull());
    expect(get(status)?.text).toBe(
      'Kein Update mehr verfügbar — das Template ist bereits auf dem neuesten Stand',
    );
    expect(get(status)?.text).not.toContain('HTTP');
    expect(h.fetchTemplates).toHaveBeenCalledTimes(2);
    expect(badges(root)).toHaveLength(0);
  });

  it('a text that only starts like a 409 is reported, the modal stays', async () => {
    const root = await mountList([tpl()]);
    const dlg = await openUpdate(root);
    h.applyBuiltinUpdate.mockRejectedValue(new Error('HTTP 409: No update available'));

    await fireEvent.click(applyButton(dlg));

    await waitFor(() =>
      expect(get(status)).toMatchObject({
        isError: true,
        text: 'HTTP 409: No update available',
      }),
    );
    expect(dialog(root)).not.toBeNull();
    expect(h.fetchTemplates).toHaveBeenCalledTimes(1);
  });

  it('another failure keeps the modal open for a retry and reports the error', async () => {
    const root = await mountList([tpl()]);
    const dlg = await openUpdate(root);
    h.applyBuiltinUpdate.mockRejectedValue('HTTP 502: Bad Gateway');

    await fireEvent.click(applyButton(dlg));

    await waitFor(() =>
      expect(get(status)).toMatchObject({ isError: true, text: 'HTTP 502: Bad Gateway' }),
    );
    expect(dialog(root)).not.toBeNull();
    await waitFor(() => expect(applyButton(dlg).disabled).toBe(false));
    expect(h.fetchTemplates).toHaveBeenCalledTimes(1);
  });
});

// monitoring-alert-quality T16 (R-0424): consecutive_oks is a check definition field
// with the schema default 2, which the server leaves out of a side at that default.
describe('BuiltinUpdateModal — consecutive_oks (monitoring-alert-quality T16)', () => {
  it('names a changed consecutive_oks by its label, a side without the key as 2', async () => {
    const root = await mountList([tpl()]);
    const data = update({
      current: {
        checkDefinitions: [
          {
            def_id: 'cpu',
            name: 'CPU',
            check_type: 'agent_resources',
            consecutive_fails: 5,
            consecutive_oks: 4,
          },
          // the old version of a check whose new one recovers after one ok
          { def_id: 'disk', name: 'Disk Forecast', check_type: 'disk_forecast' },
        ],
        alertDefinitions: [],
      },
      shipped: {
        checkDefinitions: [
          { def_id: 'cpu', name: 'CPU', check_type: 'agent_resources' },
          {
            def_id: 'disk',
            name: 'Disk Forecast',
            check_type: 'disk_forecast',
            consecutive_oks: 1,
          },
        ],
        alertDefinitions: [],
      },
    });
    const dlg = await openUpdate(root, data);

    expect(fieldRows(row(dlg, 'cpu')!)).toEqual([
      ['Fehlversuche bis Alarm', '5', '3'],
      ['OKs bis Entwarnung', '4', '2'],
    ]);
    expect(fieldRows(row(dlg, 'disk')!)).toEqual([['OKs bis Entwarnung', '2', '1']]);
  });
});
