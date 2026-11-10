// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The server dashboard head (R-1064): worst-state dot, count pills, the maintenance and
// "+ Check" actions. arch-monitoring-ui T5 (R-1225, concept §3.14): the problem count,
// "scan now" with the last scan, the cards (problems first and open, quiet ones closed
// in a fixed order), one module card per instance with its catalog module, the
// "Neu gefunden" card with adopt and its error states, what adopting left out, and the
// muted note. T6: the cost card closes the page, for a real server only.
// The sections, history, module card, cost card and modals are stubbed.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';

const h = vi.hoisted(() => ({
  stub: vi.fn(),
  maint: vi.fn(),
  moduleCard: vi.fn(),
  costs: vi.fn(),
  openCheckEditor: vi.fn(),
  requestScan: vi.fn(() => Promise.resolve(true)),
  adoptFinding: vi.fn((): Promise<unknown> => Promise.resolve(null)),
  adoptAllFindings: vi.fn((): Promise<unknown> => Promise.resolve(null)),
  dismissFinding: vi.fn(() => Promise.resolve(true)),
}));

const BASE = [
  { id: 'c1', serverId: 'srv-1', name: 'a', checkType: 'ping', state: { status: 'critical' } },
  { id: 'c2', serverId: 'srv-1', name: 'b', checkType: 'ping', state: { status: 'ok' } },
  { id: 'c3', serverId: 'srv-1', name: 'c', checkType: 'ping', state: { status: 'ok' } },
  { id: 'c4', serverId: 'srv-1', name: 'd', checkType: 'ping', state: { status: 'pending' } },
  { id: 'c5', serverId: null, name: 'e', checkType: 'ping', state: { status: 'ok' } },
];

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoringChecks: writable([]),
    monitoringServers: writable([{ id: 'srv-1', name: 'web01', hostname: 'web01.example' }]),
    selectedServerId: writable<string | null>(null),
    checkEditor: writable({ open: false, target: null, serverId: '' }),
    monitoringCatalog: writable(null),
    monitoringDiscovery: writable({}),
    monitoringFindings: writable([]),
    monitoringFindingsError: writable(null),
    openCheckEditor: h.openCheckEditor,
    closeCheckEditor: vi.fn(),
    loadMonitoring: vi.fn(),
    loadMaintenanceWindows: vi.fn(),
    requestScan: h.requestScan,
    adoptFinding: h.adoptFinding,
    adoptAllFindings: h.adoptAllFindings,
    dismissFinding: h.dismissFinding,
  };
});
vi.mock('./MaintenanceModal.svelte', () => ({ default: h.maint }));
vi.mock('./MonitorCheckModal.svelte', () => ({ default: h.stub }));
vi.mock('./MonHeartbeatBar.svelte', () => ({ default: h.stub }));
vi.mock('./HistoryPanel.svelte', () => ({ default: h.stub }));
vi.mock('./card/ModuleCard.svelte', () => ({ default: h.moduleCard }));
vi.mock('./card/MonCosts.svelte', () => ({ default: h.costs }));
vi.mock('./section/SecLive.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecNetwork.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecHeartbeat.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecServices.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecSystem.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecDocker.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecBackups.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecZfs.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecSmart.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecForecast.svelte', () => ({ default: h.stub }));

import type {
  MonitorCatalog,
  MonitorCheck,
  MonitorDiscovery,
  MonitorFinding,
} from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import * as store from '$lib/stores/monitoring';
import MonServerDashboard from './MonServerDashboard.svelte';

const checks = store.monitoringChecks as unknown as Writable<unknown[]>;
const selectedServerId = store.selectedServerId as unknown as Writable<string | null>;
const catalog = store.monitoringCatalog as unknown as Writable<MonitorCatalog | null>;
const discovery = store.monitoringDiscovery as unknown as Writable<
  Record<string, MonitorDiscovery>
>;
const findings = store.monitoringFindings as unknown as Writable<MonitorFinding[]>;
const findingsError = store.monitoringFindingsError as unknown as Writable<string | null>;

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  catalog.set(null);
  discovery.set({});
  findings.set([]);
  findingsError.set(null);
});

async function mount(selected: string, list: unknown[] = BASE): Promise<HTMLElement> {
  checks.set(list);
  selectedServerId.set(selected);
  const { container } = render(MonServerDashboard);
  await tick();
  return container;
}

function check(id: string, checkType: string, status: string, over: object = {}) {
  return { id, serverId: 'srv-1', name: id, checkType, state: { status }, ...over };
}

function finding(id: string, serverId = 'srv-1'): MonitorFinding {
  return {
    id,
    serverId,
    moduleId: 'nginx',
    moduleName: 'Nginx',
    instanceKey: `nginx@${id}`,
    kind: 'new',
    status: 'open',
    summary: {},
    catalogVersion: '1',
    firstSeen: null,
    lastSeen: null,
    decidedAt: null,
    silentChecks: [],
    droppedChecks: [],
  };
}

function scan(over: Partial<MonitorDiscovery> = {}): MonitorDiscovery {
  return {
    serverId: 'srv-1',
    scannedAt: null,
    nextScanAt: null,
    scanRequestedAt: null,
    inventory: {},
    credentials: [],
    ...over,
  };
}

// The lines of the "not everything adopted" note; null without the note.
function noteLines(el: HTMLElement): string[] | null {
  const note = el.querySelector('[role="status"]');
  return note ? Array.from(note.querySelectorAll('li')).map((li) => li.textContent) : null;
}

// Title and open state of each card, top to bottom.
function cardsOf(el: HTMLElement): Array<[string, string | null]> {
  return Array.from(el.querySelectorAll('.mon-card')).map((card) => [
    card.querySelector('.mon-card-title')?.textContent ?? '',
    card.querySelector('.mon-card-toggle')?.getAttribute('aria-expanded') ?? null,
  ]);
}

describe('MonServerDashboard head (R-1064)', () => {
  it('shows the worst state as a labelled dot and the counts as pills', async () => {
    const el = await mount('srv-1');
    expect(el.querySelector('.mon-dashboard-name')?.textContent).toBe('web01');
    expect(el.querySelector('.mon-dashboard-host')?.textContent).toBe('web01.example');
    const dot = el.querySelector('.mon-dashboard-title [role="img"]');
    expect(dot?.getAttribute('aria-label')).toBe('Kritisch');
    const pills = Array.from(el.querySelectorAll('.mon-dashboard-stats .pill')).map((p) => [
      p.textContent?.trim(),
      p.className.match(/pill-(\w+)/)?.[1],
    ]);
    expect(pills).toEqual([
      ['1 Kritisch', 'crit'],
      ['2 OK', 'ok'],
      ['1 Pending', 'muted'],
    ]);
    expect(el.querySelector('.mon-pill')).toBeNull();
  });

  it('"+ Check" opens the check editor for the selected server', async () => {
    const el = await mount('srv-1');
    await fireEvent.click(el.querySelector('[data-action="check-new"]') as HTMLElement);
    expect(h.openCheckEditor).toHaveBeenCalledWith(null, 'srv-1');
  });

  it('the maintenance button opens a new window for the selected server', async () => {
    const el = await mount('srv-1');
    const props = h.maint.mock.calls.at(-1)?.[1] as {
      open: boolean;
      editing: unknown;
      serverId: string;
    };
    expect(props.open).toBe(false);
    await fireEvent.click(el.querySelector('[data-action="maintenance-new"]') as HTMLElement);
    expect(props.open).toBe(true);
    expect(props.editing).toBeNull();
    expect(props.serverId).toBe('srv-1');
  });

  it('offers no actions and no findings for the checks without a server', async () => {
    findings.set([finding('f1')]);
    const el = await mount('__none');
    expect(el.querySelector('[data-action="check-new"]')).toBeNull();
    expect(el.querySelector('[data-action="maintenance-new"]')).toBeNull();
    expect(el.querySelector('[data-action="scan-now"]')).toBeNull();
    expect(h.maint).not.toHaveBeenCalled();
    expect(cardsOf(el)).toEqual([['System', 'false']]);
  });

  it('counts the problems in plain text', async () => {
    let el = await mount('srv-1');
    expect(el.querySelector('.mon-dashboard-problems')?.textContent).toBe('1 Problem');
    cleanup();

    el = await mount('srv-1', [check('a', 'ping', 'ok')]);
    expect(el.querySelector('.mon-dashboard-problems')?.textContent).toBe('Alles in Ordnung');
    cleanup();

    el = await mount('srv-1', [check('a', 'ping', 'warning'), check('b', 'tcp', 'unknown')]);
    expect(el.querySelector('.mon-dashboard-problems')?.textContent).toBe('2 Probleme');
  });
});

describe('MonServerDashboard cards (R-1225)', () => {
  it('puts problem cards first and open, quiet ones closed in the fixed order', async () => {
    const el = await mount('srv-1', [
      check('ping', 'ping', 'ok'),
      check('svc', 'service_process', 'ok'),
      check('dock', 'docker_health', 'warning'),
      check('bak', 'proxmox_backup', 'critical'),
    ]);
    expect(cardsOf(el)).toEqual([
      ['Backups', 'true'],
      ['Container', 'true'],
      ['System', 'false'],
      ['Dienste', 'false'],
    ]);
  });

  it('builds one module card per instance with its catalog module', async () => {
    const nginx = {
      id: 'nginx',
      name: 'Nginx',
      version: 1,
      description: '',
      instance: 'config',
      checks: [],
      card: [],
    };
    catalog.set({ version: '1', modules: [nginx] });
    await mount('srv-1', [
      check('m1', 'probe', 'ok', { moduleId: 'nginx', moduleInstance: 'b' }),
      check('m2', 'probe', 'ok', { moduleId: 'nginx', moduleInstance: 'a' }),
      check('m3', 'http', 'ok', { moduleId: 'nginx', moduleInstance: 'a' }),
      check('loose', 'probe', 'ok'),
      check('ping', 'ping', 'ok'),
    ]);
    const cards = h.moduleCard.mock.calls.map((call) => {
      const p = call[1] as {
        module: unknown;
        moduleId: string;
        instance: string;
        checks: MonitorCheck[];
      };
      return [p.module, p.moduleId, p.instance, p.checks.map((c) => c.id)];
    });
    expect(cards).toEqual([
      [nginx, 'nginx', 'a', ['m2', 'm3']],
      [nginx, 'nginx', 'b', ['m1']],
      [null, 'probe', '', ['loose']],
    ]);
  });

  it('shows what was newly found as an open card between problems and the rest', async () => {
    findings.set([finding('f1'), finding('f2', 'srv-2')]);
    const el = await mount('srv-1', [
      check('ping', 'ping', 'critical'),
      check('svc', 'service_process', 'ok'),
    ]);
    expect(cardsOf(el)).toEqual([
      ['System', 'true'],
      ['Neu gefunden (1)', 'true'],
      ['Dienste', 'false'],
    ]);
    await fireEvent.click(screen.getByRole('button', { name: 'Übernehmen' }));
    expect(h.adoptFinding).toHaveBeenCalledExactlyOnceWith('f1');
    expect(noteLines(el)).toBeNull();
  });

  it('names the checks adopting left out, after the finding is gone, until closed', async () => {
    const catalogCheck = {
      sensor: 'nginx',
      interval: 60,
      fields: [],
      testObject: false,
      credential: null,
    };
    catalog.set({
      version: '1',
      modules: [
        {
          id: 'nginx',
          name: 'Nginx',
          version: 1,
          description: '',
          instance: 'config',
          checks: [{ ...catalogCheck, key: 'tls', name: 'Zertifikat' }],
          card: [],
        },
      ],
    });
    findings.set([finding('f1')]);
    h.adoptFinding.mockImplementationOnce(() => {
      findings.set([]);
      return Promise.resolve({
        finding: finding('f1'),
        enabledChecks: ['c9'],
        disabledChecks: [],
        skippedChecks: [
          { key: 'tls', reason: 'no port for this instance' },
          { key: 'gone', reason: 'the bound check does not hold' },
        ],
      });
    });
    const el = await mount('srv-1', []);
    await fireEvent.click(screen.getByRole('button', { name: 'Übernehmen' }));
    await tick();
    expect(cardsOf(el)).toEqual([]);
    expect(screen.getByText('Nicht alles übernommen')).toBeTruthy();
    expect(noteLines(el)).toEqual([
      'Nginx · nginx@f1: Check „Zertifikat“ nicht angelegt — no port for this instance',
      'Nginx · nginx@f1: Check „gone“ nicht angelegt — the bound check does not hold',
    ]);
    await fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(noteLines(el)).toBeNull();
  });

  it('names a finding adopt all could not take, with its reason, on its server only', async () => {
    findings.set([finding('f1'), finding('f2')]);
    h.adoptAllFindings.mockImplementationOnce(() => {
      findings.set([finding('f2')]);
      return Promise.resolve({
        adopted: [
          { finding: finding('f1'), enabledChecks: [], disabledChecks: [], skippedChecks: [] },
        ],
        failed: [{ findingId: 'f2', reason: 'instance is gone' }],
      });
    });
    const el = await mount('srv-1', []);
    await fireEvent.click(screen.getByRole('button', { name: 'Alle 2 übernehmen' }));
    await tick();
    expect(h.adoptAllFindings).toHaveBeenCalledExactlyOnceWith('srv-1');
    expect(noteLines(el)).toEqual(['Nginx · nginx@f2: nicht übernommen — instance is gone']);
    selectedServerId.set('srv-2');
    await tick();
    expect(noteLines(el)).toBeNull();
  });

  it('keeps the card when the findings cannot be loaded and says so', async () => {
    findingsError.set('timeout');
    const el = await mount('srv-1', []);
    expect(cardsOf(el)).toEqual([['Neu gefunden (0)', 'false']]);
    expect(screen.getByText('Liste nicht aktuell: timeout')).toBeTruthy();
    expect(el.querySelector('.mon-panel-empty-inline')).toBeNull();
    await fireEvent.click(el.querySelector('.mon-card-toggle') as HTMLElement);
    expect(screen.getByText('Funde gerade nicht abrufbar')).toBeTruthy();
  });

  it('says when nothing is monitored and nothing was found', async () => {
    const el = await mount('srv-1', []);
    expect(el.querySelector('.mon-panel-empty-inline')?.textContent).toBe('Keine Checks vorhanden');
    expect(cardsOf(el)).toEqual([]);
    expect(h.costs).not.toHaveBeenCalled();
  });

  it('closes the page with the cost card of a real server only', async () => {
    await mount('srv-1');
    expect(h.costs).toHaveBeenCalledTimes(1);
    expect((h.costs.mock.calls[0] as unknown[])[1]).toMatchObject({ serverId: 'srv-1' });
    cleanup();
    h.costs.mockClear();
    await mount('__none');
    expect(h.costs).not.toHaveBeenCalled();
  });

  it('scan now asks the agent and holds while the request is open', async () => {
    discovery.set({ 'srv-1': scan() });
    const el = await mount('srv-1');
    expect(screen.getByText('Noch nicht gescannt')).toBeTruthy();
    const button = el.querySelector('[data-action="scan-now"]') as HTMLButtonElement;
    expect(button.textContent?.trim()).toBe('Jetzt scannen');
    expect(button.disabled).toBe(false);
    await fireEvent.click(button);
    expect(h.requestScan).toHaveBeenCalledExactlyOnceWith('srv-1');

    const fiveMinAgo = new Date(Date.now() - 5 * 60_000 - 1000).toISOString();
    discovery.set({
      'srv-1': scan({ scannedAt: fiveMinAgo, scanRequestedAt: new Date().toISOString() }),
    });
    await tick();
    expect(button.textContent?.trim()).toBe('Scan angefordert');
    expect(button.disabled).toBe(true);
    expect(screen.getByText('Zuletzt gescannt vor 5 min')).toBeTruthy();
  });

  it('names why a card does not alert', async () => {
    await mount('srv-1', [
      check('svc', 'service_process', 'ok', { mutedReason: 'maintenance window' }),
    ]);
    expect(screen.getByText('Wartungsfenster — Meldungen unterdrückt')).toBeTruthy();
  });
});
