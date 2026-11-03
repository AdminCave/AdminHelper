// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The dialog primitives of the library, copied from the desktop with their tests:
// Modal (Escape/backdrop close, footer snippet, body-scroll lock, focus trap),
// ConfirmDialog (promise API resolves via buttons) and EmptyState (message + CTA).

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick, createRawSnippet } from 'svelte';

// ConfirmDialog only asks inside a session (ConfirmDialog.test.ts): a session without a server.
vi.mock('$lib/api/client', () => ({
  restoreSession: vi.fn(async () => true),
  registerAuthFailureHandler: vi.fn(),
}));
vi.mock('$lib/api/auth', () => ({
  me: vi.fn(async () => ({ id: 1, username: 'admin', is_admin: true })),
  logout: vi.fn(),
  login: vi.fn(),
}));

import { language } from '$lib/i18n';
import { auth } from '$lib/stores/auth';
import Modal from './Modal.svelte';
import ConfirmDialog, { confirmDialog } from './ConfirmDialog.svelte';
import EmptyState from './EmptyState.svelte';

language.set('de');
beforeEach(async () => {
  await auth.hydrate();
});
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

describe('Modal stacking', () => {
  it('Escape closes only the top-most stacked modal', async () => {
    const onClose = vi.fn();
    render(Modal, { props: { open: true, title: 'Editor', onClose, children: bodySnippet } });
    render(ConfirmDialog);
    const pending = confirmDialog('Sicher?');
    await tick();

    // First Escape: the stacked dialog resolves false, the editor stays open.
    await fireEvent.keyDown(document, { key: 'Escape' });
    await expect(pending).resolves.toBe(false);
    expect(onClose).not.toHaveBeenCalled();

    // Second Escape: now the editor is top of stack and closes.
    await tick();
    await fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

const formSnippet = createRawSnippet(() => ({
  render: () => '<div><input data-testid="a" /><input data-testid="b" /></div>',
}));

function opener(): HTMLButtonElement {
  const b = document.createElement('button');
  b.textContent = 'Öffnen';
  document.body.appendChild(b);
  b.focus();
  return b;
}

describe('Modal focus', () => {
  afterEach(() => document.querySelectorAll('body > button').forEach((b) => b.remove()));

  it('names itself by title and description and focuses the first body control', async () => {
    const { getByRole, getByTestId } = render(Modal, {
      props: { open: true, title: 'Server', description: 'Neu anlegen', children: formSnippet },
    });
    await tick();
    const dlg = getByRole('dialog', { name: 'Server', description: 'Neu anlegen' });
    expect(dlg.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(getByTestId('a'));
  });

  it('without controls in body or footer the panel itself takes focus', async () => {
    const { getByRole } = render(Modal, { props: { open: true, children: bodySnippet } });
    await tick();
    expect(document.activeElement).toBe(getByRole('dialog'));
    expect(getByRole('dialog').hasAttribute('aria-labelledby')).toBe(false);
  });

  it('Tab wraps forward and Shift+Tab backward inside the dialog', async () => {
    const { getByTestId } = render(Modal, {
      props: { open: true, title: 'T', children: formSnippet, footer: footerSnippet },
    });
    await tick();
    const close = document.querySelector('.modal-header button') as HTMLElement;
    const last = getByTestId('footer-btn');
    last.focus();
    const fwd = await fireEvent.keyDown(document, { key: 'Tab' });
    expect(fwd).toBe(false); // default prevented
    expect(document.activeElement).toBe(close);
    await fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
    // In the middle the platform moves focus: the trap does not interfere.
    getByTestId('a').focus();
    expect(await fireEvent.keyDown(document, { key: 'Tab' })).toBe(true);
  });

  it('returns focus to the opener on close', async () => {
    const btn = opener();
    const { rerender } = render(Modal, {
      props: { open: true, title: 'T', children: formSnippet },
    });
    await tick();
    expect(document.activeElement).not.toBe(btn);
    await rerender({ open: false });
    await tick();
    expect(document.activeElement).toBe(btn);
  });

  it('a stacked ConfirmDialog traps alone and hands focus back to the editor', async () => {
    const { getByTestId } = render(Modal, {
      props: { open: true, title: 'Editor', children: formSnippet },
    });
    render(ConfirmDialog);
    await tick();
    const field = getByTestId('b');
    field.focus();
    const pending = confirmDialog('Sicher?');
    await tick();
    const dialogs = document.querySelectorAll('[role="dialog"]');
    const top = dialogs[dialogs.length - 1] as HTMLElement;
    expect(top.contains(document.activeElement)).toBe(true);
    const topButtons = [...top.querySelectorAll('button')];
    topButtons[topButtons.length - 1].focus();
    await fireEvent.keyDown(document, { key: 'Tab' });
    expect(top.contains(document.activeElement)).toBe(true);

    await fireEvent.keyDown(document, { key: 'Escape' });
    await expect(pending).resolves.toBe(false);
    await tick();
    expect(document.activeElement).toBe(field);
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
    const btn = document.querySelector('.ui-btn-danger') as HTMLButtonElement;
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
