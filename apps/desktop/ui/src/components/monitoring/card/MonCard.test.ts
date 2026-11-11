// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T4 (R-1225): the module card of the server page (concept §3.14).
// A green card is one line, a problem opens it; the admin's choice holds only for the
// status it was made at, so a card closed on a warning opens again when it turns
// critical. The note (why notifications are muted) shows open or closed. A card without
// a status of its own (the findings inbox) has no dot and opens as its caller says.

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import type { MonStatus } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import MonCard, { opensByDefault } from './MonCard.svelte';

const body = createRawSnippet(() => ({ render: () => '<p>BODY</p>' }));
const actions = createRawSnippet(() => ({
  render: () => '<button type="button">Zugangsdaten hinterlegen</button>',
}));

function props(status: MonStatus | null, extra: Record<string, unknown> = {}) {
  return { title: 'Nginx', status, summary: '3 Checks', children: body, ...extra };
}

beforeEach(() => setLanguage('de'));
afterEach(() => cleanup());

describe('opensByDefault', () => {
  it('opens a problem and keeps green and pending closed', () => {
    expect(opensByDefault('ok')).toBe(false);
    expect(opensByDefault('pending')).toBe(false);
    expect(opensByDefault('warning')).toBe(true);
    expect(opensByDefault('critical')).toBe(true);
    expect(opensByDefault('unknown')).toBe(true);
  });
});

describe('MonCard', () => {
  it('shows a green card as one closed line', () => {
    const { getByRole, getByText, queryByText, container } = render(MonCard, props('ok'));
    const toggle = getByRole('button', { name: /Nginx/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.hasAttribute('aria-controls')).toBe(false);
    expect(getByText('3 Checks')).toBeTruthy();
    expect(getByRole('img', { name: 'OK' })).toBeTruthy();
    expect(queryByText('BODY')).toBeNull();
    expect(container.querySelector('section')?.getAttribute('data-status')).toBe('ok');
  });

  it('opens a critical card and points the toggle at its body', () => {
    const { getByRole, getByText } = render(MonCard, props('critical'));
    const toggle = getByRole('button', { name: /Nginx/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const bodyEl = getByText('BODY').parentElement;
    expect(bodyEl?.id).toBeTruthy();
    expect(toggle.getAttribute('aria-controls')).toBe(bodyEl?.id);
    expect(getByRole('img', { name: 'Kritisch' })).toBeTruthy();
  });

  it('toggles open and closed', async () => {
    const { getByRole, queryByText } = render(MonCard, props('ok'));
    const toggle = getByRole('button', { name: /Nginx/ });
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(queryByText('BODY')).toBeTruthy();
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(queryByText('BODY')).toBeNull();
  });

  it('keeps a closed card closed while its status holds, and reopens it on a change', async () => {
    const { getByRole, queryByText, rerender } = render(MonCard, props('warning'));
    const toggle = getByRole('button', { name: /Nginx/ });
    await fireEvent.click(toggle);
    expect(queryByText('BODY')).toBeNull();

    await rerender(props('warning', { summary: '1 Warnung' }));
    expect(queryByText('BODY')).toBeNull();

    await rerender(props('critical', { summary: '1 Warnung' }));
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(queryByText('BODY')).toBeTruthy();
  });

  it('shows the note while closed and renders the actions beside the toggle', () => {
    const { getByText, getByRole, queryByText } = render(
      MonCard,
      props('ok', { note: 'Wartungsfenster — Meldungen unterdrückt', actions }),
    );
    expect(getByText('Wartungsfenster — Meldungen unterdrückt')).toBeTruthy();
    expect(queryByText('BODY')).toBeNull();
    expect(getByRole('button', { name: 'Zugangsdaten hinterlegen' })).toBeTruthy();
  });

  it('shows no dot without a status and opens as asked', async () => {
    const { getByRole, queryByRole, queryByText, container } = render(
      MonCard,
      props(null, { defaultOpen: true }),
    );
    const toggle = getByRole('button', { name: /Nginx/ });
    expect(queryByRole('img')).toBeNull();
    expect(container.querySelector('section')?.hasAttribute('data-status')).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    await fireEvent.click(toggle);
    expect(queryByText('BODY')).toBeNull();
  });

  it('lets defaultOpen close a problem card', () => {
    const { getByRole } = render(MonCard, props('critical', { defaultOpen: false }));
    expect(getByRole('button', { name: /Nginx/ }).getAttribute('aria-expanded')).toBe('false');
  });
});
