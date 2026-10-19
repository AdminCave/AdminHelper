// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A session that could no longer be renewed ends in a reload of the window (R-0430). The
// login screen it comes up on says why, once: a later start of the screen is a plain one.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import { leaveLoginNotice } from '$lib/utils/loginNotice';

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    login: vi.fn(),
    setMode: vi.fn(async () => {}),
    setAllowSelfSignedCerts: vi.fn(async () => {}),
    settings: writable({
      mode: 'server',
      serverUrl: 'https://srv.example',
      lastUsername: 'alice',
      allowSelfSignedCerts: false,
    }),
  };
});
vi.mock('$lib/bridge', () => ({
  enrollWithToken: vi.fn(),
  resetServerCertPin: vi.fn(),
  resetDeviceIdentity: vi.fn(),
}));

import Login from './Login.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

function notice(container: HTMLElement): string | null {
  return container.querySelector('.login-info')?.textContent ?? null;
}

describe('Login — the notice a reload left (R-0430)', () => {
  it('shows the session-expired notice once', () => {
    leaveLoginNotice(tNow('login.sessionExpired'));

    const first = render(Login);
    expect(notice(first.container)).toBe('Sitzung abgelaufen — bitte neu anmelden.');
    cleanup();

    const second = render(Login);
    expect(notice(second.container)).toBeNull();
  });

  it('comes up without a notice when none was left', () => {
    const { container } = render(Login);
    expect(notice(container)).toBeNull();
  });
});
