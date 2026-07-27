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
  runCheck: vi.fn(),
}));

vi.mock('$lib/api/monitoring', () => ({ monitoringApi: mocks }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { session: writable({ session: {}, settings: {} }) };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import { setLanguage } from '$lib/i18n';
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
