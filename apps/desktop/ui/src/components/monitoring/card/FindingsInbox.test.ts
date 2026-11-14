// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T4 (R-1225): the "Neu gefunden" inbox. Pins what a finding
// shows (kind, module, instance, server, detail, silent, dropped and updatable checks, the
// containers of a compose finding, age), that
// adopt and dismiss hand over the finding, that one action runs at a time, and when
// "adopt all" is offered.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorFinding } from '$lib/api/types';
import { setLanguage, t } from '$lib/i18n';
import FindingsInbox from './FindingsInbox.svelte';

function finding(over: Partial<MonitorFinding> = {}): MonitorFinding {
  return {
    id: 'f1',
    serverId: 'srv-1',
    moduleId: 'nginx',
    moduleName: 'Nginx',
    instanceKey: 'nginx',
    kind: 'new',
    status: 'open',
    summary: { image: 'nginx:1.27' },
    catalogVersion: '1',
    firstSeen: null,
    lastSeen: new Date(Date.now() - 5 * 60_000 - 1000).toISOString(),
    decidedAt: null,
    silentChecks: [],
    droppedChecks: [],
    ...over,
  };
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

const resolved = () => vi.fn(() => Promise.resolve());

beforeEach(() => setLanguage('de'));
afterEach(() => cleanup());

describe('FindingsInbox', () => {
  it('says so when nothing new was found', () => {
    const { getByText, queryByRole } = render(FindingsInbox, {
      findings: [],
      onAdopt: resolved(),
      onDismiss: resolved(),
      onAdoptAll: resolved(),
    });
    expect(getByText('Nichts Neues gefunden')).toBeTruthy();
    expect(queryByRole('button')).toBeNull();
  });

  it('shows kind, module, detail, hint and age of a finding', () => {
    const { getByRole, getByText, queryByText } = render(FindingsInbox, {
      findings: [finding()],
      onAdopt: resolved(),
      onDismiss: resolved(),
    });
    const item = getByRole('listitem');
    expect(item.getAttribute('data-kind')).toBe('new');
    expect(within(item).getByText('Neu')).toBeTruthy();
    expect(within(item).getByText('Nginx')).toBeTruthy();
    // The instance key repeats the module id: not shown twice.
    expect(within(item).queryByText('nginx')).toBeNull();
    expect(getByText('nginx:1.27')).toBeTruthy();
    expect(getByText(/Übernehmen legt die Checks an\./)).toBeTruthy();
    const age = get(t)('timeAgo.minutes', { count: 5 });
    expect(getByText(`zuletzt gesehen ${age}`, { exact: false })).toBeTruthy();
    expect(queryByText(/Stille Checks/)).toBeNull();
  });

  it('names instance, server, silent and dropped checks, and falls back to the module id', () => {
    const { getByText } = render(FindingsInbox, {
      findings: [
        finding({
          kind: 'changed',
          moduleName: null,
          instanceKey: 'nginx@proxy',
          summary: {},
          silentChecks: ['c1', 'c2'],
          droppedChecks: ['c3'],
        }),
      ],
      serverName: (id: string) => `Server ${id}`,
      onAdopt: resolved(),
      onDismiss: resolved(),
    });
    expect(getByText('Geändert')).toBeTruthy();
    expect(getByText('nginx')).toBeTruthy();
    expect(getByText('nginx@proxy')).toBeTruthy();
    expect(getByText('Server srv-1')).toBeTruthy();
    expect(getByText(/Stille Checks bis dahin: 2\./)).toBeTruthy();
    expect(getByText(/Nicht mehr im Katalog, bleiben wie sie sind: 1\./)).toBeTruthy();
  });

  it('counts the checks a changed catalog definition updates on adopt', () => {
    const { getByText, queryAllByText } = render(FindingsInbox, {
      // A server before the catalog updates sends no list (f2): nothing to count.
      findings: [
        finding({ kind: 'changed', updatableChecks: ['c1', 'c2'] }),
        finding({ id: 'f2', kind: 'changed', instanceKey: 'nginx@b' }),
      ],
      onAdopt: resolved(),
      onDismiss: resolved(),
    });
    expect(getByText(/Neue Katalog-Definition, Übernehmen aktualisiert sie: 2\./)).toBeTruthy();
    expect(queryAllByText(/Neue Katalog-Definition/)).toHaveLength(1);
  });

  it('names the container of each compose service, and none for another finding', () => {
    const { getByText, queryByText } = render(FindingsInbox, {
      findings: [
        finding({
          id: 'f1',
          moduleId: 'paperless',
          instanceKey: 'paperless',
          summary: {
            services: { web: 'paperless', broker: 'redis' },
            containers: { broker: 'paperless-broker-1', web: 'paperless_web_2' },
          },
        }),
        finding({ id: 'f2', summary: { image: 'nginx', containers: 'not a map' } }),
      ],
      onAdopt: resolved(),
      onDismiss: resolved(),
    });
    expect(getByText('Container: broker: paperless-broker-1, web: paperless_web_2')).toBeTruthy();
    expect(queryByText(/Container: .*not a map/)).toBeNull();
  });

  it('hands the finding to adopt and blocks every button until it is done', async () => {
    const pending = deferred();
    const onAdopt = vi.fn(() => pending.promise);
    const onDismiss = resolved();
    const one = finding();
    const { getAllByRole } = render(FindingsInbox, {
      findings: [one, finding({ id: 'f2', instanceKey: 'nginx@b' })],
      onAdopt,
      onDismiss,
      onAdoptAll: resolved(),
    });
    const adopt = getAllByRole('button', { name: 'Übernehmen' })[0];
    await fireEvent.click(adopt);
    expect(onAdopt).toHaveBeenCalledExactlyOnceWith(one);
    expect(adopt.getAttribute('aria-busy')).toBe('true');
    for (const button of getAllByRole('button')) expect(button.hasAttribute('disabled')).toBe(true);

    await fireEvent.click(getAllByRole('button', { name: 'Ignorieren' })[1]);
    expect(onDismiss).not.toHaveBeenCalled();

    pending.resolve();
    await pending.promise;
    await tick();
    for (const button of getAllByRole('button'))
      expect(button.hasAttribute('disabled')).toBe(false);
  });

  it('hands the finding to dismiss', async () => {
    const onDismiss = resolved();
    const one = finding({ kind: 'gone' });
    const { getByRole, getByText } = render(FindingsInbox, {
      findings: [one],
      onAdopt: resolved(),
      onDismiss,
    });
    expect(getByText(/Nicht mehr gefunden\. Übernehmen schaltet die Checks ab\./)).toBeTruthy();
    await fireEvent.click(getByRole('button', { name: 'Ignorieren' }));
    expect(onDismiss).toHaveBeenCalledExactlyOnceWith(one);
  });

  it('offers adopt-all only for more than one finding and only with a handler', async () => {
    const onAdoptAll = resolved();
    const single = render(FindingsInbox, {
      findings: [finding()],
      onAdopt: resolved(),
      onDismiss: resolved(),
      onAdoptAll,
    });
    expect(single.queryByRole('button', { name: /Alle/ })).toBeNull();
    single.unmount();

    const two = [finding(), finding({ id: 'f2', instanceKey: 'nginx@b' })];
    const without = render(FindingsInbox, {
      findings: two,
      onAdopt: resolved(),
      onDismiss: resolved(),
    });
    expect(without.queryByRole('button', { name: /Alle/ })).toBeNull();
    without.unmount();

    const { getByRole } = render(FindingsInbox, {
      findings: two,
      onAdopt: resolved(),
      onDismiss: resolved(),
      onAdoptAll,
    });
    await fireEvent.click(getByRole('button', { name: 'Alle 2 übernehmen' }));
    expect(onAdoptAll).toHaveBeenCalledOnce();
  });
});
