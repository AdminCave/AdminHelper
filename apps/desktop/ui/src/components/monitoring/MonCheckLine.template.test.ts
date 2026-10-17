// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-templates T9: a check a template created and the user changed says so
// ("angepasst", the changed fields as its tooltip) and offers to take the template's
// values again. The question comes from the app's own dialog, rendered beside the
// line as in App's layer. For the reset the line reads its check from the store
// through a signal of its own, the way a section hands it down: rerender() would swap
// the prop by itself and could not show that the answer reached the row.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init calls matchMedia
// (missing in jsdom). The chart never renders here (collapsed line).
vi.mock('uplot', () => ({ default: class {} }));

const h = vi.hoisted(() => ({
  session: { username: 'admin', serverUrl: 'https://srv.example', token: 'jwt-1' },
  resetCheck: vi.fn(),
  fetchStatus: vi.fn(),
}));

vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return {
    currentSession: () => h.session,
    sessionStore: readable({ session: h.session, settings: {}, ready: true }),
  };
});

// Only the calls under test; anything else the line reached for would fail loudly.
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { resetCheck: h.resetCheck, fetchStatus: h.fetchStatus },
}));

import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { get } from 'svelte/store';
import type { MonitorCheck } from '$lib/api/types';
import { setLanguage, tNow } from '$lib/i18n';
import { loadMonitoring, monitoring, monitoringChecks, setExpanded } from '$lib/stores/monitoring';
import { clearStatus, status } from '$lib/stores/statusBar';
import MonCheckLine from './section/MonCheckLine.svelte';
import ConfirmDialog from '../ui/ConfirmDialog.svelte';

const RESET = 'Auf Template zurücksetzen';
const label = createRawSnippet(() => ({ render: () => '<span>CPU</span>' }));

function check(over: Partial<MonitorCheck> = {}): MonitorCheck {
  return {
    id: 'chk-1',
    serverId: 'srv-1',
    name: 'CPU',
    checkType: 'agent_resources',
    interval: '1m',
    severity: 'warning',
    enabled: true,
    config: {},
    state: { status: 'ok' },
    templateId: 'tpl-1',
    templateDefId: 'cpu',
    overriddenFields: ['interval', 'check_type'],
    ...over,
  } as MonitorCheck;
}

let stopFeed: (() => void) | null = null;

setLanguage('de');
beforeEach(() => {
  h.resetCheck.mockReset();
  h.fetchStatus.mockReset();
});
afterEach(() => {
  cleanup();
  stopFeed?.();
  stopFeed = null;
  setExpanded(null);
  clearStatus();
});

// The line with its check from the store, and the dialog layer beside it.
async function mountFromStore(initial: MonitorCheck): Promise<{
  line: HTMLElement;
  layer: HTMLElement;
}> {
  h.fetchStatus.mockResolvedValue([initial]);
  await loadMonitoring();
  const row = new SvelteMap<string, MonitorCheck>();
  stopFeed = monitoringChecks.subscribe((list) => {
    const found = list.find((c) => c.id === initial.id);
    if (found) row.set('check', found);
  });
  const line = render(MonCheckLine, {
    props: {
      get check(): MonitorCheck {
        return row.get('check')!;
      },
      label,
    },
  }).container;
  const layer = render(ConfirmDialog).container;
  return { line, layer };
}

function badge(line: HTMLElement): HTMLElement | null {
  return line.querySelector<HTMLElement>('.mon-line-badge');
}

function resetButton(line: HTMLElement): HTMLButtonElement | null {
  return line.querySelector<HTMLButtonElement>(`button[aria-label="${RESET}"]`);
}

function question(layer: HTMLElement): HTMLElement | null {
  return layer.querySelector<HTMLElement>('[role="dialog"]');
}

function buttonIn(dialog: HTMLElement, text: string): HTMLButtonElement {
  const found = [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === text,
  );
  expect(found).toBeDefined();
  return found!;
}

// Clicks the reset and returns the question it raises.
async function ask(line: HTMLElement, layer: HTMLElement): Promise<HTMLElement> {
  const btn = resetButton(line);
  expect(btn).not.toBeNull();
  await fireEvent.click(btn!);
  return waitFor(() => {
    const found = question(layer);
    expect(found).not.toBeNull();
    return found!;
  });
}

describe('MonCheckLine — badge on a changed template check (T9)', () => {
  it('names the changed fields in their translation', () => {
    const { container } = render(MonCheckLine, { props: { check: check(), label } });
    const b = badge(container);
    expect(b?.textContent?.trim()).toBe('angepasst');
    expect(b?.title).toBe('Weicht vom Template ab: Intervall, Typ');
    expect(resetButton(container)).not.toBeNull();
  });

  it('shows a field it does not know by its raw name', () => {
    const { container } = render(MonCheckLine, {
      props: { check: check({ overriddenFields: ['severity', 'retry_after'] }), label },
    });
    expect(badge(container)?.title).toBe('Weicht vom Template ab: Schweregrad, retry_after');
  });

  it.each([
    ['an unchanged template check', { overriddenFields: [] }],
    ['a template check from a server without the field', { overriddenFields: undefined }],
    ['a manual check', { templateId: null, templateDefId: null }],
  ])('offers neither badge nor reset on %s', (_name, over: Partial<MonitorCheck>) => {
    const { container } = render(MonCheckLine, { props: { check: check(over), label } });
    expect(badge(container)).toBeNull();
    expect(resetButton(container)).toBeNull();
  });
});

describe('MonCheckLine — reset to the template (T9)', () => {
  it('asks first, resets once on confirm, and shows the answer', async () => {
    const answer = check({ interval: '5m', checkType: 'agent_ping', overriddenFields: [] });
    h.resetCheck.mockResolvedValue(answer);
    const { line, layer } = await mountFromStore(check());

    const dialog = await ask(line, layer);
    expect(dialog.textContent).toContain('Intervall, Typ');
    expect(h.resetCheck).not.toHaveBeenCalled();
    // stopPropagation: the click must not expand the row underneath.
    expect(get(monitoring).expandedCheckId).toBeNull();

    await fireEvent.click(buttonIn(dialog, RESET));

    await waitFor(() => expect(badge(line)).toBeNull());
    expect(h.resetCheck).toHaveBeenCalledTimes(1);
    expect(h.resetCheck).toHaveBeenCalledWith(h.session, 'chk-1');
    expect(get(monitoringChecks)).toEqual([answer]);
    expect(resetButton(line)).toBeNull();
    expect(question(layer)).toBeNull();
  });

  it('Enter on the reset button stays away from the row', async () => {
    const { container } = render(MonCheckLine, {
      props: { check: check(), label, showChart: false },
    });

    await fireEvent.keyDown(resetButton(container)!, { key: 'Enter' });
    expect(get(monitoring).expandedCheckId).toBeNull();

    // The same key on the row itself does expand it: the probe can see an expansion.
    await fireEvent.keyDown(container.querySelector<HTMLElement>('.mon-line')!, { key: 'Enter' });
    expect(get(monitoring).expandedCheckId).toBe('chk-1');
  });

  it('cancelling resets nothing', async () => {
    const { line, layer } = await mountFromStore(check());

    const dialog = await ask(line, layer);
    await fireEvent.click(buttonIn(dialog, tNow('action.cancel')));

    await waitFor(() => expect(question(layer)).toBeNull());
    expect(h.resetCheck).not.toHaveBeenCalled();
    expect(badge(line)).not.toBeNull();
  });

  it('a failed reset shows the error in the status bar and keeps the badge', async () => {
    h.resetCheck.mockRejectedValue(new Error('Check was not created by a template'));
    const { line, layer } = await mountFromStore(check());

    const dialog = await ask(line, layer);
    await fireEvent.click(buttonIn(dialog, RESET));

    await waitFor(() =>
      expect(get(status)).toMatchObject({
        isError: true,
        text: 'Check was not created by a template',
      }),
    );
    expect(h.resetCheck).toHaveBeenCalledTimes(1);
    expect(badge(line)).not.toBeNull();
  });
});
