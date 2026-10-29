// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The copy buttons of the four dialogs that show a value once (R-0724): a click copies exactly the
// value shown and says so.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import type { Component } from 'svelte';

vi.mock('$lib/api/users', () => ({ mintEnrollToken: vi.fn() }));

import KeyRevealModal from './KeyRevealModal.svelte';
import WebhookTokenModal from './WebhookTokenModal.svelte';
import EnrollTokenModal from './EnrollTokenModal.svelte';
import FrpConfigPreviewModal from './FrpConfigPreviewModal.svelte';
import { mintEnrollToken } from '$lib/api/users';
import type { EnrollmentGrant } from '$lib/api/types';
import { language } from '$lib/i18n';
import { toasts, dismissToast } from '$lib/stores/notifications';

const GRANT: EnrollmentGrant = {
  token: 'enroll-placeholder',
  subjectId: 'alice',
  scope: 'access',
  browser: false,
  enrollPort: 8444,
  expiresAt: '2026-10-16T12:00:00Z',
};

// The part of a rendered dialog the cases use.
interface Shown {
  container: HTMLElement;
  getByRole: (role: string, options: { name: string }) => HTMLElement;
}

interface CopyCase {
  name: string;
  component: Component<Record<string, unknown>>;
  props: Record<string, unknown>;
  value: string;
  toast: string;
  // Steps before the value is on screen.
  prepare?: (view: Shown) => Promise<void>;
}

const cases: CopyCase[] = [
  {
    name: 'KeyRevealModal',
    component: KeyRevealModal as unknown as Component<Record<string, unknown>>,
    props: { open: true, value: 'key-placeholder', onClose: () => {} },
    value: 'key-placeholder',
    toast: 'In Zwischenablage kopiert',
  },
  {
    name: 'WebhookTokenModal',
    component: WebhookTokenModal as unknown as Component<Record<string, unknown>>,
    props: { open: true, token: 'webhook-placeholder', onClose: () => {} },
    value: 'webhook-placeholder',
    toast: 'Token kopiert',
  },
  {
    name: 'EnrollTokenModal',
    component: EnrollTokenModal as unknown as Component<Record<string, unknown>>,
    props: { open: true, username: 'alice', onClose: () => {} },
    value: 'enroll-placeholder',
    toast: 'In Zwischenablage kopiert',
    prepare: async (view) => {
      await fireEvent.click(view.getByRole('button', { name: 'Ausstellen' }));
      await waitFor(() =>
        expect(view.container.querySelector('.key-reveal')?.textContent?.trim()).toBe(
          'enroll-placeholder',
        ),
      );
    },
  },
  {
    name: 'FrpConfigPreviewModal',
    component: FrpConfigPreviewModal as unknown as Component<Record<string, unknown>>,
    props: {
      open: true,
      title: 'frpc.toml',
      content: 'serverAddr = "frp.example"',
      onClose: () => {},
    },
    value: 'serverAddr = "frp.example"',
    toast: 'In Zwischenablage kopiert',
  },
];

beforeEach(() => {
  language.set('de');
  vi.mocked(mintEnrollToken).mockReset().mockResolvedValue(GRANT);
});

afterEach(() => {
  cleanup();
  for (const t of get(toasts)) dismissToast(t.id);
});

describe.each(cases)('$name copy button', (c) => {
  it('copies exactly the value shown and says so', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const view = render(c.component, { props: c.props }) as unknown as Shown;
    await c.prepare?.(view);

    await fireEvent.click(view.getByRole('button', { name: 'Kopieren' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith(c.value);
    await waitFor(() =>
      expect(get(toasts).map((t) => [t.kind, t.message])).toEqual([['success', c.toast]]),
    );
  });

  it('a refused copy says "copy failed"', async () => {
    const writeText = vi.fn(() => Promise.reject(new Error('denied')));
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const view = render(c.component, { props: c.props }) as unknown as Shown;
    await c.prepare?.(view);

    await fireEvent.click(view.getByRole('button', { name: 'Kopieren' }));

    await waitFor(() =>
      expect(get(toasts).map((t) => [t.kind, t.message])).toEqual([
        ['error', 'Kopieren fehlgeschlagen'],
      ]),
    );
  });
});
