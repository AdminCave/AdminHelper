// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Exemplary component-level test enabled by the jsdom + @testing-library/svelte
// setup (6.94): mounts a real component, drives it through the promise-based
// confirm flow, and asserts the resolved value + open/closed state. Buttons are
// selected by their variant class (.danger / .ghost) to stay independent of the
// active i18n language.

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import ConfirmDialog, { confirmDialog } from './ConfirmDialog.svelte';

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
});
