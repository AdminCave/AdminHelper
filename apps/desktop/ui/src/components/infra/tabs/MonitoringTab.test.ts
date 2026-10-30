// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T14: the server-detail monitoring tab gains a templates section — assigned
// templates as pills (built-ins badged, tag-materialized ones not manually
// removable), plus an assign dropdown listing only unassigned templates.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Server, TemplateSuggestion } from '$lib/api/types';

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
  fetchTemplateSuggestions: vi.fn().mockResolvedValue([]),
  dismissTemplateSuggestion: vi.fn().mockResolvedValue(null),
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

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
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

// T5 (monitoring-discovery): the standard templates the agent's host facts suggest
// stand above the templates section, each checked, to assign or to ignore.
describe('MonitoringTab template suggestions', () => {
  const docker: TemplateSuggestion = {
    slug: 'docker-host',
    templateId: 'tpl-dh',
    templateName: 'Docker Host',
    reason: 'subsystem:docker',
  };
  const zfs: TemplateSuggestion = {
    slug: 'zfs-storage',
    templateId: 'tpl-zfs',
    templateName: 'ZFS Storage',
    reason: 'subsystem:zfs',
  };
  const proxmox: TemplateSuggestion = {
    slug: 'proxmox-host',
    templateId: 'tpl-px',
    templateName: 'Proxmox Host',
    reason: 'subsystem:proxmox',
  };

  // clearAllMocks keeps queued once-values: a list queued for a reload that a
  // broken build never makes would otherwise leak into the next test.
  afterEach(() => {
    mocks.fetchTemplateSuggestions.mockReset().mockResolvedValue([]);
  });

  // Only the first fetch carries the suggestions; the reload after an action gets
  // the default empty list, so the hint goes away.
  async function mountWithSuggestions(...list: TemplateSuggestion[]) {
    mocks.fetchTemplateSuggestions.mockResolvedValueOnce(list);
    const view = mount();
    await waitFor(() => expect(view.container.querySelector('.tpl-suggest')).not.toBeNull());
    const hintEl = view.container.querySelector('.tpl-suggest') as HTMLElement;
    return { ...view, hintEl, hint: within(hintEl) };
  }

  function hintButton(hint: ReturnType<typeof within>, name: string): HTMLButtonElement {
    return hint.getByRole('button', { name }) as HTMLButtonElement;
  }

  it('shows no hint without suggestions', async () => {
    const { container, getByText, queryByText } = mount();
    await waitFor(() => expect(getByText('Linux Base')).toBeTruthy());
    await waitFor(() =>
      expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledWith(expect.anything(), 'srv-1'),
    );
    await tick();
    expect(container.querySelector('.tpl-suggest')).toBeNull();
    expect(queryByText('Vorgeschlagen:')).toBeNull();
    expect(queryByText('Ignorieren')).toBeNull();
  });

  it('offers each suggestion checked, with what was detected', async () => {
    const { hint } = await mountWithSuggestions(docker, zfs);
    expect(hint.getByText('Vorgeschlagen:')).toBeTruthy();
    const boxes = hint.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes).toHaveLength(2);
    expect(boxes.map((b) => b.checked)).toEqual([true, true]);
    expect(hint.getByLabelText(/Docker Host/)).toBe(boxes[0]);
    expect(hint.getByLabelText(/ZFS Storage/)).toBe(boxes[1]);
    expect(hint.getByText('erkannt: Docker')).toBeTruthy();
    expect(hint.getByText('erkannt: ZFS')).toBeTruthy();
    expect(hintButton(hint, 'Zuweisen').disabled).toBe(false);
    expect(hintButton(hint, 'Ignorieren').disabled).toBe(false);
  });

  it('names each known reason in German and English and never shows a raw code', async () => {
    const all: TemplateSuggestion[] = [
      { slug: 'linux-base', templateId: 'tpl-lb', templateName: 'Linux Srv', reason: 'os:linux' },
      { slug: 'windows-base', templateId: 'tpl-wb', templateName: 'Win Srv', reason: 'os:windows' },
      docker,
      zfs,
      proxmox,
      // Unknown codes, among them keys every plain object inherits.
      { slug: 'x-1', templateId: 'tpl-x1', templateName: 'X1', reason: 'os:darwin' },
      { slug: 'x-2', templateId: 'tpl-x2', templateName: 'X2', reason: 'constructor' },
      { slug: 'x-3', templateId: 'tpl-x3', templateName: 'X3', reason: 'subsystem:__proto__' },
    ];
    const de = await mountWithSuggestions(...all);
    for (const text of ['Linux', 'Windows', 'Docker', 'ZFS', 'Proxmox']) {
      expect(de.hint.getByText(`erkannt: ${text}`)).toBeTruthy();
    }
    expect(de.hint.getAllByText('passt zu diesem Server')).toHaveLength(3);
    expect(de.hintEl.textContent).not.toMatch(/darwin|constructor|__proto__|os:|subsystem:/);
    cleanup();

    setLanguage('en');
    try {
      const en = await mountWithSuggestions(...all);
      expect(en.hint.getByText('Suggested:')).toBeTruthy();
      for (const text of ['Linux', 'Windows', 'Docker', 'ZFS', 'Proxmox']) {
        expect(en.hint.getByText(`detected: ${text}`)).toBeTruthy();
      }
      expect(en.hint.getAllByText('fits this server')).toHaveLength(3);
      expect(en.hintEl.textContent).not.toMatch(/darwin|constructor|__proto__|os:|subsystem:/);
      expect(hintButton(en.hint, 'Assign')).toBeTruthy();
      expect(hintButton(en.hint, 'Ignore')).toBeTruthy();
    } finally {
      setLanguage('de');
    }
  });

  it('assigns each checked template with the server data, leaves an unchecked one, then reloads', async () => {
    const { container, hint } = await mountWithSuggestions(docker, zfs);
    expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(1);
    expect(mocks.fetchAssignments).toHaveBeenCalledTimes(1);
    expect(mocks.fetchStatus).toHaveBeenCalledTimes(1);

    await fireEvent.click(hint.getByLabelText(/ZFS Storage/));
    await fireEvent.click(hintButton(hint, 'Zuweisen'));

    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchAssignments).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchStatus).toHaveBeenCalledTimes(2));
    expect(mocks.assignTemplate).toHaveBeenCalledTimes(1);
    expect(mocks.assignTemplate).toHaveBeenCalledWith(
      expect.anything(),
      'tpl-dh',
      'srv-1',
      'alpha.example',
      'alpha',
    );
    expect(mocks.dismissTemplateSuggestion).not.toHaveBeenCalled();
    expect(reportError).not.toHaveBeenCalled();
    // The reload has no suggestions left.
    await waitFor(() => expect(container.querySelector('.tpl-suggest')).toBeNull());
  });

  it('ignores each checked suggestion by its slug, leaves an unchecked one, then reloads', async () => {
    const { container, hint } = await mountWithSuggestions(docker, zfs, proxmox);

    await fireEvent.click(hint.getByLabelText(/Proxmox Host/));
    await fireEvent.click(hintButton(hint, 'Ignorieren'));

    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchAssignments).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchStatus).toHaveBeenCalledTimes(2));
    expect(mocks.dismissTemplateSuggestion.mock.calls.map((c) => c.slice(1))).toEqual([
      ['srv-1', 'docker-host'],
      ['srv-1', 'zfs-storage'],
    ]);
    expect(mocks.assignTemplate).not.toHaveBeenCalled();
    expect(reportError).not.toHaveBeenCalled();
    await waitFor(() => expect(container.querySelector('.tpl-suggest')).toBeNull());
  });

  it('shows no hint and no error when the suggestions cannot be fetched', async () => {
    mocks.fetchTemplateSuggestions.mockRejectedValueOnce(new Error('HTTP 404: Not Found'));
    const { container, getByText } = mount();
    await waitFor(() => expect(getByText('Other Template')).toBeTruthy());
    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 0));
    await tick();
    expect(container.querySelector('.tpl-suggest')).toBeNull();
    expect(reportError).not.toHaveBeenCalled();
    // The rest of the tab stays usable.
    const select = container.querySelector('.tpl-assign select') as HTMLSelectElement;
    expect(select.disabled).toBe(false);
  });

  it('locks the buttons while it runs and assigns each template once on a double click', async () => {
    const pending = deferred<unknown>();
    mocks.assignTemplate.mockReturnValueOnce(pending.promise);
    const { container, hint } = await mountWithSuggestions(docker, zfs);
    const assign = hintButton(hint, 'Zuweisen');
    const ignore = hintButton(hint, 'Ignorieren');

    // Both clicks before the DOM updates: the handler itself has to refuse the second.
    void fireEvent.click(assign);
    await fireEvent.click(assign);
    expect(assign.disabled).toBe(true);
    expect(ignore.disabled).toBe(true);
    expect((hint.getAllByRole('checkbox') as HTMLInputElement[]).every((b) => b.disabled)).toBe(
      true,
    );
    // The other template actions share the lock.
    expect((container.querySelector('.tpl-assign select') as HTMLSelectElement).disabled).toBe(
      true,
    );
    await fireEvent.click(assign);
    await fireEvent.click(ignore);
    expect(mocks.assignTemplate).toHaveBeenCalledTimes(1);
    expect(mocks.dismissTemplateSuggestion).not.toHaveBeenCalled();

    pending.resolve({});
    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(2));
    // One call per checked template, not one per click.
    expect(mocks.assignTemplate.mock.calls.map((c) => c[1])).toEqual(['tpl-dh', 'tpl-zfs']);
    expect(mocks.dismissTemplateSuggestion).not.toHaveBeenCalled();
  });

  it.each([
    ['Zuweisen', mocks.assignTemplate, 'HTTP 409: already assigned'],
    ['Ignorieren', mocks.dismissTemplateSuggestion, 'HTTP 502: Bad Gateway'],
  ])(
    'reports a failed %s like the other actions and still reloads the suggestions and assignments',
    async (label, call, message) => {
      call.mockRejectedValueOnce(new Error(message));
      const { hint } = await mountWithSuggestions(docker, zfs);
      // What the server suggests now: Docker Host went stale, assigned meanwhile by a
      // tag or by another admin.
      mocks.fetchTemplateSuggestions.mockResolvedValueOnce([zfs]);

      await fireEvent.click(hintButton(hint, label));

      await waitFor(() => expect(reportError).toHaveBeenCalledWith(message));
      await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(mocks.fetchAssignments).toHaveBeenCalledTimes(2));
      // Stops at the first failure.
      expect(call).toHaveBeenCalledTimes(1);
      // The tab heals itself: the stale suggestion is gone, the other one is offered again.
      await waitFor(() => expect(hint.queryByText('Docker Host')).toBeNull());
      expect((hint.getAllByRole('checkbox') as HTMLInputElement[]).map((b) => b.checked)).toEqual([
        true,
      ]);
      expect(hint.getByLabelText(/ZFS Storage/)).toBeTruthy();
      await waitFor(() => expect(hintButton(hint, label).disabled).toBe(false));
    },
  );

  it('reloads after a failure part way, since the calls before it went through', async () => {
    mocks.assignTemplate
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('HTTP 409: already assigned'));
    const { hint } = await mountWithSuggestions(docker, zfs);

    await fireEvent.click(hintButton(hint, 'Zuweisen'));

    await waitFor(() => expect(reportError).toHaveBeenCalledWith('HTTP 409: already assigned'));
    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchAssignments).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.fetchStatus).toHaveBeenCalledTimes(2));
    expect(mocks.assignTemplate).toHaveBeenCalledTimes(2);
  });

  it('refreshes the suggestions when a template is assigned or removed by hand', async () => {
    // The dropdown offers tpl-3, which is also suggested.
    const { container, getByLabelText } = await mountWithSuggestions({
      ...docker,
      templateId: 'tpl-3',
      templateName: 'Other Template',
    });
    const select = container.querySelector('.tpl-assign select') as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: 'tpl-3' } });
    await fireEvent.click(container.querySelector('.tpl-assign button') as HTMLButtonElement);
    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(container.querySelector('.tpl-suggest')).toBeNull());

    const remove = getByLabelText('Entfernen Linux Base') as HTMLButtonElement;
    await waitFor(() => expect(remove.disabled).toBe(false));
    await fireEvent.click(remove);
    await waitFor(() => expect(mocks.fetchTemplateSuggestions).toHaveBeenCalledTimes(3));
  });
});
