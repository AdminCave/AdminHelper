// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The settings in the window of a workspace (R-0431): "This workspace" shows its name, colour
// and URL and holds what belongs to it, by its kind; "All workspaces on this device" holds what
// every window shares. There is no mode to switch: the kind and the URL of a workspace are
// fixed, so a save neither signs out nor touches the tunnel. The bridge is mocked; the settings
// and workspace stores are the real ones, the session store a stand-in each test sets.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import { settingsModalOpen, stopSyncTimer } from '$lib/stores/settings';
import { loadContext } from '$lib/stores/workspace';
import { WORKSPACE_PALETTE } from '$lib/models/workspace';
import type { ResetOutcome } from '$lib/bridge';
import type {
  AuthSession,
  Settings,
  SyncMode,
  WorkspaceContext,
  WorkspaceInfo,
} from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  workspaceContext: vi.fn<() => Promise<WorkspaceContext>>(),
  saveSettings: vi.fn(async (_settings: Settings) => undefined),
  isDeviceEnrolled: vi.fn(async () => false),
  enrollWithToken: vi.fn(async (_url: string, _token: string, _selfSigned: boolean) => undefined),
  resetDeviceIdentity: vi.fn(async (_serverUrl: string): Promise<ResetOutcome> => 'revoked'),
  resetServerCertPin: vi.fn(async (_serverUrl: string) => undefined),
  bridgeLogout: vi.fn(async () => undefined),
  // The notification rules load through the proxy once they mount.
  apiProxy: vi.fn(async (method: string, path: string) => {
    if (method === 'GET' && path === '/api/users/me/notification-prefs') {
      return { email: null, subscriptions: [] };
    }
    if (method === 'GET' && path === '/api/servers') return [];
    return null;
  }),
  refreshSettings: vi.fn(async () => undefined),
  logout: vi.fn(async () => undefined),
  startIfServerMode: vi.fn(async () => undefined),
  stopTunnel: vi.fn(async () => undefined),
  // Set by the session mock below.
  setState: (_settings: Settings, _session: AuthSession | null): void => {},
}));

// Everything but the calls under test fails loudly, as in SettingsModal.enroll.test.ts.
vi.mock('$lib/bridge', () => {
  const known: Record<string, unknown> = {
    workspaceContext: h.workspaceContext,
    saveSettings: h.saveSettings,
    isDeviceEnrolled: h.isDeviceEnrolled,
    deviceIdentity: async () => null,
    enrollWithToken: h.enrollWithToken,
    resetDeviceIdentity: h.resetDeviceIdentity,
    resetServerCertPin: h.resetServerCertPin,
    logout: h.bridgeLogout,
    apiProxy: h.apiProxy,
  };
  const passthrough = new Set(['then', '__esModule', 'default']);
  return new Proxy(
    {},
    {
      get: (_target, prop) => {
        if (typeof prop === 'symbol' || passthrough.has(String(prop))) return undefined;
        return (
          known[String(prop)] ??
          (() => {
            throw new Error(`bridge.${String(prop)}() is not part of this test`);
          })
        );
      },
      has: (_target, prop) => !passthrough.has(String(prop)),
    },
  );
});

vi.mock('$lib/stores/session', async () => {
  const { writable, derived, get: read } = await import('svelte/store');
  const state = writable<{
    settings: Settings | null;
    session: AuthSession | null;
    ready: boolean;
  }>({ settings: null, session: null, ready: true });
  h.setState = (settings, session) => state.set({ settings, session, ready: true });
  return {
    sessionStore: { subscribe: state.subscribe },
    settings: derived(state, (s) => s.settings),
    session: derived(state, (s) => s.session),
    currentSession: () => read(state).session,
    refreshSettings: h.refreshSettings,
    logout: h.logout,
  };
});

vi.mock('$lib/stores/tunnel', () => ({
  startIfServerMode: h.startIfServerMode,
  stop: h.stopTunnel,
}));

vi.mock('@tauri-apps/plugin-dialog', () => ({ save: vi.fn(async () => null) }));
vi.mock('./ui/ConfirmDialog.svelte', () => ({ confirmDialog: vi.fn(async () => true) }));

import SettingsModal from './SettingsModal.svelte';

// What the window shows of the URL the workspace keeps (workspace.rs shown_url).
const SHOWN = 'https://***@ah.example.com:8443/?token=***';
const KEPT = 'https://bob:pw@ah.example.com:8443/?token=t0k';
const SYNC = 'https://sync.example/connections.json';

const SESSION: AuthSession = { serverUrl: KEPT, username: 'alice', isAdmin: false };

function workspaceOf(kind: SyncMode, url: string | null): WorkspaceInfo {
  return {
    id: 'w-0a1b2c3d',
    name: 'Kunde A',
    color: WORKSPACE_PALETTE[4],
    kind,
    url,
    host: url ? 'ah.example.com' : null,
    open: true,
  };
}

function settingsOf(kind: SyncMode, url: string | null): Settings {
  return {
    mode: kind,
    url: kind === 'sync' ? url : null,
    intervalMinutes: 5,
    language: 'de',
    storePasswords: false,
    rdpScalingMode: 'auto',
    rdpWindowMode: 'fit',
    rdpCustomSize: '1920x1080',
    rdpPerformanceProfile: 'auto',
    allowSelfSignedCerts: false,
    serverUrl: kind === 'server' ? url : null,
    lastUsername: 'alice',
    osNotifications: false,
  };
}

/**
 * The window of a workspace of `kind`: its context shows `shown`, its settings keep `kept`, and
 * a server workspace has `session` signed in.
 */
async function windowOf(
  kind: SyncMode,
  shown: string | null,
  kept: string | null,
  session: AuthSession | null = null,
): Promise<Settings> {
  h.workspaceContext.mockResolvedValue({ launcher: false, workspace: workspaceOf(kind, shown) });
  await loadContext();
  const settings = settingsOf(kind, kept);
  h.setState(settings, session);
  return settings;
}

function open(): HTMLElement {
  settingsModalOpen.set(true);
  return render(SettingsModal).container;
}

function group(container: HTMLElement, name: 'workspace' | 'device'): HTMLElement {
  const found = container.querySelector<HTMLElement>(`[data-group="${name}"]`);
  expect(found).not.toBeNull();
  return found!;
}

function el(container: HTMLElement, selector: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(selector);
}

function button(container: HTMLElement, label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll<HTMLButtonElement>('button')].find(
    (b) => b.textContent?.trim() === label,
  );
}

// jsdom gives a colour of an inline style as rgb().
const rgb = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
};

/** The device half is the same in every kind of workspace. */
function expectDeviceGroup(container: HTMLElement): void {
  const device = group(container, 'device');
  expect(device.textContent).toContain(tNow('settings.group.device'));
  for (const key of [
    'settings.section.language',
    'settings.storePasswords',
    'settings.section.rdp',
    'settings.osNotifications',
    'settings.diagnostics.create',
  ]) {
    expect(device.textContent).toContain(tNow(key));
  }
  expect([...device.querySelectorAll('option')].map((o) => o.value)).toContain('en');
  // Nothing of a workspace on the device half.
  expect(device.textContent).not.toContain(tNow('settings.allowSelfSigned'));
  expect(device.textContent).not.toContain(tNow('settings.section.notificationRules'));
}

beforeAll(() => {
  setLanguage('de');
});

beforeEach(() => {
  vi.clearAllMocks();
  h.isDeviceEnrolled.mockResolvedValue(false);
});

afterEach(() => {
  cleanup();
  settingsModalOpen.set(false);
  stopSyncTimer();
  setLanguage('de');
});

describe('SettingsModal in a server workspace', () => {
  beforeEach(async () => {
    await windowOf('server', SHOWN, KEPT, SESSION);
  });

  it('shows name, colour and URL of the workspace, fixed, and no mode to switch', () => {
    const container = open();
    const workspace = group(container, 'workspace');

    expect(workspace.textContent).toContain(tNow('settings.group.workspace'));
    expect(el(workspace, '[data-testid="settings-workspace-name"]')?.textContent).toBe('Kunde A');
    expect(el(workspace, '.workspace-dot')?.style.background).toBe(rgb(WORKSPACE_PALETTE[4]));
    expect(el(workspace, '[data-testid="settings-workspace-url"]')?.textContent).toBe(SHOWN);
    expect(workspace.textContent).toContain(tNow('settings.serverUrl'));
    expect(workspace.textContent).toContain(tNow('settings.workspace.fixed'));
    expect(container.querySelector('input[type="radio"]')).toBeNull();
    expect(container.querySelector('input[type="url"]')).toBeNull();
  });

  it('holds sign-out, trust, pin, identity, browser certificate and notification rules', async () => {
    const container = open();
    const workspace = group(container, 'workspace');

    await waitFor(() => expect(el(workspace, '[data-action="enroll-token"]')).not.toBeNull());
    expect(button(workspace, tNow('settings.logout'))).toBeDefined();
    expect(workspace.textContent).toContain(tNow('settings.allowSelfSigned'));
    expect(button(workspace, tNow('settings.resetCertPin'))).toBeDefined();
    expect(el(workspace, '[data-action="browser-cert-export"]')).not.toBeNull();
    expect(workspace.textContent).toContain(tNow('settings.section.notificationRules'));
    await waitFor(() => expect(button(workspace, tNow('notifPrefs.save'))).toBeDefined());
    // A sync workspace's interval is not one of a server workspace.
    expect(container.querySelector('input[type="number"]')).toBeNull();
    expectDeviceGroup(container);
  });

  it('saving signs nobody out and leaves the tunnel alone', async () => {
    const stored = settingsOf('server', KEPT);
    const container = open();

    const language = [...group(container, 'device').querySelectorAll('select')].find((s) =>
      [...s.options].some((o) => o.value === 'en'),
    )!;
    await fireEvent.change(language, { target: { value: 'en' } });
    await fireEvent.click(el(container, '[data-action="settings-save"]')!);

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    // The kind and the URL go back as they came.
    expect(h.saveSettings).toHaveBeenCalledExactlyOnceWith({ ...stored, language: 'en' });
    expect(h.stopTunnel).not.toHaveBeenCalled();
    expect(h.startIfServerMode).not.toHaveBeenCalled();
    expect(h.logout).not.toHaveBeenCalled();
    expect(h.bridgeLogout).not.toHaveBeenCalled();
  });
});

describe('SettingsModal in a server workspace that kept no URL', () => {
  // A save Rust refused after the sign-in (a device identity, but no URL): the settings have
  // no server URL, the session names the server signed in to.
  beforeEach(async () => {
    await windowOf('server', null, null, SESSION);
  });

  it('says it has no URL yet', () => {
    const container = open();
    expect(el(container, '[data-testid="settings-workspace-url"]')?.textContent).toBe(
      tNow('settings.workspace.noUrl'),
    );
  });

  it('saves the language all the same: the URL is no input here', async () => {
    const stored = settingsOf('server', null);
    const container = open();

    const language = [...group(container, 'device').querySelectorAll('select')].find((s) =>
      [...s.options].some((o) => o.value === 'en'),
    )!;
    await fireEvent.change(language, { target: { value: 'en' } });
    await fireEvent.click(el(container, '[data-action="settings-save"]')!);

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledExactlyOnceWith({ ...stored, language: 'en' });
  });

  it('still resets the device identity, at the server of the session', async () => {
    h.isDeviceEnrolled.mockResolvedValue(true);
    const container = open();
    const reset = await waitFor(() => {
      const found = el(container, '[data-action="device-reset"]');
      expect(found).not.toBeNull();
      return found!;
    });

    await fireEvent.click(reset);

    await waitFor(() => expect(h.resetDeviceIdentity).toHaveBeenCalledExactlyOnceWith(KEPT));
    await waitFor(() =>
      expect(el(container, '[data-msg="device-reset"]')?.textContent).toContain(
        tNow('settings.resetDeviceId.done'),
      ),
    );
    expect(el(container, '[data-msg="device-reset"]')?.textContent).not.toContain(
      tNow('settings.resetCertPin.missingUrl'),
    );
  });

  it('after a registration shows the URL the workspace took there', async () => {
    const container = open();
    const token = await waitFor(() => {
      const found = el(container, '[data-action="enroll-token"]');
      expect(found).not.toBeNull();
      return found!;
    });
    // Rust made the URL of the registration the workspace's (storage.rs keep_enrolled_url).
    h.workspaceContext.mockResolvedValue({
      launcher: false,
      workspace: workspaceOf('server', SHOWN),
    });

    await fireEvent.input(token, { target: { value: 'tok-1' } });
    await fireEvent.click(el(container, '[data-action="enroll-submit"]')!);

    await waitFor(() =>
      expect(el(container, '[data-testid="settings-workspace-url"]')?.textContent).toBe(SHOWN),
    );
    expect(h.enrollWithToken).toHaveBeenCalledExactlyOnceWith(KEPT, 'tok-1', false);
    await waitFor(() => expect(h.startIfServerMode).toHaveBeenCalledOnce());
  });
});

describe('SettingsModal in a sync workspace', () => {
  beforeEach(async () => {
    await windowOf('sync', SYNC, SYNC);
  });

  it('shows its URL and interval, trust and pin, but no identity and no notification rules', async () => {
    h.isDeviceEnrolled.mockResolvedValue(true);
    const container = open();
    const workspace = group(container, 'workspace');

    await waitFor(() => expect(h.isDeviceEnrolled).toHaveBeenCalled());
    await h.isDeviceEnrolled.mock.results[0]?.value;
    expect(el(workspace, '[data-testid="settings-workspace-url"]')?.textContent).toBe(SYNC);
    expect(workspace.textContent).toContain(tNow('settings.syncUrl'));
    expect(el(workspace, 'input[type="number"]')).not.toBeNull();
    expect(workspace.textContent).toContain(tNow('settings.allowSelfSigned'));
    expect(button(workspace, tNow('settings.resetCertPin'))).toBeDefined();
    // Rust refuses the reset of a device identity in a sync workspace: the action is not there.
    expect(el(container, '[data-action="device-reset"]')).toBeNull();
    expect(el(container, '[data-action="enroll-token"]')).toBeNull();
    expect(button(workspace, tNow('settings.logout'))).toBeUndefined();
    expect(workspace.textContent).not.toContain(tNow('settings.section.notificationRules'));
    expectDeviceGroup(container);
  });

  it('resets the pin at the URL of the workspace', async () => {
    const container = open();

    await fireEvent.click(button(group(container, 'workspace'), tNow('settings.resetCertPin'))!);

    await waitFor(() => expect(h.resetServerCertPin).toHaveBeenCalledExactlyOnceWith(SYNC));
  });

  it('saves a changed interval with the kind and the URL as they came', async () => {
    const stored = settingsOf('sync', SYNC);
    const container = open();

    await fireEvent.input(el(container, 'input[type="number"]')!, { target: { value: '1' } });
    await fireEvent.click(el(container, '[data-action="settings-save"]')!);

    await waitFor(() => expect(get(settingsModalOpen)).toBe(false));
    expect(h.saveSettings).toHaveBeenCalledExactlyOnceWith({ ...stored, intervalMinutes: 1 });
    expect(h.stopTunnel).not.toHaveBeenCalled();
    expect(h.logout).not.toHaveBeenCalled();
  });
});

describe('SettingsModal in a local workspace', () => {
  beforeEach(async () => {
    await windowOf('local', null, null);
  });

  it('shows name and colour, no URL, nothing of a server', async () => {
    const container = open();
    const workspace = group(container, 'workspace');

    await waitFor(() => expect(h.isDeviceEnrolled).toHaveBeenCalled());
    expect(el(workspace, '[data-testid="settings-workspace-name"]')?.textContent).toBe('Kunde A');
    expect(el(workspace, '[data-testid="settings-workspace-url"]')).toBeNull();
    expect(workspace.textContent).toContain(tNow('settings.workspace.fixed'));
    expect(workspace.textContent).not.toContain(tNow('settings.allowSelfSigned'));
    expect(button(workspace, tNow('settings.resetCertPin'))).toBeUndefined();
    expect(el(container, 'input[type="number"]')).toBeNull();
    expect(el(container, '[data-action="device-reset"]')).toBeNull();
    expect(el(container, '[data-action="enroll-token"]')).toBeNull();
    expect(workspace.textContent).not.toContain(tNow('settings.section.notificationRules'));
    expectDeviceGroup(container);
  });
});
