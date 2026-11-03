// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The hooks page shows each hook's type, its triggers and an "active" switch. The switch posts
// the toggle and follows the server's answer; after a failed toggle it shows the old state
// again. An empty list shows the empty state, and "+ Hook" opens the dialog.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';

import Hooks from './Hooks.svelte';
import { language } from '$lib/i18n';
import type { Hook } from '$lib/api/types';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let list: Hook[];
let toggleOk: boolean;
let fetchMock: ReturnType<typeof vi.fn>;

function fetchStub(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/hooks') return Promise.resolve(json(list));
  const toggle = path.match(/^\/api\/hooks\/([^/]+)\/toggle$/);
  if (toggle && init?.method === 'POST') {
    if (!toggleOk) return Promise.resolve(json({ detail: 'nope' }, 400));
    const h = list.find((x) => x.id === toggle[1])!;
    return Promise.resolve(json({ ...h, enabled: !h.enabled }));
  }
  return Promise.resolve(json([]));
}

const hook = (id: string, type: Hook['hook_type'], enabled: boolean, extra: Partial<Hook> = {}) =>
  ({ id, name: `hook-${id}`, hook_type: type, enabled, ...extra }) as Hook;

function row(container: HTMLElement, name: string): HTMLElement {
  const tr = [...container.querySelectorAll<HTMLElement>('tbody tr')].find((r) =>
    r.textContent?.includes(name),
  );
  expect(tr, `no row ${name}`).toBeDefined();
  return tr as HTMLElement;
}

const toggleCalls = () =>
  fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/toggle')).length;

describe('Hooks page', () => {
  beforeEach(() => {
    language.set('de');
    toggleOk = true;
    fetchMock = vi.fn(fetchStub);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows type, triggers and the active switch per hook', async () => {
    list = [
      hook('a', 'webhook', true),
      hook('b', 'event', false, { event_triggers: ['server.created', 'user.deleted'] }),
    ];
    const { container, findByText } = render(Hooks);
    await findByText('hook-b');

    const a = within(row(container, 'hook-a'));
    expect(a.getByText('Webhook').closest('.pill-accent')).not.toBeNull();
    expect(a.getByRole('switch', { name: 'Aktiv' }).getAttribute('aria-checked')).toBe('true');
    expect(a.getByRole('button', { name: 'Token rotieren' })).toBeTruthy();

    const b = within(row(container, 'hook-b'));
    expect(b.getByText('Event').closest('.pill-warn')).not.toBeNull();
    expect(b.getByText('server.created')).toBeTruthy();
    expect(b.getByText('user.deleted')).toBeTruthy();
    expect(b.getByRole('switch', { name: 'Aktiv' }).getAttribute('aria-checked')).toBe('false');
    expect(b.queryByRole('button', { name: 'Token rotieren' })).toBeNull();
    expect(b.getByRole('button', { name: 'Löschen' })).toBeTruthy();
  });

  it('toggles a hook through the switch', async () => {
    list = [hook('a', 'schedule', false)];
    const { container, findByText } = render(Hooks);
    await findByText('hook-a');

    const sw = within(row(container, 'hook-a')).getByRole('switch');
    sw.focus();
    await fireEvent.click(sw);
    await vi.waitFor(() => expect(toggleCalls()).toBe(1));
    await vi.waitFor(() =>
      expect(
        within(row(container, 'hook-a')).getByRole('switch').getAttribute('aria-checked'),
      ).toBe('true'),
    );
    // The same element keeps the keyboard focus after the server's answer.
    // Let the toggle answer reach the store before checking the element.
    await fetchMock.mock.results.at(-1)!.value;
    await tick();
    await tick();
    expect(within(row(container, 'hook-a')).getByRole('switch')).toBe(sw);
    expect(document.activeElement).toBe(sw);
  });

  it('shows the old state again after a failed toggle', async () => {
    list = [hook('a', 'schedule', true)];
    toggleOk = false;
    const { container, findByText } = render(Hooks);
    await findByText('hook-a');

    await fireEvent.click(within(row(container, 'hook-a')).getByRole('switch'));
    await vi.waitFor(() => expect(toggleCalls()).toBe(1));
    await vi.waitFor(() =>
      expect(
        within(row(container, 'hook-a')).getByRole('switch').getAttribute('aria-checked'),
      ).toBe('true'),
    );
  });

  it('shows the empty state and opens the create dialog', async () => {
    list = [];
    const view = render(Hooks);
    await view.findByText('Keine Hooks vorhanden.');
    expect(view.container.querySelector('table')).toBeNull();

    await fireEvent.click(view.getByRole('button', { name: '+ Hook' }));
    const dialog = await view.findByRole('dialog');
    expect(dialog.textContent).toContain('Neuer Hook');
  });
});
