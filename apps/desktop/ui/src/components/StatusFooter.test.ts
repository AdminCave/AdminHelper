// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// StatusFooter: per mode only the fields the app has data for (R-1062).

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { writable } from 'svelte/store';
import type { AuthSession, Settings } from '$lib/bridge/types';
import type { MonitorCheck } from '$lib/api/types';

const h = vi.hoisted(() => ({
  deviceIdentity: vi.fn(),
  syncConnections: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({
  deviceIdentity: h.deviceIdentity,
  syncConnections: h.syncConnections,
  loadConnections: vi.fn(async () => []),
  fetchConnectionsJwt: vi.fn(async () => []),
}));

vi.mock('$lib/stores/session', async () => {
  const { writable: w, derived: d } = await import('svelte/store');
  const state = w<{ settings: Settings | null; session: AuthSession | null }>({
    settings: null,
    session: null,
  });
  return {
    sessionStore: state,
    settings: d(state, (s) => s.settings),
    session: d(state, (s) => s.session),
  };
});

vi.mock('$lib/stores/tunnel', async () => {
  const { writable: w } = await import('svelte/store');
  return { tunnel: w({ ui: 'idle', status: null, mappings: [] }) };
});

vi.mock('$lib/stores/settings', async () => {
  const { writable: w } = await import('svelte/store');
  return { settingsModalOpen: w(false) };
});

vi.mock('$lib/stores/dnd', async () => {
  const { writable: w } = await import('svelte/store');
  return { dndUntil: w<number | null>(null) };
});

vi.mock('$lib/stores/monitoring', async () => {
  const { writable: w } = await import('svelte/store');
  return {
    monitoringChecks: w([]),
    monitoringHasLoaded: w(false),
    monitoringError: w<string | null>(null),
  };
});

import * as sessionMod from '$lib/stores/session';
import * as tunnelMod from '$lib/stores/tunnel';
import * as monitoringMod from '$lib/stores/monitoring';
import * as settingsMod from '$lib/stores/settings';
import * as dndMod from '$lib/stores/dnd';
import { reloadForMode } from '$lib/stores/connections';
import StatusFooter from './StatusFooter.svelte';
import { setLanguage } from '$lib/i18n';

type W<T> = ReturnType<typeof writable<T>>;
const sessionState = sessionMod.sessionStore as unknown as W<{
  settings: Settings | null;
  session: AuthSession | null;
}>;
const tunnelState = tunnelMod.tunnel as unknown as W<{ ui: string }>;
const checks = monitoringMod.monitoringChecks as unknown as W<Partial<MonitorCheck>[]>;
const hasLoaded = monitoringMod.monitoringHasLoaded as unknown as W<boolean>;
const loadError = monitoringMod.monitoringError as unknown as W<string | null>;
const modalOpen = settingsMod.settingsModalOpen as unknown as W<boolean>;
const dndUntil = dndMod.dndUntil as unknown as W<number | null>;

const base: Settings = {
  mode: 'local',
  url: null,
  intervalMinutes: 15,
  storePasswords: false,
  rdpScalingMode: 'auto',
  rdpWindowMode: 'fit',
  rdpPerformanceProfile: 'auto',
  allowSelfSignedCerts: false,
  osNotifications: false,
  sshConsole: 'external',
  terminal: {
    fontSize: 13,
    theme: 'cave',
    cursor: 'block',
    scrollback: 10000,
    copyOnSelect: true,
    rightClickPaste: true,
    confirmClose: true,
  },
};

function fields(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-field]')).map(
    (el) => el.dataset.field as string,
  );
}

function text(container: HTMLElement, field: string): string {
  return (container.querySelector(`[data-field="${field}"]`)?.textContent ?? '')
    .replace(/\s+/g, ' ')
    .trim();
}

describe('StatusFooter', () => {
  beforeAll(() => setLanguage('de'));

  beforeEach(() => {
    h.deviceIdentity.mockReset();
    h.syncConnections.mockReset();
    sessionState.set({ settings: null, session: null });
    tunnelState.set({ ui: 'idle' });
    checks.set([]);
    hasLoaded.set(false);
    loadError.set(null);
    modalOpen.set(false);
    dndUntil.set(null);
  });

  afterEach(() => cleanup());

  it('local mode shows the mode only', () => {
    sessionState.set({ settings: { ...base, mode: 'local' }, session: null });
    const { container } = render(StatusFooter);
    expect(fields(container)).toEqual(['mode']);
    expect(text(container, 'mode')).toBe('Lokal');
    expect(h.deviceIdentity).not.toHaveBeenCalled();
  });

  it('sync mode shows the hub host and the last sync, once a sync answered', async () => {
    sessionState.set({
      settings: { ...base, mode: 'sync', url: 'https://sync.example:8443/list.json' },
      session: null,
    });
    const { container } = render(StatusFooter);
    expect(fields(container)).toEqual(['mode', 'sync']);
    expect(text(container, 'mode')).toBe('Sync · sync.example:8443');
    expect(text(container, 'sync')).toBe('Letzter Sync: -');

    h.syncConnections.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode(
      { ...base, mode: 'sync', url: 'https://sync.example:8443/list.json' },
      null,
    );
    await tick();
    expect(text(container, 'sync')).toBe('Letzter Sync: -');

    h.syncConnections.mockResolvedValueOnce([]);
    await reloadForMode(
      { ...base, mode: 'sync', url: 'https://sync.example:8443/list.json' },
      null,
    );
    await tick();
    expect(text(container, 'sync')).toBe('Letzter Sync: gerade eben');

    // A new URL that fails does not inherit the time of the old one.
    h.syncConnections.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode({ ...base, mode: 'sync', url: 'https://other.example/list.json' }, null);
    await tick();
    expect(text(container, 'sync')).toBe('Letzter Sync: -');
  });

  it('server mode shows hub, tunnel, problems after the first load and the certificate', async () => {
    h.deviceIdentity.mockResolvedValue({ name: 'kevin-laptop', notAfter: '2099-03-01T00:00:00Z' });
    sessionState.set({
      settings: { ...base, mode: 'server' },
      session: { serverUrl: 'https://hub.example', username: 'kevin', isAdmin: true },
    });
    tunnelState.set({ ui: 'connected' });
    const { container } = render(StatusFooter);
    await waitFor(() => expect(fields(container)).toContain('cert'));
    // No monitoring load yet: no number to show.
    expect(fields(container)).toEqual(['mode', 'tunnel', 'cert']);
    expect(text(container, 'mode')).toBe('Server · hub.example');
    expect(text(container, 'tunnel')).toBe('Tunnel aktiv');
    expect(text(container, 'cert')).toMatch(/^Zertifikat bis \d{2}\.\d{2}\.2099$/);

    checks.set([
      { enabled: true, state: { status: 'critical' } },
      { enabled: true, state: { status: 'warning' } },
      { enabled: false, state: { status: 'critical' } },
      { enabled: true, state: { status: 'ok' } },
    ] as Partial<MonitorCheck>[]);
    hasLoaded.set(true);
    await tick();
    expect(fields(container)).toEqual(['mode', 'tunnel', 'problems', 'cert']);
    expect(text(container, 'problems')).toBe('2 Probleme');

    checks.set([{ enabled: true, state: { status: 'ok' } }] as Partial<MonitorCheck>[]);
    await tick();
    expect(text(container, 'problems')).toBe('Keine Probleme');

    // A failed load empties the checks: that is no count, so the field goes, not "no problems".
    checks.set([]);
    loadError.set('HTTP 502');
    await tick();
    expect(fields(container)).toEqual(['mode', 'tunnel', 'cert']);

    // The next load that works brings it back.
    checks.set([
      { enabled: true, state: { status: 'critical' } },
      { enabled: true, state: { status: 'warning' } },
    ] as Partial<MonitorCheck>[]);
    loadError.set(null);
    await tick();
    expect(text(container, 'problems')).toBe('2 Probleme');
  });

  it('server mode names a missing or expired certificate and hides an unreadable one', async () => {
    const server = {
      settings: { ...base, mode: 'server' as const },
      session: { serverUrl: 'https://hub.example', username: 'kevin', isAdmin: false },
    };
    h.deviceIdentity.mockResolvedValueOnce(null);
    sessionState.set(server);
    let r = render(StatusFooter);
    await waitFor(() => expect(text(r.container, 'cert')).toBe('Gerät nicht registriert'));
    cleanup();

    h.deviceIdentity.mockResolvedValueOnce({ name: 'x', notAfter: '2001-01-01T00:00:00Z' });
    r = render(StatusFooter);
    await waitFor(() => expect(text(r.container, 'cert')).toBe('Zertifikat abgelaufen'));
    cleanup();

    h.deviceIdentity.mockRejectedValueOnce(new Error('unreadable'));
    r = render(StatusFooter);
    await tick();
    await tick();
    expect(fields(r.container)).toEqual(['mode', 'tunnel']);
  });

  it('server mode reads the certificate again when the settings dialog closes', async () => {
    h.deviceIdentity.mockResolvedValueOnce(null);
    sessionState.set({
      settings: { ...base, mode: 'server' },
      session: { serverUrl: 'https://hub.example', username: 'kevin', isAdmin: false },
    });
    const { container } = render(StatusFooter);
    await waitFor(() => expect(text(container, 'cert')).toBe('Gerät nicht registriert'));

    // Enrolled in the dialog: nothing is read while it is open, once on closing.
    modalOpen.set(true);
    await tick();
    expect(h.deviceIdentity).toHaveBeenCalledTimes(1);
    h.deviceIdentity.mockResolvedValueOnce({ name: 'x', notAfter: '2099-03-01T00:00:00Z' });
    modalOpen.set(false);
    await waitFor(() => expect(text(container, 'cert')).toMatch(/^Zertifikat bis /));

    // Reset in the dialog: back to not enrolled.
    modalOpen.set(true);
    await tick();
    h.deviceIdentity.mockResolvedValueOnce(null);
    modalOpen.set(false);
    await waitFor(() => expect(text(container, 'cert')).toBe('Gerät nicht registriert'));
    expect(h.deviceIdentity).toHaveBeenCalledTimes(3);
  });

  it('server mode without a session shows the mode only', () => {
    sessionState.set({ settings: { ...base, mode: 'server' }, session: null });
    const { container } = render(StatusFooter);
    expect(fields(container)).toEqual(['mode']);
    expect(text(container, 'mode')).toBe('Server');
  });

  // R-1078: do not disturb shows its end in every mode, and goes when it ends.
  it('shows do not disturb with its end time while it holds', async () => {
    sessionState.set({ settings: { ...base, mode: 'local' }, session: null });
    const { container } = render(StatusFooter);
    expect(fields(container)).toEqual(['mode']);
    dndUntil.set(new Date(2026, 10, 4, 14, 5).getTime());
    await tick();
    expect(fields(container)).toEqual(['mode', 'dnd']);
    expect(text(container, 'dnd')).toBe('Nicht stören bis 14:05');
    dndUntil.set(null);
    await tick();
    expect(fields(container)).toEqual(['mode']);
  });
});
