// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Exemplary component-level test enabled by the jsdom + @testing-library/svelte
// setup (6.94): mounts a real component, drives it through the promise-based
// confirm flow, and asserts the resolved value + open/closed state. Buttons are
// selected by their variant class (.danger / .ghost) to stay independent of the
// active i18n language.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { get } from 'svelte/store';

// A session without a server, as in auth.test.ts: hydrate restores one, logout and the
// client's auth-failure handler end it.
vi.mock('$lib/api/client', () => ({
  restoreSession: vi.fn(async () => true),
  registerAuthFailureHandler: vi.fn(),
}));
vi.mock('$lib/api/auth', () => ({
  me: vi.fn(async () => ({ id: 1, username: 'admin', is_admin: true })),
  logout: vi.fn(),
  login: vi.fn(),
}));

import ConfirmDialog, { confirmDialog } from './ConfirmDialog.svelte';
import Modal from './Modal.svelte';
import { registerAuthFailureHandler } from '$lib/api/client';
import { auth } from '$lib/stores/auth';

afterEach(cleanup);

describe('ConfirmDialog', () => {
  it('opens with the requested message and resolves true on confirm', async () => {
    const { container, getByText } = render(ConfirmDialog);
    expect(container.querySelector('.btn.danger')).toBeNull(); // closed initially

    const answer = confirmDialog('Wirklich löschen?');
    // getByText throws when the node is absent, so a truthy result is the assertion.
    await waitFor(() => expect(getByText('Wirklich löschen?')).toBeTruthy());

    await fireEvent.click(container.querySelector('.btn.danger') as HTMLButtonElement);
    await expect(answer).resolves.toBe(true);
    await waitFor(() => expect(container.querySelector('.btn.danger')).toBeNull()); // closed again
  });

  it('resolves false on cancel', async () => {
    const { container } = render(ConfirmDialog);
    const answer = confirmDialog('Abbrechen?');
    await waitFor(() => expect(container.querySelector('.btn.ghost')).not.toBeNull());

    await fireEvent.click(container.querySelector('.btn.ghost') as HTMLButtonElement);
    await expect(answer).resolves.toBe(false);
  });

  it('cancels a still-open request when a second dialog is opened', async () => {
    const { container } = render(ConfirmDialog);
    const first = confirmDialog('erste');
    const second = confirmDialog('zweite');
    // The dropped first request must resolve (as cancelled) so its awaiter never hangs.
    await expect(first).resolves.toBe(false);

    await waitFor(() => expect(container.querySelector('.btn.ghost')).not.toBeNull());
    await fireEvent.click(container.querySelector('.btn.ghost') as HTMLButtonElement);
    await expect(second).resolves.toBe(false); // settle the second too (module store is shared)
  });

  // A question over an open modal: the modal registered its document listener first, and the
  // listener registered first takes Escape. The question is on top, so it takes it.
  it('cancels on Escape before a modal under it, which a second Escape closes', async () => {
    const below = vi.fn();
    const children = createRawSnippet(() => ({ render: () => '<p>below</p>' }));
    render(Modal, { props: { open: true, onClose: below, children } });
    const { container } = render(ConfirmDialog);
    let result: boolean | undefined;
    void confirmDialog('Escape?').then((ok) => (result = ok));
    await waitFor(() => expect(container.querySelector('.btn.danger')).not.toBeNull());

    await fireEvent.keyDown(document.body, { key: 'Escape' });

    await waitFor(() => expect(result).toBe(false));
    await waitFor(() => expect(container.querySelector('.btn.danger')).toBeNull());
    expect(below).not.toHaveBeenCalled();

    await fireEvent.keyDown(document.body, { key: 'Escape' });

    expect(below).toHaveBeenCalledTimes(1);
  });

  it('lets other keys through while a question is open', async () => {
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    try {
      const { container } = render(ConfirmDialog);
      const answer = confirmDialog('Enter?');
      await waitFor(() => expect(container.querySelector('.btn.ghost')).not.toBeNull());

      await fireEvent.keyDown(document.body, { key: 'Enter' });

      expect(seen).toHaveBeenCalledTimes(1);
      expect(container.querySelector('.btn.ghost')).not.toBeNull();
      await fireEvent.click(container.querySelector('.btn.ghost') as HTMLButtonElement);
      await expect(answer).resolves.toBe(false);
    } finally {
      document.removeEventListener('keydown', seen);
    }
  });

  // The dialog sits outside the login gate: a question left open past the session would stand
  // over the login page, and a confirm after the next login would act with the new session.
  it.each([
    ['a logout', () => auth.logout()],
    ['an expiry', () => vi.mocked(registerAuthFailureHandler).mock.calls[0][0]()],
  ])('cancels the open question on %s', async (_name, endSession) => {
    await auth.hydrate();
    expect(get(auth).user).not.toBeNull();
    const { container } = render(ConfirmDialog);
    let result: boolean | undefined;
    void confirmDialog('Session?').then((ok) => (result = ok));
    await waitFor(() => expect(container.querySelector('.btn.danger')).not.toBeNull());

    endSession();

    expect(get(auth).user).toBeNull();
    await waitFor(() => expect(result).toBe(false));
    await waitFor(() => expect(container.querySelector('.btn.danger')).toBeNull());
  });
});
