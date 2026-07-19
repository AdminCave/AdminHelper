// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T13: the template modal's assignment section is no longer read-only — it must
// unassign servers, bulk-assign the selected ones, manage tag bindings, and mark
// tag-materialized assignments (source='tag') as not manually removable.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
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
  };
});

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoringTemplates: writable([mocks.template]),
    monitoringServers: writable(mocks.servers),
    saveTemplate: vi.fn().mockResolvedValue(true),
    deleteTemplate: vi.fn().mockResolvedValue(true),
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
});
