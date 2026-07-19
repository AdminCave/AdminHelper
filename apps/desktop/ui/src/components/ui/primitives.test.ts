// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T16: shared desktop UI primitives — Modal (Escape/backdrop close, footer
// snippet, body-scroll lock), ConfirmDialog (promise API resolves via buttons)
// and EmptyState (message + optional CTA snippet).

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick, createRawSnippet } from 'svelte';
import { setLanguage } from '$lib/i18n';
import Modal from './Modal.svelte';
import ConfirmDialog, { confirmDialog } from './ConfirmDialog.svelte';
import EmptyState from './EmptyState.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  document.body.style.overflow = '';
});

const bodySnippet = createRawSnippet(() => ({
  render: () => '<p data-testid="content">Inhalt</p>',
}));
const footerSnippet = createRawSnippet(() => ({
  render: () => '<button data-testid="footer-btn">Weiter</button>',
}));

describe('Modal', () => {
  it('renders title, content and footer when open', async () => {
    const { getByRole, getByTestId, getByText } = render(Modal, {
      props: { open: true, title: 'Titel', children: bodySnippet, footer: footerSnippet },
    });
    await tick();
    expect(getByRole('dialog')).toBeTruthy();
    expect(getByText('Titel')).toBeTruthy();
    expect(getByTestId('content')).toBeTruthy();
    expect(getByTestId('footer-btn')).toBeTruthy();
  });

  it('closes on Escape and on backdrop click, locks body scroll while open', async () => {
    const onClose = vi.fn();
    const { container } = render(Modal, {
      props: { open: true, title: 'T', onClose, children: bodySnippet },
    });
    await tick();
    expect(document.body.style.overflow).toBe('hidden');

    await fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    const backdrop = container.querySelector('.modal-backdrop') as HTMLElement;
    await fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('does not render anything while closed', () => {
    const { container } = render(Modal, {
      props: { open: false, children: bodySnippet },
    });
    expect(container.querySelector('.modal-backdrop')).toBeNull();
    expect(document.body.style.overflow).toBe('');
  });
});

describe('ConfirmDialog', () => {
  it('resolves true on confirm and false on cancel', async () => {
    const { getByText } = render(ConfirmDialog);

    const p1 = confirmDialog('Wirklich löschen?');
    await waitFor(() => expect(getByText('Wirklich löschen?')).toBeTruthy());
    await fireEvent.click(getByText('Bestätigen'));
    await expect(p1).resolves.toBe(true);

    const p2 = confirmDialog('Nochmal?', { confirmLabel: 'Weg damit' });
    await waitFor(() => expect(getByText('Nochmal?')).toBeTruthy());
    await fireEvent.click(getByText('Abbrechen'));
    await expect(p2).resolves.toBe(false);
  });

  it('a replaced pending dialog resolves as cancelled', async () => {
    render(ConfirmDialog);
    const first = confirmDialog('Erste Frage');
    const second = confirmDialog('Zweite Frage');
    await expect(first).resolves.toBe(false); // dropped, must not hang
    // Settle the second so no pending state leaks into other tests.
    await tick();
    const btn = document.querySelector('.btn.danger') as HTMLButtonElement;
    await fireEvent.click(btn);
    await expect(second).resolves.toBe(true);
  });
});

describe('EmptyState', () => {
  it('renders the message and an optional CTA snippet', async () => {
    const cta = createRawSnippet(() => ({
      render: () => '<button data-testid="cta">Jetzt zuweisen</button>',
    }));
    const { getByText, getByTestId } = render(EmptyState, {
      props: { message: 'Keine Server', children: cta },
    });
    await tick();
    expect(getByText('Keine Server')).toBeTruthy();
    expect(getByTestId('cta')).toBeTruthy();
  });
});
