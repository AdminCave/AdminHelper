// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Regression guard (6.39): the open-$effect form-seeding pattern that caused an
// effect_update_depth_exceeded crash in the infra modals (see infra/modals.regression.test.ts) also
// lives in these monitoring/ansible modals. That self-loop leaves the mounted modal with every input
// and button (including Cancel) dead. Mounting each real component with open=true reproduces it, so
// asserting the dialog mounts and Cancel fires onClose guards all of them.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { setLanguage } from '$lib/i18n';
import MonitorCheckModal from './monitoring/MonitorCheckModal.svelte';
import AlertRuleModal from './monitoring/AlertRuleModal.svelte';
import MonitoringTemplateModal from './monitoring/MonitoringTemplateModal.svelte';
import PlaybookModal from './ansible/PlaybookModal.svelte';

setLanguage('de');
afterEach(cleanup);

describe('monitoring/ansible modals open without an effect loop (6.39)', () => {
  it('MonitorCheckModal: mounts and Cancel fires onClose', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole } = render(MonitorCheckModal, {
      props: { open: true, target: null, serverId: 'srv-1', onClose, onSaved: vi.fn() },
    });
    await tick();
    expect(getByRole('dialog')).toBeTruthy();
    await fireEvent.click(getByText('Abbrechen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('AlertRuleModal: mounts and Cancel fires onClose', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole } = render(AlertRuleModal, {
      props: { open: true, editing: null, servers: [], onClose },
    });
    await tick();
    expect(getByRole('dialog')).toBeTruthy();
    await fireEvent.click(getByText('Abbrechen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('MonitoringTemplateModal: mounts and Cancel fires onClose', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole } = render(MonitoringTemplateModal, {
      props: { open: true, editing: null, onClose },
    });
    await tick();
    expect(getByRole('dialog')).toBeTruthy();
    await fireEvent.click(getByText('Abbrechen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('PlaybookModal: mounts and Cancel fires onClose', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole } = render(PlaybookModal, {
      props: { open: true, target: null, onClose, onSaved: vi.fn() },
    });
    await tick();
    expect(getByRole('dialog')).toBeTruthy();
    await fireEvent.click(getByText('Abbrechen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
