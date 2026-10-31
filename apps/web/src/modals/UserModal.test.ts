// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// An admin editing themselves (R-0652). A new password makes the server end every session of the
// account, so the panel logs out at once and says why; any other change to oneself reaches the
// auth store, so navigation and routing follow the server's answer.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('$lib/api/users', () => ({ list: vi.fn(), update: vi.fn(), create: vi.fn() }));
vi.mock('$lib/api/servers', () => ({ listSummaries: vi.fn(async () => []) }));
// A session without a server, as in ConfirmDialog.test.ts.
vi.mock('$lib/api/client', () => ({
  restoreSession: vi.fn(async () => true),
  registerAuthFailureHandler: vi.fn(),
}));
vi.mock('$lib/api/auth', () => ({
  me: vi.fn(async () => ({ id: 1, username: 'admin', is_admin: true })),
  logout: vi.fn(async () => {}),
  login: vi.fn(),
}));

import UserModal from './UserModal.svelte';
import { update, create } from '$lib/api/users';
import * as serversApi from '$lib/api/servers';
import * as authApi from '$lib/api/auth';
import { auth, isAdmin } from '$lib/stores/auth';
import { ApiError, type ServerSummary, type User } from '$lib/api/types';
import { language } from '$lib/i18n';
import { translations } from '$lib/i18n/dictionaries';
import { toasts, dismissToast } from '$lib/stores/notifications';

const de = translations.de;
const SELF: User = { id: 1, username: 'admin', is_admin: true, server_ids: [] };
const OTHER: User = { id: 2, username: 'alice', is_admin: false, server_ids: [] };

/** The dialog open on `editing`; the only checkbox is "admin", the server list is empty. */
function renderModal(editing: User) {
  const onClose = vi.fn();
  const view = render(UserModal, { props: { open: true, editing, onClose } });
  const el = (selector: string) => view.container.querySelector(selector) as HTMLInputElement;
  return {
    onClose,
    typePassword: (value: string) => fireEvent.input(el('#ufPassword'), { target: { value } }),
    toggleAdmin: () => fireEvent.click(el('input[type="checkbox"]')),
    submit: () => fireEvent.submit(el('#user-form')),
  };
}

beforeEach(async () => {
  // The server answers a PUT with the user as stored.
  vi.mocked(update)
    .mockReset()
    .mockImplementation(async (id, data) => ({
      ...(id === SELF.id ? SELF : OTHER),
      is_admin: data.is_admin,
      server_ids: data.server_ids,
    }));
  vi.mocked(authApi.logout).mockClear();
  language.set('de');
  await auth.hydrate();
});

afterEach(() => {
  cleanup();
  for (const t of get(toasts)) dismissToast(t.id);
});

describe('UserModal editing the signed-in admin', () => {
  it('logs out with a hint after a change of the own password', async () => {
    const m = renderModal(SELF);
    await m.typePassword('a-new-password');

    await m.submit();

    await waitFor(() => expect(authApi.logout).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith(1, expect.objectContaining({ password: 'a-new-password' }));
    // The PUT goes out first: logging out before it drops the token, and the password stays old.
    expect(vi.mocked(update).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(authApi.logout).mock.invocationCallOrder[0],
    );
    expect(get(auth).user).toBeNull();
    expect(m.onClose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(get(toasts)).toContainEqual(
        expect.objectContaining({ kind: 'info', message: de['toast.user.ownPasswordChanged'] }),
      ),
    );
    expect(get(toasts).map((t) => t.message)).not.toContain(de['toast.user.saved']);
  });

  it('keeps the session and shows the error when the server refuses the own password', async () => {
    // As the server answers a password under 8 characters (UserUpdate.password, min_length=8).
    const refused = 'String should have at least 8 characters';
    vi.mocked(update).mockRejectedValueOnce(new ApiError(422, refused));
    const m = renderModal(SELF);
    await m.typePassword('short');

    await m.submit();

    await waitFor(() =>
      expect(get(toasts)).toContainEqual(
        expect.objectContaining({ kind: 'error', message: refused }),
      ),
    );
    expect(update).toHaveBeenCalledWith(1, expect.objectContaining({ password: 'short' }));
    expect(authApi.logout).not.toHaveBeenCalled();
    expect(get(auth).user).toEqual({ id: 1, username: 'admin', is_admin: true });
    expect(m.onClose).not.toHaveBeenCalled();
    expect(get(toasts).map((t) => t.message)).not.toContain(de['toast.user.ownPasswordChanged']);
  });

  it('drops the admin right from the session when demoting oneself without a password', async () => {
    const m = renderModal(SELF);
    await m.toggleAdmin();

    await m.submit();

    await waitFor(() => expect(m.onClose).toHaveBeenCalledTimes(1));
    expect(vi.mocked(update).mock.calls[0][1]).toEqual({ is_admin: false, server_ids: [] });
    expect(get(isAdmin)).toBe(false);
    expect(get(auth).user).toMatchObject({ id: 1, username: 'admin', is_admin: false });
    expect(authApi.logout).not.toHaveBeenCalled();
  });

  it('leaves the session alone when another user gets a new password', async () => {
    const m = renderModal(OTHER);
    await m.typePassword('a-new-password');

    await m.submit();

    await waitFor(() => expect(m.onClose).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith(2, expect.objectContaining({ password: 'a-new-password' }));
    expect(authApi.logout).not.toHaveBeenCalled();
    expect(get(auth).user).toEqual({ id: 1, username: 'admin', is_admin: true });
    expect(get(toasts)).toContainEqual(
      expect.objectContaining({ kind: 'success', message: de['toast.user.saved'] }),
    );
  });
});

// The form -> payload mapping and the server list (R-0722). The list holds two servers; a server's
// checkbox is found by its name.
describe('UserModal form and server list', () => {
  const SERVERS = [
    { id: 's1', name: 'web-01', hostname: 'web-01.example' },
    { id: 's2', name: 'db-01', hostname: 'db-01.example' },
  ] as ServerSummary[];

  beforeEach(() => {
    vi.mocked(serversApi.listSummaries).mockClear().mockResolvedValue(SERVERS);
    vi.mocked(create)
      .mockReset()
      .mockImplementation(async (data) => ({ id: 3, ...data }) as User);
  });

  afterEach(() => {
    vi.mocked(serversApi.listSummaries).mockReset().mockResolvedValue([]);
  });

  function serverBox(container: HTMLElement, name: string): HTMLInputElement {
    const label = [...container.querySelectorAll('label')].find((l) =>
      [...l.querySelectorAll('span')].some((sp) => sp.textContent === name),
    );
    return label?.querySelector('input[type="checkbox"]') as HTMLInputElement;
  }

  function open(editing: User | null) {
    const onClose = vi.fn();
    const view = render(UserModal, { props: { open: true, editing, onClose } });
    const el = (selector: string) => view.container.querySelector(selector) as HTMLInputElement;
    return { onClose, view, el, submit: () => fireEvent.submit(el('#user-form')) };
  }

  it('creates a user with a trimmed name and the servers ticked', async () => {
    const m = open(null);
    await waitFor(() => expect(serverBox(m.view.container, 'db-01')).toBeTruthy());
    await fireEvent.input(m.el('#ufUsername'), { target: { value: '  alice  ' } });
    await fireEvent.input(m.el('#ufPassword'), { target: { value: 'a-password' } });
    await fireEvent.click(serverBox(m.view.container, 'db-01'));
    await m.submit();

    await waitFor(() => expect(m.onClose).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({
      username: 'alice',
      password: 'a-password',
      is_admin: false,
      server_ids: ['s2'],
    });
    expect(get(toasts).map((t) => t.message)).toContain(de['toast.user.created']);
  });

  it('a new user without a password sends nothing and says why', async () => {
    const m = open(null);
    await fireEvent.input(m.el('#ufUsername'), { target: { value: 'bob' } });
    await m.submit();

    await waitFor(() =>
      expect(get(toasts)).toContainEqual(
        expect.objectContaining({ kind: 'error', message: de['modal.user.passwordRequired'] }),
      ),
    );
    expect(create).not.toHaveBeenCalled();
    expect(m.onClose).not.toHaveBeenCalled();
  });

  it('editing another user swaps the servers and sends no password key', async () => {
    const m = open({ ...OTHER, server_ids: ['s1'] });
    await waitFor(() => expect(serverBox(m.view.container, 'web-01').checked).toBe(true));
    await fireEvent.click(serverBox(m.view.container, 'web-01'));
    await fireEvent.click(serverBox(m.view.container, 'db-01'));
    await m.submit();

    await waitFor(() => expect(m.onClose).toHaveBeenCalledTimes(1));
    expect(vi.mocked(update).mock.calls[0]).toEqual([2, { is_admin: false, server_ids: ['s2'] }]);
    expect(get(toasts).map((t) => t.message)).toContain(de['toast.user.saved']);
  });

  it('lists every server with its name and host name', async () => {
    const m = open(null);
    await waitFor(() => expect(m.view.container.textContent).toContain('web-01.example'));
    for (const s of SERVERS) {
      const box = serverBox(m.view.container, s.name);
      expect(box).toBeTruthy();
      expect(box.closest('label')?.textContent).toContain(s.hostname);
    }
  });

  it('a list that fails to load says so and shows the error', async () => {
    vi.mocked(serversApi.listSummaries).mockRejectedValue(new ApiError(500, 'inventory down'));
    const m = open(null);

    await waitFor(() =>
      expect(m.view.container.textContent).toContain(de['page.users.serverLoadFailed']),
    );
    expect(get(toasts)).toContainEqual(
      expect.objectContaining({ kind: 'error', message: 'inventory down' }),
    );
    expect(m.view.container.textContent).not.toContain(de['page.users.noServers']);
  });

  it('opening the dialog loads the server summary once', async () => {
    const m = open(null);
    await waitFor(() => expect(serverBox(m.view.container, 'web-01')).toBeTruthy());
    expect(serversApi.listSummaries).toHaveBeenCalledTimes(1);
  });

  it('an empty list says there are no servers', async () => {
    vi.mocked(serversApi.listSummaries).mockResolvedValue([]);
    const m = open(null);

    await waitFor(() => expect(m.view.container.textContent).toContain(de['page.users.noServers']));
  });
});
