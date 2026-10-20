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

// monitoring-alert-quality T16 (R-0424): each check definition of a template carries
// consecutive_oks next to consecutive_fails. The field shows the definition's value
// (2 when the key is missing, as the server default), and what the user enters is
// what gets saved with the template.
describe('MonitoringTemplateModal consecutive_oks (monitoring-alert-quality T16)', () => {
  type TemplateCheckDef = NonNullable<MonitoringTemplateFull['checkDefinitions']>[number];
  const OKS = 'OKs bis Entwarnung';

  function oksInputs(container: HTMLElement): HTMLInputElement[] {
    return Array.from(container.querySelectorAll('label.field'))
      .filter((f) => f.querySelector('.field-label')?.textContent?.trim() === OKS)
      .map((f) => f.querySelector('input') as HTMLInputElement);
  }

  function withChecks(defs: TemplateCheckDef[]): MonitoringTemplateFull {
    return { ...mocks.template, checkDefinitions: defs } as unknown as MonitoringTemplateFull;
  }

  function check(over: Partial<TemplateCheckDef> = {}): TemplateCheckDef {
    return {
      def_id: 'ping',
      name: 'Ping',
      check_type: 'ping',
      config: { target: 'host.example' },
      interval: '1m',
      severity: 'critical',
      consecutive_fails: 3,
      ...over,
    };
  }

  async function mountWith(editing: MonitoringTemplateFull | null) {
    const r = render(MonitoringTemplateModal, { props: { open: true, editing, onClose: vi.fn() } });
    await tick();
    return r;
  }

  // The one saveTemplate call as [input, template id or null for a new one].
  async function saved() {
    const { saveTemplate } = await import('$lib/stores/monitoring');
    await waitFor(() => expect(saveTemplate).toHaveBeenCalledTimes(1));
    return vi.mocked(saveTemplate).mock.calls[0];
  }

  it("shows each definition's value, 2 without the key, within 1 to 100", async () => {
    const { container } = await mountWith(
      withChecks([check({ consecutive_oks: 4 }), check({ def_id: 'http', name: 'HTTP' })]),
    );
    const inputs = oksInputs(container);
    expect(inputs.map((i) => i.value)).toEqual(['4', '2']);
    expect(inputs[0].type).toBe('number');
    expect(inputs[0].min).toBe('1');
    expect(inputs[0].max).toBe('100');
  });

  it('saves the entered value in the edited definition', async () => {
    const { container, getByText } = await mountWith(
      withChecks([check({ consecutive_oks: 4 }), check({ def_id: 'http', name: 'HTTP' })]),
    );
    await fireEvent.input(oksInputs(container)[1], { target: { value: '5' } });
    await fireEvent.click(getByText('Speichern'));

    const [input, id] = await saved();
    expect(id).toBe('tpl-1');
    expect(input.check_definitions.map((d) => [d.def_id, d.consecutive_oks])).toEqual([
      ['ping', 4],
      ['http', 5],
    ]);
  });

  it('starts a new definition at 2 and saves the entered value', async () => {
    const { container, getByText } = await mountWith(null);
    const name = container.querySelector('input[type="text"]') as HTMLInputElement;
    await fireEvent.input(name, { target: { value: 'Eigenes' } });
    await fireEvent.click(getByText('+ Check hinzufügen'));
    await tick();
    expect(oksInputs(container).map((i) => i.value)).toEqual(['2']);

    await fireEvent.input(oksInputs(container)[0], { target: { value: '1' } });
    await fireEvent.click(getByText('Speichern'));

    const [input, id] = await saved();
    expect(id).toBeNull();
    expect(input.name).toBe('Eigenes');
    expect(input.check_definitions).toHaveLength(1);
    expect(input.check_definitions[0]).toMatchObject({ consecutive_fails: 3, consecutive_oks: 1 });
  });
});
