// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// An admin editing themselves (R-0652). A new password makes the server end every session of the
// account, so the panel logs out at once and says why; any other change to oneself reaches the
// auth store, so navigation and routing follow the server's answer.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('$lib/api/users', () => ({ update: vi.fn() }));
vi.mock('$lib/api/servers', () => ({ list: vi.fn(async () => []) }));
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
import { update } from '$lib/api/users';
import * as authApi from '$lib/api/auth';
import { auth, isAdmin } from '$lib/stores/auth';
import type { User } from '$lib/api/types';
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
    expect(get(auth).user).toBeNull();
    expect(m.onClose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(get(toasts)).toContainEqual(
        expect.objectContaining({ kind: 'info', message: de['toast.user.ownPasswordChanged'] }),
      ),
    );
    expect(get(toasts).map((t) => t.message)).not.toContain(de['toast.user.saved']);
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
