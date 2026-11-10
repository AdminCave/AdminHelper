// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T5 (R-1225): one module instance as a card on the server page
// (concept §3.14). Pins the title with its instance, the catalog's figures read from
// the check they name (a figure without its check left out), the closed line of a
// green card, a problem card's line in plain text (the sensor's status before the
// raw message), silent checks marked one by one, the muted note, and a module the
// catalog does not know (any more).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// ModuleCard -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init
// calls matchMedia (missing in jsdom). The card's rows never draw a chart
// (showChart={false}) — stub the lib away, same as SecServices.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { cleanup, fireEvent, render, within } from '@testing-library/svelte';
import type {
  MonitorCatalogModule,
  MonitorCheck,
  MonitorProbeDetails,
  MonStatus,
} from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import ModuleCard from './ModuleCard.svelte';

function probe(over: Partial<MonitorProbeDetails> = {}): MonitorProbeDetails {
  return {
    ts: 1,
    status: 'ok',
    error: null,
    measured_ts: 1,
    values: {},
    baseline: null,
    problems: [],
    ...over,
  };
}

function check(
  id: string,
  key: string,
  status: MonStatus,
  details: MonitorProbeDetails,
  over: Partial<MonitorCheck> = {},
): MonitorCheck {
  return {
    id,
    serverId: 'srv-1',
    name: key === 'status' ? 'Status' : 'Zertifikat',
    checkType: 'probe',
    interval: '1m',
    severity: 'critical',
    enabled: true,
    moduleId: 'nginx',
    moduleInstance: 'proxy',
    moduleCheckKey: key,
    state: { status, message: 'raw checker text', details },
    ...over,
  } as MonitorCheck;
}

const MODULE: MonitorCatalogModule = {
  id: 'nginx',
  name: 'Nginx',
  version: 1,
  description: '',
  instance: 'config',
  checks: [],
  card: [
    { checkKey: 'status', field: 'active_connections', label: 'Verbindungen' },
    { checkKey: 'status', field: 'version', label: 'Version' },
    { checkKey: 'tls', field: 'days_left', label: 'Zertifikat' },
  ],
};

const green = () => check('c1', 'status', 'ok', probe({ values: { active_connections: 12 } }));

function toggle(getByRole: (role: string, opts: object) => HTMLElement): HTMLElement {
  return getByRole('button', { name: /Nginx|nginx/ });
}

beforeEach(() => setLanguage('de'));
afterEach(() => cleanup());

describe('ModuleCard', () => {
  it('names the instance beside the module, but not twice', () => {
    const { getByText, unmount } = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [green()],
    });
    expect(getByText('Nginx · proxy')).toBeTruthy();
    unmount();

    const single = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'nginx',
      checks: [green()],
    });
    expect(single.getByText('Nginx')).toBeTruthy();
    expect(single.queryByText(/·/)).toBeNull();
  });

  it('closes a green card to the known figures and lists them when opened', async () => {
    const { getByRole, getByText, container } = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [green()],
    });
    const button = toggle(getByRole);
    expect(button.getAttribute('aria-expanded')).toBe('false');
    // The version has no value yet and the instance has no `tls` check.
    expect(getByText('Verbindungen 12')).toBeTruthy();

    await fireEvent.click(button);
    const figures = container.querySelector('dl');
    expect(figures).toBeTruthy();
    const terms = [...figures!.querySelectorAll('dt')].map((dt) => dt.textContent);
    expect(terms).toEqual(['Verbindungen', 'Version']);
    expect(within(figures!).getByText('—')).toBeTruthy();
    expect(getByText('Status')).toBeTruthy();
  });

  it('opens a problem card and says the sensor status in plain text', () => {
    const broken = check('c1', 'status', 'critical', probe({ status: 'no_credential' }));
    const { getByRole, getAllByText, queryByText } = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [broken],
    });
    expect(toggle(getByRole).getAttribute('aria-expanded')).toBe('true');
    // Once as the card's line, once on the check's row.
    expect(getAllByText('Zugangsdaten fehlen')).toHaveLength(2);
    expect(getByRole('img', { name: 'Kritisch' })).toBeTruthy();
    expect(queryByText('raw checker text')).toBeNull();
  });

  it('names the worst check of several and falls back to its broken rule', () => {
    const { getByText } = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [
        green(),
        check('c2', 'tls', 'warning', probe({ problems: ['days_left < 14', 'other'] })),
      ],
    });
    expect(getByText('Zertifikat: days_left < 14')).toBeTruthy();
  });

  it('falls back to the raw message, then to the counts', () => {
    const plain = check('c1', 'status', 'critical', probe(), { name: 'Status' });
    const first = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [plain],
    });
    expect(first.getByText('raw checker text')).toBeTruthy();
    first.unmount();

    const bare = check('c1', 'status', 'unknown', probe(), { state: { status: 'unknown' } });
    const { getByText } = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [bare],
    });
    expect(getByText('1 Unknown')).toBeTruthy();
  });

  it('marks a silent check and shows the muted note', () => {
    const { getByText } = render(ModuleCard, {
      module: MODULE,
      moduleId: 'nginx',
      instance: 'proxy',
      checks: [
        check('c1', 'status', 'warning', probe({ problems: ['slow'] }), {
          silent: true,
          mutedReason: 'maintenance window',
        }),
      ],
    });
    expect(getByText('still')).toBeTruthy();
    expect(getByText('Wartungsfenster — Meldungen unterdrückt')).toBeTruthy();
  });

  it('shows a module the catalog does not know by its id and its check count', async () => {
    const { getByRole, getByText, container } = render(ModuleCard, {
      module: null,
      moduleId: 'nginx',
      instance: 'nginx',
      checks: [green(), check('c2', 'tls', 'ok', probe())],
    });
    expect(getByText('2 Checks')).toBeTruthy();
    await fireEvent.click(toggle(getByRole));
    expect(container.querySelector('dl')).toBeNull();
    expect(getByText('Status')).toBeTruthy();
    expect(getByText('Zertifikat')).toBeTruthy();
  });
});
