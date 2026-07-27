// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T26: the maintenance modal — kind-dependent fields, timezone default from
// the client, one-off windows converted local wall clock -> UTC ISO, weekly
// payloads carrying weekdays/start_time/duration/timezone, delete via
// confirmDialog. The conversion assertion computes its expectation with the
// same Date semantics so it is host-timezone-agnostic.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MaintenanceWindow } from '$lib/api/types';

const mocks = vi.hoisted(() => ({
  createMaintenance: vi.fn().mockResolvedValue({}),
  updateMaintenance: vi.fn().mockResolvedValue({}),
  removeMaintenance: vi.fn().mockResolvedValue(undefined),
  confirmDialog: vi.fn().mockResolvedValue(true),
}));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: {
    createMaintenance: mocks.createMaintenance,
    updateMaintenance: mocks.updateMaintenance,
    removeMaintenance: mocks.removeMaintenance,
  },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { session: writable({ session: {}, settings: {} }) };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));
vi.mock('../ui/ConfirmDialog.svelte', () => ({ confirmDialog: mocks.confirmDialog }));

import { setLanguage } from '$lib/i18n';
import MaintenanceModal from './MaintenanceModal.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mount(editing: MaintenanceWindow | null = null) {
  return render(MaintenanceModal, {
    props: { open: true, editing, serverId: 'srv-1', onClose: vi.fn(), onSaved: vi.fn() },
  });
}

describe('MaintenanceModal (T26)', () => {
  it('creates a weekly window with weekdays, time, duration and timezone', async () => {
    const { container, getByText } = mount();
    await tick();
    const kind = container.querySelector('select') as HTMLSelectElement;
    await fireEvent.change(kind, { target: { value: 'weekly' } });
    await tick();

    const sunday = Array.from(container.querySelectorAll('.day-choice input')).at(
      6,
    ) as HTMLInputElement;
    await fireEvent.click(sunday);
    const tzInput = Array.from(container.querySelectorAll('input[type="text"]')).at(
      -1,
    ) as HTMLInputElement;
    await fireEvent.input(tzInput, { target: { value: 'Europe/Berlin' } });

    await fireEvent.click(getByText('Speichern'));
    await waitFor(() =>
      expect(mocks.createMaintenance).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          kind: 'weekly',
          server_id: 'srv-1',
          weekdays: [6],
          start_time: '02:00',
          duration_minutes: 120,
          timezone: 'Europe/Berlin',
          starts_at: null,
          ends_at: null,
        }),
      ),
    );
  });

  it('converts one-off local inputs to UTC ISO', async () => {
    const { container, getByText } = mount();
    await tick();
    const [starts, ends] = Array.from(
      container.querySelectorAll('input[type="datetime-local"]'),
    ) as HTMLInputElement[];
    await fireEvent.input(starts, { target: { value: '2026-07-19T14:00' } });
    await fireEvent.input(ends, { target: { value: '2026-07-19T16:00' } });
    await fireEvent.click(getByText('Speichern'));
    // Host-TZ-agnostic expectation: local wall clock interpreted in the
    // client zone, serialized as UTC ISO with the Z suffix.
    const expectedStart = new Date('2026-07-19T14:00').toISOString();
    const expectedEnd = new Date('2026-07-19T16:00').toISOString();
    expect(expectedStart.endsWith('Z')).toBe(true);
    await waitFor(() =>
      expect(mocks.createMaintenance).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          kind: 'once',
          starts_at: expectedStart,
          ends_at: expectedEnd,
          weekdays: [],
        }),
      ),
    );
  });

  it('timezone defaults to the client zone when untouched', async () => {
    const { container, getByText } = mount();
    await tick();
    const kind = container.querySelector('select') as HTMLSelectElement;
    await fireEvent.change(kind, { target: { value: 'weekly' } });
    await tick();
    const monday = Array.from(container.querySelectorAll('.day-choice input')).at(
      0,
    ) as HTMLInputElement;
    await fireEvent.click(monday);
    await fireEvent.click(getByText('Speichern'));
    await waitFor(() =>
      expect(mocks.createMaintenance).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          // Same source the component uses — host-TZ-agnostic.
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      ),
    );
  });

  it('missing kind fields report validation instead of calling the API', async () => {
    const { getByText } = mount();
    await tick();
    await fireEvent.click(getByText('Speichern'));
    expect(mocks.createMaintenance).not.toHaveBeenCalled();
  });

  it('editing prefills and delete goes through confirmDialog', async () => {
    const editing: MaintenanceWindow = {
      id: 'mw-1',
      serverId: 'srv-1',
      kind: 'weekly',
      weekdays: [5],
      startTime: '23:00',
      durationMinutes: 180,
      timezone: 'Europe/Berlin',
      enabled: true,
    };
    const { container, getByText } = mount(editing);
    await tick();
    const saturday = Array.from(container.querySelectorAll('.day-choice input')).at(
      5,
    ) as HTMLInputElement;
    expect(saturday.checked).toBe(true);

    mocks.confirmDialog.mockResolvedValueOnce(false);
    await fireEvent.click(getByText('Löschen'));
    expect(mocks.removeMaintenance).not.toHaveBeenCalled();

    mocks.confirmDialog.mockResolvedValueOnce(true);
    await fireEvent.click(getByText('Löschen'));
    await waitFor(() =>
      expect(mocks.removeMaintenance).toHaveBeenCalledWith(expect.anything(), 'mw-1'),
    );
  });
});
