// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Mount smoke test (harness 8a, T16).
 *
 * 53 components under src/components, 19 mount tests. The ten below had none: a
 * component that throws on mount — or loops in an `$effect` that writes what it
 * reads — is invisible to the rest of the suite and shows up as a blank window
 * in the packaged app.
 *
 * How a loop surfaces (measured, not assumed): Svelte raises
 * `effect_update_depth_exceeded` as a THROWN error out of `render()`, after
 * roughly twenty seconds of retrying. `expect(mount).not.toThrow()` is therefore
 * the guard, and MOUNT_TIMEOUT_MS is generous enough that the failure arrives as
 * that error rather than as a five-second test timeout. The console.error spy is
 * the second net: Svelte's dev diagnostics and any component-level logging land
 * there without throwing at all.
 *
 * Six of the ten are hidden behind a store-driven `{#if}` and would mount to an
 * empty comment node; each of those gets its store driven first, so the template
 * — the part that can actually go blank — is really instantiated.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

// Any bridge call during mount must fail loudly here instead of reaching for a
// Tauri runtime that does not exist under jsdom. None of the ten calls it today;
// this is what keeps that true.
vi.mock('$lib/bridge', () => {
  const fail = (name: string) => () => {
    throw new Error(`bridge.${name}() must not be called during mount`);
  };
  // `then`/`__esModule` are probed by the module loader itself while it awaits
  // this factory — answering those with a thrower breaks the import, not a call.
  const passthrough = new Set(['then', '__esModule', 'default']);
  return new Proxy(
    {},
    {
      get: (_target, prop) =>
        typeof prop === 'symbol' || passthrough.has(String(prop)) ? undefined : fail(String(prop)),
      has: (_target, prop) => !passthrough.has(String(prop)),
    },
  );
});

// A server-mode session: TunnelIndicator renders only for one, and SettingsModal
// reads `settings`/`session` on mount.
vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  const settings = { mode: 'server', url: null, intervalMinutes: 5 };
  const session = { username: 'admin', serverUrl: 'https://example.invalid' };
  return {
    sessionStore: readable({ settings, session, ready: true }),
    settings: readable(settings),
    session: readable(session),
    currentSession: () => session,
  };
});

import { showStatus } from '$lib/stores/statusBar';
import { settingsModalOpen } from '$lib/stores/settings';
import { requestPassword } from '$lib/stores/passwordPrompt';

import StatusBar from './components/StatusBar.svelte';
import TunnelIndicator from './components/TunnelIndicator.svelte';
import NotificationBell from './components/NotificationBell.svelte';
import PasswordPrompt from './components/PasswordPrompt.svelte';
import SettingsModal from './components/SettingsModal.svelte';
import MonSummaryCards from './components/monitoring/MonSummaryCards.svelte';
import MonServerList from './components/monitoring/MonServerList.svelte';
import MonitoringAlerts from './components/monitoring/MonitoringAlerts.svelte';
import MonitoringLog from './components/monitoring/MonitoringLog.svelte';
import MonitoringTemplates from './components/monitoring/MonitoringTemplates.svelte';

setLanguage('de');

// Svelte gives up on a runaway effect after ~20s; without this the failure would
// arrive as a bare 5s test timeout instead of the error that names the cause.
const MOUNT_TIMEOUT_MS = 30_000;

const CASES: Array<{ name: string; mount: () => void }> = [
  {
    name: 'StatusBar',
    mount: () => {
      showStatus('smoke');
      render(StatusBar);
    },
  },
  { name: 'TunnelIndicator', mount: () => render(TunnelIndicator) },
  { name: 'NotificationBell', mount: () => render(NotificationBell) },
  {
    name: 'PasswordPrompt',
    mount: () => {
      void requestPassword(
        { id: 'c1', name: 'c1', kind: 'ssh', tags: [], trustCert: false },
        false,
        true,
      );
      render(PasswordPrompt);
    },
  },
  {
    name: 'SettingsModal',
    mount: () => {
      settingsModalOpen.set(true);
      render(SettingsModal);
    },
  },
  { name: 'monitoring/MonSummaryCards', mount: () => render(MonSummaryCards) },
  { name: 'monitoring/MonServerList', mount: () => render(MonServerList) },
  { name: 'monitoring/MonitoringAlerts', mount: () => render(MonitoringAlerts) },
  { name: 'monitoring/MonitoringLog', mount: () => render(MonitoringLog) },
  { name: 'monitoring/MonitoringTemplates', mount: () => render(MonitoringTemplates) },
];

afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  vi.restoreAllMocks();
});

describe('component mount smoke', () => {
  it('covers ten components', () => {
    expect(CASES).toHaveLength(10);
    expect(new Set(CASES.map((c) => c.name)).size).toBe(10);
    for (const c of CASES) expect(typeof c.mount, `${c.name} has no mount`).toBe('function');
  });

  for (const { name, mount } of CASES) {
    it(
      `mounts ${name} without errors`,
      () => {
        const errors: string[] = [];
        vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
          errors.push(args.map(String).join(' '));
        });

        expect(mount, `${name} threw on mount`).not.toThrow();
        expect(errors, `${name} logged to console.error on mount`).toEqual([]);
      },
      MOUNT_TIMEOUT_MS,
    );
  }
});
