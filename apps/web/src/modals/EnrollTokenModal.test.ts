// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { flushSync, tick } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

vi.mock('$lib/api/users', () => ({ mintEnrollToken: vi.fn() }));

import EnrollTokenModal from './EnrollTokenModal.svelte';
import { mintEnrollToken } from '$lib/api/users';
import { ApiError, type EnrollmentGrant } from '$lib/api/types';
import { language } from '$lib/i18n';

// The server sends Python's isoformat with microseconds, not the three digits of
// the ECMAScript date format; the expiry must still render as a time, not '–'.
const GRANT: EnrollmentGrant = {
  token: 'enr_secret_once',
  subjectId: 'alice',
  scope: 'access',
  browser: false,
  enrollPort: 8444,
  expiresAt: '2026-10-16T12:00:00.123456Z',
};
const EXPIRES_LOCAL = new Date(Date.UTC(2026, 9, 16, 12, 0, 0, 123)).toLocaleString('de-DE');

const noop = () => {};

function renderOpen() {
  return render(EnrollTokenModal, { props: { open: true, username: 'alice', onClose: noop } });
}

// The user list passes `open` and `username` as two memoized expressions, so a click on another
// row's button changes `username` while `open` stays true and does not fire. `rerender` cannot
// show that: it swaps one signal holding the whole props object, which re-runs every effect.
function renderSwitchable() {
  const live = new SvelteMap([['username', 'alice']]);
  const view = render(EnrollTokenModal, {
    props: {
      open: true,
      get username() {
        return live.get('username') ?? '';
      },
      onClose: noop,
    },
  });
  const switchTo = (username: string) => {
    flushSync(() => {
      live.set('username', username);
    });
  };
  return { ...view, switchTo };
}

async function issue(getByRole: ReturnType<typeof renderOpen>['getByRole']) {
  await fireEvent.click(getByRole('button', { name: 'Ausstellen' }));
}

beforeEach(() => {
  vi.mocked(mintEnrollToken).mockReset();
  language.set('de');
});

afterEach(cleanup);

describe('EnrollTokenModal', () => {
  it('sends the chosen validity to mintEnrollToken', async () => {
    vi.mocked(mintEnrollToken).mockResolvedValue(GRANT);
    const { getByRole, getByLabelText } = renderOpen();

    await fireEvent.change(getByLabelText('Gültigkeit'), { target: { value: '60' } });
    await issue(getByRole);

    await waitFor(() => expect(mintEnrollToken).toHaveBeenCalledTimes(1));
    expect(mintEnrollToken).toHaveBeenCalledWith('alice', 60);
  });

  it('shows the token once with its expiry in local time, 10 minutes by default', async () => {
    vi.mocked(mintEnrollToken).mockResolvedValue(GRANT);
    const { getByRole, getByText, container } = renderOpen();

    await issue(getByRole);

    await waitFor(() =>
      expect(container.querySelector('.key-reveal')?.textContent?.trim()).toBe('enr_secret_once'),
    );
    expect(mintEnrollToken).toHaveBeenCalledWith('alice', 10);
    expect(getByText(`Gültig bis ${EXPIRES_LOCAL}`)).toBeTruthy();
    expect(getByText(/Gerät mit Token registrieren/)).toBeTruthy();
  });

  it('copies the token to the clipboard', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    vi.mocked(mintEnrollToken).mockResolvedValue(GRANT);
    const { getByRole } = renderOpen();

    await issue(getByRole);
    await waitFor(() => expect(getByRole('button', { name: 'Kopieren' })).toBeTruthy());
    await fireEvent.click(getByRole('button', { name: 'Kopieren' }));

    expect(writeText).toHaveBeenCalledWith('enr_secret_once');
  });

  it('shows an API error inside the dialog', async () => {
    vi.mocked(mintEnrollToken).mockRejectedValue(new ApiError(404, 'Unknown user'));
    const { getByRole, container } = renderOpen();

    await issue(getByRole);

    await waitFor(() => expect(getByRole('alert').textContent).toContain('Unknown user'));
    expect(container.querySelector('.key-reveal')).toBeNull();
  });

  it('drops the token on close', async () => {
    vi.mocked(mintEnrollToken).mockResolvedValue(GRANT);
    const { getByRole, queryByText, rerender } = renderOpen();

    await issue(getByRole);
    await waitFor(() => expect(queryByText('enr_secret_once')).not.toBeNull());

    await rerender({ open: false });
    await rerender({ open: true });

    expect(queryByText('enr_secret_once')).toBeNull();
    expect(getByRole('button', { name: 'Ausstellen' })).toBeTruthy();
  });

  it('does not show a token that arrives after the dialog was closed', async () => {
    let resolve: (g: EnrollmentGrant) => void = noop;
    const pending = new Promise<EnrollmentGrant>((r) => (resolve = r));
    vi.mocked(mintEnrollToken).mockReturnValue(pending);
    const { getByRole, queryByText, rerender } = renderOpen();

    await issue(getByRole);
    await rerender({ open: false });
    await rerender({ open: true, username: 'bob' });
    resolve(GRANT);
    // The dialog's own continuation was queued on `pending` first, so it has run by now.
    await pending;
    await tick();

    expect(queryByText('enr_secret_once')).toBeNull();
    expect((getByRole('button', { name: 'Ausstellen' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('starts over when the user changes while the dialog is open', async () => {
    vi.mocked(mintEnrollToken).mockResolvedValue(GRANT);
    const { getByRole, getByLabelText, queryByText, switchTo } = renderSwitchable();

    await fireEvent.change(getByLabelText('Gültigkeit'), { target: { value: '60' } });
    await issue(getByRole);
    await waitFor(() => expect(queryByText('enr_secret_once')).not.toBeNull());

    switchTo('bob');

    expect(queryByText('enr_secret_once')).toBeNull();
    expect((getByLabelText('Gültigkeit') as HTMLSelectElement).value).toBe('10');
    await issue(getByRole);
    await waitFor(() => expect(mintEnrollToken).toHaveBeenLastCalledWith('bob', 10));
  });

  it('does not show a token for the previous user that arrives after the switch', async () => {
    let resolve: (g: EnrollmentGrant) => void = noop;
    const pending = new Promise<EnrollmentGrant>((r) => (resolve = r));
    vi.mocked(mintEnrollToken).mockReturnValue(pending);
    const { getByRole, queryByText, switchTo } = renderSwitchable();

    await issue(getByRole);
    await waitFor(() => expect(mintEnrollToken).toHaveBeenCalledWith('alice', 10));
    switchTo('bob');
    resolve(GRANT);
    // The dialog's own continuation was queued on `pending` first, so it has run by now.
    await pending;
    await tick();

    expect(queryByText('enr_secret_once')).toBeNull();
    expect((getByRole('button', { name: 'Ausstellen' }) as HTMLButtonElement).disabled).toBe(false);
  });
});
