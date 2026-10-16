// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T14: the server-detail monitoring tab gains a templates section — assigned
// templates as pills (built-ins badged, tag-materialized ones not manually
// removable), plus an assign dropdown listing only unassigned templates.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import type { Server } from '$lib/api/types';

const mocks = vi.hoisted(() => ({
  fetchStatus: vi.fn().mockResolvedValue([]),
  fetchAssignments: vi.fn().mockResolvedValue([
    { templateId: 'tpl-1', serverId: 'srv-1', templateName: 'Linux Base', source: 'manual' },
    { templateId: 'tpl-2', serverId: 'srv-1', templateName: 'Web Fleet', source: 'tag' },
  ]),
  fetchTemplates: vi.fn().mockResolvedValue([
    { id: 'tpl-1', name: 'Linux Base', builtinSlug: 'linux-base' },
    { id: 'tpl-2', name: 'Web Fleet' },
    { id: 'tpl-3', name: 'Other Template' },
  ]),
  assignTemplate: vi.fn().mockResolvedValue({}),
  unassignTemplate: vi.fn().mockResolvedValue(undefined),
  restoreTemplateChecks: vi.fn().mockResolvedValue({ restored: 0 }),
  fetchMaintenance: vi.fn().mockResolvedValue([]),
  runCheck: vi.fn(),
}));

vi.mock('$lib/api/monitoring', () => ({ monitoringApi: mocks }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { session: writable({ session: {}, settings: {} }) };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import { setLanguage } from '$lib/i18n';
import { reportError } from '$lib/stores/statusBar';
import MonitoringTab from './MonitoringTab.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const server = { id: 'srv-1', name: 'alpha', hostname: 'alpha.example' } as Server;

function mount() {
  return render(MonitoringTab, { props: { server } });
}

describe('MonitoringTab templates section', () => {
  it('renders pills with builtin badge and via-tag marker', async () => {
    const { getByText, queryByLabelText } = mount();
    await waitFor(() => expect(getByText('Linux Base')).toBeTruthy());
    expect(getByText('Standard')).toBeTruthy(); // builtinSlug badge
    expect(getByText('via Tag')).toBeTruthy(); // tag-materialized marker
    // Tag-materialized assignment has no manual remove button.
    expect(queryByLabelText('Entfernen Web Fleet')).toBeNull();
  });

  it('unassigns a manual template via its pill button', async () => {
    const { getByLabelText } = mount();
    await waitFor(() => expect(getByLabelText('Entfernen Linux Base')).toBeTruthy());
    await fireEvent.click(getByLabelText('Entfernen Linux Base'));
    await waitFor(() =>
      expect(mocks.unassignTemplate).toHaveBeenCalledWith(expect.anything(), 'tpl-1', 'srv-1'),
    );
  });

  it('dropdown offers only unassigned templates and assigns with server data', async () => {
    const { container, getByText } = mount();
    await waitFor(() => expect(getByText('Other Template')).toBeTruthy());
    const select = container.querySelector('.tpl-assign select') as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(['', 'tpl-3']); // tpl-1/tpl-2 already assigned
    await fireEvent.change(select, { target: { value: 'tpl-3' } });
    await fireEvent.click(getByText('Zuweisen'));
    await waitFor(() =>
      expect(mocks.assignTemplate).toHaveBeenCalledWith(
        expect.anything(),
        'tpl-3',
        'srv-1',
        'alpha.example',
        'alpha',
      ),
    );
    // Assigning materializes checks — the check list must refresh too
    // (mount + post-assign = 2 fetchStatus calls).
    await waitFor(() => expect(mocks.fetchStatus).toHaveBeenCalledTimes(2));
  });
});

// T10 (monitoring-templates): template checks deleted on this server stay deleted
// through the sync; each assignment that has some offers to create them again.
describe('MonitoringTab restore deleted template checks', () => {
  // Only the first load carries removedChecks; the reload after a restore gets the
  // default assignments without them.
  function withRemoved(linuxBase: number | undefined, webFleet: number | undefined): void {
    mocks.fetchAssignments.mockResolvedValueOnce([
      {
        templateId: 'tpl-1',
        serverId: 'srv-1',
        templateName: 'Linux Base',
        source: 'manual',
        removedChecks: linuxBase,
      },
      {
        templateId: 'tpl-2',
        serverId: 'srv-1',
        templateName: 'Web Fleet',
        source: 'tag',
        removedChecks: webFleet,
      },
    ]);
  }

  function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
    let resolve!: (v: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
  }

  it('offers the restore only on assignments with deleted checks, in singular and plural', async () => {
    withRemoved(3, 0);
    const first = mount();
    await waitFor(() =>
      expect(first.getByText('3 gelöschte Checks wiederherstellen')).toBeTruthy(),
    );
    expect(first.container.querySelectorAll('.tpl-restore')).toHaveLength(1);
    cleanup();

    withRemoved(undefined, 1);
    const second = mount();
    await waitFor(() =>
      expect(second.getByText('1 gelöschten Check wiederherstellen')).toBeTruthy(),
    );
    expect(second.container.querySelectorAll('.tpl-restore')).toHaveLength(1);
    cleanup();

    const none = mount();
    await waitFor(() => expect(none.getByText('Linux Base')).toBeTruthy());
    expect(none.container.querySelector('.tpl-restore')).toBeNull();
  });

  it('says it in English too', async () => {
    setLanguage('en');
    try {
      withRemoved(2, 1);
      const { getByText } = mount();
      await waitFor(() => expect(getByText('Restore 2 deleted checks')).toBeTruthy());
      expect(getByText('Restore 1 deleted check')).toBeTruthy();
    } finally {
      setLanguage('de');
    }
  });

  it('restores with template and server, then reloads assignments and checks', async () => {
    withRemoved(2, 0);
    const { getByText, queryByText } = mount();
    await waitFor(() => expect(getByText('2 gelöschte Checks wiederherstellen')).toBeTruthy());
    expect(mocks.fetchAssignments).toHaveBeenCalledTimes(1);
    expect(mocks.fetchStatus).toHaveBeenCalledTimes(1);

    await fireEvent.click(getByText('2 gelöschte Checks wiederherstellen'));

    await waitFor(() =>
      expect(mocks.restoreTemplateChecks).toHaveBeenCalledWith(expect.anything(), 'tpl-1', 'srv-1'),
    );
    await waitFor(() => expect(mocks.fetchAssignments).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchStatus).toHaveBeenCalledTimes(2));
    // The reloaded assignment has nothing deleted any more.
    await waitFor(() => expect(queryByText('2 gelöschte Checks wiederherstellen')).toBeNull());
    expect(reportError).not.toHaveBeenCalled();
  });

  it('calls the restore once on a double click while it runs', async () => {
    withRemoved(2, 0);
    const pending = deferred<{ restored: number }>();
    mocks.restoreTemplateChecks.mockReturnValueOnce(pending.promise);
    const { getByText } = mount();
    await waitFor(() => expect(getByText('2 gelöschte Checks wiederherstellen')).toBeTruthy());
    const link = getByText('2 gelöschte Checks wiederherstellen') as HTMLButtonElement;

    // Both clicks before the DOM updates: the handler itself has to refuse the second.
    void fireEvent.click(link);
    await fireEvent.click(link);
    expect(link.disabled).toBe(true);
    // A click on the now disabled link does not go through either.
    await fireEvent.click(link);
    expect(mocks.restoreTemplateChecks).toHaveBeenCalledTimes(1);

    pending.resolve({ restored: 2 });
    await waitFor(() => expect(mocks.fetchAssignments).toHaveBeenCalledTimes(2));
    expect(mocks.restoreTemplateChecks).toHaveBeenCalledTimes(1);
  });

  it('reports a failed restore like the other actions and offers it again', async () => {
    withRemoved(2, 0);
    mocks.restoreTemplateChecks.mockRejectedValueOnce(new Error('restore failed'));
    const { getByText } = mount();
    await waitFor(() => expect(getByText('2 gelöschte Checks wiederherstellen')).toBeTruthy());

    await fireEvent.click(getByText('2 gelöschte Checks wiederherstellen'));

    await waitFor(() => expect(reportError).toHaveBeenCalledWith('restore failed'));
    const link = getByText('2 gelöschte Checks wiederherstellen') as HTMLButtonElement;
    await waitFor(() => expect(link.disabled).toBe(false));
    // Nothing was restored, so nothing is reloaded.
    expect(mocks.fetchAssignments).toHaveBeenCalledTimes(1);
  });
});
