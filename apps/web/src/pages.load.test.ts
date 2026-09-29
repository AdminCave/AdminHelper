// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Page load test (R-0107).
 *
 * The four admin list pages load through the API on mount and read `.length` on
 * what comes back. A reload while that request is in flight cuts the response
 * body off; the client used to hand the page `null` for it, and the page died on
 * `.length` — the pageerror the live smoke found ("Cannot read properties of null
 * (reading 'length')"). mount.smoke.test.ts leaves the pages out on purpose
 * because they need an API stub; this is that stub, for the one failure mode that
 * matters here: a 2xx whose body cannot be read. Expected is a page that stays
 * standing — title, empty state — and says what went wrong in an error toast.
 *
 * Each case is a thunk, like in the mount smoke: one table type for four page
 * components would otherwise have to be `any`.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';

import Users from './pages/Users.svelte';
import ApiKeys from './pages/ApiKeys.svelte';
import Hooks from './pages/Hooks.svelte';
import Audit from './pages/Audit.svelte';
import { toasts, dismissToast } from '$lib/stores/notifications';

// A body that fails mid-read the way a reload leaves it: the stream errors with
// an AbortError after the 200 has already arrived.
function abortedBody(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.error(new DOMException('The operation was aborted.', 'AbortError'));
    },
  });
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'application/json' } });
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

const LIST_PATHS = ['/api/users', '/api/api-keys', '/api/hooks', '/api/audit'];

let unexpected: string[];
let errors: string[];

function fetchStub(input: RequestInfo | URL): Promise<Response> {
  const path = String(input).split('?')[0];
  if (LIST_PATHS.includes(path)) return Promise.resolve(abortedBody());
  if (path === '/api/auth/refresh') return Promise.resolve(json({ access_token: 'test-token' }));
  if (path === '/api/auth/me') return Promise.resolve(json({ id: 1, username: 'admin' }));
  // Anything else is a request this test did not plan for: recorded, and answered
  // with a valid empty list so it cannot be what makes a page fail.
  unexpected.push(path);
  return Promise.resolve(json([]));
}

const onError = (e: ErrorEvent) => errors.push(`error: ${String(e.error ?? e.message)}`);
const onRejection = (e: PromiseRejectionEvent) => errors.push(`rejection: ${String(e.reason)}`);

beforeEach(() => {
  unexpected = [];
  errors = [];
  vi.stubGlobal('fetch', vi.fn(fetchStub));
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    errors.push(`console.error: ${args.map(String).join(' ')}`);
  });
  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onRejection);
});

afterEach(() => {
  cleanup();
  window.removeEventListener('error', onError);
  window.removeEventListener('unhandledrejection', onRejection);
  for (const t of get(toasts)) dismissToast(t.id);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const PAGES: Array<{ name: string; mount: () => ReturnType<typeof render> }> = [
  { name: 'Users', mount: () => render(Users) },
  { name: 'ApiKeys', mount: () => render(ApiKeys) },
  { name: 'Hooks', mount: () => render(Hooks) },
  { name: 'Audit', mount: () => render(Audit) },
];

describe('admin pages with an unreadable list body', () => {
  for (const { name, mount } of PAGES) {
    it(`${name} stays standing and shows an error toast`, async () => {
      const { container } = mount();

      await waitFor(() => expect(get(toasts).map((t) => t.kind)).toContain('error'));

      expect(get(toasts).find((t) => t.kind === 'error')?.message).toBe('Invalid response body');
      expect(container.querySelector('.page-title'), `${name} has no title`).not.toBeNull();
      expect(container.querySelector('.empty-state'), `${name} has no empty state`).not.toBeNull();
      expect(errors, `${name} raised an error`).toEqual([]);
      expect(unexpected, `${name} made requests the stub does not know`).toEqual([]);
    });
  }
});
