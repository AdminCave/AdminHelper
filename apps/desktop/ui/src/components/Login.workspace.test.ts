// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The login in the window of a workspace (R-0431): it names the workspace, shows its URL
// instead of a field once it has one, and sends that URL; "Workspaces…" brings up the launcher
// instead of a local mode. A save after the sign-in that fails is reported, not swallowed. The
// bridge is mocked; the session, workspace and status stores are the real ones.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import type { AuthSession, Settings, WorkspaceContext, WorkspaceInfo } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { WORKSPACE_PALETTE } from '$lib/models/workspace';

const h = vi.hoisted(() => ({
  workspaceContext: vi.fn<() => Promise<WorkspaceContext>>(),
  loadSettings: vi.fn<() => Promise<Settings>>(),
  saveSettings: vi.fn<(s: Settings) => Promise<void>>(),
  login:
    vi.fn<
      (url: string, user: string, password: string, selfSigned: boolean) => Promise<AuthSession>
    >(),
  enrollWithToken: vi.fn<(url: string, token: string, selfSigned: boolean) => Promise<void>>(),
  openLauncher: vi.fn<() => Promise<void>>(),
}));

vi.mock('$lib/bridge', () => ({
  workspaceContext: h.workspaceContext,
  loadSettings: h.loadSettings,
  saveSettings: h.saveSettings,
  login: h.login,
  logout: vi.fn(async () => {}),
  enrollWithToken: h.enrollWithToken,
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: vi.fn(),
  openLauncher: h.openLauncher,
}));

import { hydrate, session, settings } from '$lib/stores/session';
import { status, clearStatus } from '$lib/stores/statusBar';
import Login from './Login.svelte';

// What the window shows of the URL the workspace keeps (workspace.rs shown_url).
const SHOWN = 'https://***@ah.example.com:8443/?token=***';
const KEPT = 'https://bob:pw@ah.example.com:8443/?token=t0k';

const kundeA: WorkspaceInfo = {
  id: 'w-0a1b2c3d',
  name: 'Kunde A',
  color: WORKSPACE_PALETTE[4],
  kind: 'server',
  url: SHOWN,
  host: 'ah.example.com',
  open: true,
};

const serverSettings = (serverUrl: string | null): Settings => ({
  mode: 'server',
  url: null,
  intervalMinutes: 1,
  language: 'en',
  storePasswords: false,
  osNotifications: false,
  rdpScalingMode: 'auto',
  rdpWindowMode: 'fit',
  rdpCustomSize: null,
  rdpPerformanceProfile: 'auto',
  allowSelfSignedCerts: false,
  serverUrl,
  lastUsername: null,
});

// jsdom gives a colour of an inline style as rgb().
const rgb = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
};

/** Starts the window of `ws` as hydrate does: its context, then its settings. */
async function startIn(ws: WorkspaceInfo | null, serverUrl: string | null): Promise<void> {
  h.workspaceContext.mockResolvedValue({ launcher: false, workspace: ws });
  h.loadSettings.mockResolvedValue(serverSettings(serverUrl));
  await hydrate();
}

async function signIn(container: HTMLElement): Promise<void> {
  const user = container.querySelector<HTMLInputElement>('input[type="text"]')!;
  const pass = container.querySelector<HTMLInputElement>('input[type="password"]')!;
  await fireEvent.input(user, { target: { value: 'alice' } });
  await fireEvent.input(pass, { target: { value: 'secret' } });
  await fireEvent.submit(container.querySelector('form')!);
}

beforeAll(() => {
  setLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  clearStatus();
  h.saveSettings.mockResolvedValue(undefined);
  h.login.mockResolvedValue({ serverUrl: KEPT, username: 'alice', isAdmin: false });
});

afterEach(() => {
  cleanup();
});

describe('Login in a workspace with a URL', () => {
  beforeEach(async () => {
    await startIn(kundeA, KEPT);
  });

  it('names the workspace with its colour and shows its URL without a field', () => {
    const { container } = render(Login);

    const heading = container.querySelector<HTMLElement>('h2')!;
    expect(heading.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      `${tNow('login.signInTo')} Kunde A`,
    );
    expect(heading.querySelector<HTMLElement>('.workspace-dot')?.style.background).toBe(
      rgb(WORKSPACE_PALETTE[4]),
    );
    expect(container.querySelector('input[type="url"]')).toBeNull();
    expect(container.querySelector('[data-testid="workspace-url"]')?.textContent).toBe(SHOWN);
    // Username and password are all the form asks for.
    expect(container.querySelectorAll('form input')).toHaveLength(2);
  });

  it('signs in at the URL of the workspace and keeps the one Rust signed in at', async () => {
    const { container } = render(Login);
    await signIn(container);

    await waitFor(() => expect(get(session)).not.toBeNull());
    expect(h.login).toHaveBeenCalledWith(SHOWN, 'alice', 'secret', false);
    // The masked URL never lands in the settings: the session names the kept one.
    expect(h.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ serverUrl: KEPT, lastUsername: 'alice' }),
    );
    expect(get(settings)?.serverUrl).toBe(KEPT);
  });

  it('registers the device at the URL of the workspace, the token form has no URL field', async () => {
    h.enrollWithToken.mockResolvedValue(undefined);
    const { container } = render(Login);
    await fireEvent.click(container.querySelector('[data-action="enroll-switch"]')!);

    expect(container.querySelector('input[type="url"]')).toBeNull();
    expect(container.querySelector('[data-testid="workspace-url"]')?.textContent).toBe(SHOWN);
    const token = container.querySelector<HTMLInputElement>('input[type="text"]')!;
    await fireEvent.input(token, { target: { value: 'tok-1' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(h.enrollWithToken).toHaveBeenCalledWith(SHOWN, 'tok-1', false));
  });

  it('reports a save after the sign-in that fails, with the hint to reset the identity', async () => {
    const refused =
      'this workspace holds a device identity but no URL of its server; reset the device identity before it takes one';
    h.saveSettings.mockRejectedValueOnce(refused);
    const { container } = render(Login);
    await signIn(container);

    // The sign-in stands; what it could not keep is said, not swallowed.
    await waitFor(() => expect(get(session)).not.toBeNull());
    expect(get(status)).toMatchObject({
      text: tNow('login.notSaved', { message: refused }),
      isError: true,
    });
    expect(get(status)?.text).toContain('reset it in the settings');
    // The settings stay as saved.
    expect(get(settings)?.lastUsername).toBeNull();
  });
});

describe('Login in a workspace without a URL', () => {
  beforeEach(async () => {
    await startIn({ ...kundeA, url: null, host: null }, null);
  });

  it('asks for the URL in the login and in the token form, and signs in there', async () => {
    const { container } = render(Login);
    expect(container.querySelector('[data-testid="workspace-url"]')).toBeNull();
    const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
    expect(url.required).toBe(true);
    await fireEvent.input(url, { target: { value: '  https://srv.example  ' } });
    await signIn(container);

    await waitFor(() =>
      expect(h.login).toHaveBeenCalledWith('https://srv.example', 'alice', 'secret', false),
    );

    cleanup();
    const again = render(Login);
    await fireEvent.click(again.container.querySelector('[data-action="enroll-switch"]')!);
    expect(again.container.querySelector('input[type="url"]')).not.toBeNull();
  });

  it('after a registration shows the URL the workspace took there, and no field', async () => {
    h.enrollWithToken.mockResolvedValue(undefined);
    const { container } = render(Login);
    await fireEvent.click(container.querySelector('[data-action="enroll-switch"]')!);
    const url = container.querySelector<HTMLInputElement>('input[type="url"]')!;
    await fireEvent.input(url, { target: { value: 'https://ah.example.com:8443' } });
    const token = container.querySelector<HTMLInputElement>('input[type="text"]')!;
    await fireEvent.input(token, { target: { value: 'tok-1' } });
    // Rust made the URL of the registration the workspace's (storage.rs keep_enrolled_url).
    h.workspaceContext.mockResolvedValue({ launcher: false, workspace: kundeA });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() =>
      expect(container.querySelector('[data-testid="workspace-url"]')?.textContent).toBe(SHOWN),
    );
    expect(h.enrollWithToken).toHaveBeenCalledWith('https://ah.example.com:8443', 'tok-1', false);
    expect(h.workspaceContext).toHaveBeenCalledTimes(2);
    // Back at the sign-in, which takes the URL of the workspace now.
    expect(container.querySelector('input[type="url"]')).toBeNull();
    expect(container.querySelector('input[type="password"]')).not.toBeNull();
  });
});

describe('Login: "Workspaces…"', () => {
  beforeEach(async () => {
    await startIn(kundeA, KEPT);
  });

  it('brings up the launcher instead of a local mode', async () => {
    h.openLauncher.mockResolvedValue(undefined);
    const { container } = render(Login);

    const button = container.querySelector<HTMLButtonElement>('[data-action="open-launcher"]')!;
    expect(button.textContent?.trim()).toBe(tNow('workspace.openLauncher'));
    await fireEvent.click(button);

    expect(h.openLauncher).toHaveBeenCalledOnce();
    expect(h.saveSettings).not.toHaveBeenCalled();
  });

  it('a launcher that does not come up says why', async () => {
    h.openLauncher.mockRejectedValue(new Error('the launcher did not start'));
    const { container } = render(Login);

    await fireEvent.click(container.querySelector('[data-action="open-launcher"]')!);

    await waitFor(() =>
      expect(container.querySelector('.login-error')?.textContent).toBe(
        'the launcher did not start',
      ),
    );
  });
});
