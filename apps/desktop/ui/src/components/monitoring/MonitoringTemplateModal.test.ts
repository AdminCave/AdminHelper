// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T13: the template modal's assignment section is no longer read-only — it must
// unassign servers, bulk-assign the selected ones, manage tag bindings, and mark
// tag-materialized assignments (source='tag') as not manually removable.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitoringTemplateFull } from '$lib/api/types';

const mocks = vi.hoisted(() => {
  const template = {
    id: 'tpl-1',
    name: 'Linux Base',
    checkDefinitions: [],
    alertDefinitions: [],
    assignments: [
      { serverId: 'srv-1', serverName: 'alpha', source: 'manual' },
      { serverId: 'srv-2', serverName: 'beta', source: 'tag' },
    ],
    tagAssignments: [{ id: 'ta-1', templateId: 'tpl-1', tag: 'web' }],
  };
  const servers = [
    { id: 'srv-1', name: 'alpha', hostname: 'alpha.example' },
    { id: 'srv-2', name: 'beta', hostname: 'beta.example' },
    { id: 'srv-3', name: 'gamma', hostname: 'gamma.example' },
  ];
  return {
    template,
    servers,
    assignTemplateToServers: vi.fn().mockResolvedValue(true),
    unassignTemplateFromServer: vi.fn().mockResolvedValue(true),
    assignTagToTemplate: vi.fn().mockResolvedValue(true),
    removeTagFromTemplate: vi.fn().mockResolvedValue(true),
    deleteTemplate: vi.fn().mockResolvedValue(true),
    confirmDialog: vi.fn().mockResolvedValue(true),
  };
});

vi.mock('../ui/ConfirmDialog.svelte', () => ({ confirmDialog: mocks.confirmDialog }));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoringTemplates: writable([mocks.template]),
    monitoringServers: writable(mocks.servers),
    saveTemplate: vi.fn().mockResolvedValue(true),
    deleteTemplate: mocks.deleteTemplate,
    assignTemplateToServers: mocks.assignTemplateToServers,
    unassignTemplateFromServer: mocks.unassignTemplateFromServer,
    assignTagToTemplate: mocks.assignTagToTemplate,
    removeTagFromTemplate: mocks.removeTagFromTemplate,
  };
});

import { setLanguage } from '$lib/i18n';
import MonitoringTemplateModal from './MonitoringTemplateModal.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mount() {
  return render(MonitoringTemplateModal, {
    props: {
      open: true,
      editing: mocks.template as unknown as MonitoringTemplateFull,
      onClose: vi.fn(),
    },
  });
}

describe('MonitoringTemplateModal assignments', () => {
  it('unassigns a manual server via its remove button', async () => {
    const { getByLabelText } = mount();
    await tick();
    await fireEvent.click(getByLabelText('Entfernen alpha'));
    expect(mocks.unassignTemplateFromServer).toHaveBeenCalledWith('tpl-1', 'srv-1');
  });

  it('tag-materialized assignments have no remove button', async () => {
    const { queryByLabelText, getByText } = mount();
    await tick();
    expect(queryByLabelText('Entfernen beta')).toBeNull();
    expect(getByText('via Tag')).toBeTruthy();
  });

  it('bulk-assigns the selected unassigned servers', async () => {
    const { container, getByText } = mount();
    await tick();
    // Only gamma is unassigned — it is the only checkbox choice.
    const checkbox = container.querySelector(
      '.assign-choice input[type="checkbox"]',
    ) as HTMLInputElement;
    expect(checkbox.value).toBe('srv-3');
    await fireEvent.click(checkbox);
    await tick();
    await fireEvent.click(getByText('Auswahl zuweisen (1)'));
    expect(mocks.assignTemplateToServers).toHaveBeenCalledWith('tpl-1', [
      expect.objectContaining({ id: 'srv-3', hostname: 'gamma.example', name: 'gamma' }),
    ]);
  });

  it('assigns a trimmed tag and clears the input', async () => {
    const { container, getByText } = mount();
    await tick();
    const input = container.querySelector('.assign-add-tag input') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: '  db  ' } });
    await tick();
    await fireEvent.click(getByText('Tag zuweisen'));
    expect(mocks.assignTagToTemplate).toHaveBeenCalledWith('tpl-1', 'db');
    await tick();
    expect(input.value).toBe('');
  });

  it('removes a tag binding via its pill button', async () => {
    const { getByLabelText } = mount();
    await tick();
    await fireEvent.click(getByLabelText('Entfernen web'));
    expect(mocks.removeTagFromTemplate).toHaveBeenCalledWith('tpl-1', 'web');
  });

  it('delete asks via confirmDialog and deletes only on confirm (T17)', async () => {
    const { getByText } = mount();
    await tick();
    mocks.confirmDialog.mockResolvedValueOnce(false);
    await fireEvent.click(getByText('Löschen'));
    expect(mocks.confirmDialog).toHaveBeenCalledTimes(1);
    expect(mocks.deleteTemplate).not.toHaveBeenCalled();

    mocks.confirmDialog.mockResolvedValueOnce(true);
    await fireEvent.click(getByText('Löschen'));
    await waitFor(() => expect(mocks.deleteTemplate).toHaveBeenCalledWith('tpl-1'));
  });
});

// monitoring-linux-base-v2 T28 (R-0423): picking system_state for a check
// definition suggests one fail in a row, as the check form does; leaving the type
// with that 1 untouched brings back the definition's value from before the pick,
// a value entered under system_state stays.
describe('MonitoringTemplateModal system_state fails (monitoring-linux-base-v2 T28)', () => {
  type TemplateCheckDef = NonNullable<MonitoringTemplateFull['checkDefinitions']>[number];
  const FAILS = 'Fehlversuche bis Alarm';

  function card(container: HTMLElement, idx: number): Element {
    return container.querySelectorAll('.def-card')[idx];
  }

  function fieldIn(root: Element, label: string): HTMLInputElement | HTMLSelectElement {
    const match = Array.from(root.querySelectorAll('label.field')).find(
      (f) => f.querySelector('.field-label')?.textContent?.trim() === label,
    );
    if (!match) throw new Error(`no field labelled ${label}`);
    return match.querySelector('input, select') as HTMLInputElement | HTMLSelectElement;
  }

  async function pickType(container: HTMLElement, idx: number, type: string): Promise<void> {
    await fireEvent.change(fieldIn(card(container, idx), 'Typ'), { target: { value: type } });
    await tick();
  }

  function fails(container: HTMLElement, idx: number): string {
    return fieldIn(card(container, idx), FAILS).value;
  }

  function check(over: Partial<TemplateCheckDef>): TemplateCheckDef {
    return {
      name: 'Check',
      check_type: 'ping',
      config: { target: 'host.example' },
      interval: '5m',
      severity: 'critical',
      ...over,
    };
  }

  async function mountWith(defs: TemplateCheckDef[]) {
    const editing = {
      ...mocks.template,
      checkDefinitions: defs,
    } as unknown as MonitoringTemplateFull;
    const r = render(MonitoringTemplateModal, { props: { open: true, editing, onClose: vi.fn() } });
    await tick();
    return r;
  }

  it('suggests 1 and goes back to the value from before the pick', async () => {
    const { container } = await mountWith([
      check({ def_id: 'a', consecutive_fails: 5 }),
      check({ def_id: 'b', check_type: 'http', consecutive_fails: 2 }),
    ]);
    await pickType(container, 0, 'system_state');
    expect(fails(container, 0)).toBe('1');
    expect(fails(container, 1)).toBe('2');
    // The config fields below follow the type: the four switches of system_state.
    expect(card(container, 0).querySelectorAll('input[type="checkbox"]')).toHaveLength(4);

    await pickType(container, 0, 'ping');
    expect(fails(container, 0)).toBe('5');
  });

  it('keeps a value entered under system_state', async () => {
    const { container } = await mountWith([check({ consecutive_fails: 5 })]);
    await pickType(container, 0, 'system_state');
    await fireEvent.input(fieldIn(card(container, 0), FAILS), { target: { value: '2' } });
    await pickType(container, 0, 'ping');
    expect(fails(container, 0)).toBe('2');
  });

  it('goes back to 3 for a definition stored as system_state', async () => {
    const { container } = await mountWith([
      check({ check_type: 'system_state', config: {}, consecutive_fails: 1 }),
    ]);
    await pickType(container, 0, 'ping');
    expect(fails(container, 0)).toBe('3');
  });

  it("keeps each definition's value from before apart when a card above is removed", async () => {
    const { container } = await mountWith([
      check({ def_id: 'a', consecutive_fails: 5 }),
      check({ def_id: 'b', check_type: 'http', consecutive_fails: 4 }),
    ]);
    await pickType(container, 1, 'system_state');
    await fireEvent.click(card(container, 0).querySelector('button.danger') as HTMLButtonElement);
    await tick();
    expect(container.querySelectorAll('.def-card')).toHaveLength(1);
    expect(fails(container, 0)).toBe('1');

    await pickType(container, 0, 'http');
    expect(fails(container, 0)).toBe('4');
  });

  it('saves the suggested 1 with the definition', async () => {
    const { container, getByText } = await mountWith([
      check({ def_id: 'a', consecutive_fails: 5 }),
      check({ def_id: 'b', check_type: 'http', consecutive_fails: 2 }),
    ]);
    await pickType(container, 0, 'system_state');
    await fireEvent.click(getByText('Speichern'));

    const { saveTemplate } = await import('$lib/stores/monitoring');
    await waitFor(() => expect(saveTemplate).toHaveBeenCalledTimes(1));
    const [input, id] = vi.mocked(saveTemplate).mock.calls[0];
    expect(id).toBe('tpl-1');
    expect(
      input.check_definitions.map((d) => [d.def_id, d.check_type, d.consecutive_fails, d.config]),
    ).toEqual([
      ['a', 'system_state', 1, {}],
      ['b', 'http', 2, { target: 'host.example' }],
    ]);
  });
});
