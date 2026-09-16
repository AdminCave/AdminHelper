// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Mount smoke test (harness 8a, T15).
 *
 * 24 components, one mount test. A component that throws on mount — or loops in
 * an `$effect` that writes what it reads — is invisible to every other test in
 * this suite and shows up as a blank page in the browser.
 *
 * How a loop surfaces (measured, not assumed): Svelte raises
 * `effect_update_depth_exceeded` as a THROWN error out of `render()`, after
 * roughly twenty seconds of retrying. `expect(mount).not.toThrow()` is therefore
 * the guard, and MOUNT_TIMEOUT_MS is generous enough that the failure arrives as
 * that error rather than as a five-second test timeout. The console.error spy is
 * the second net: Svelte's dev diagnostics and any component-level logging land
 * there without throwing at all.
 *
 * Which ten: the shared primitives, the two layout pieces and three modals. The
 * seven pages are deliberately absent — each loads through its store on mount and
 * would need an API stub of its own, which is a different test with a different
 * failure mode. The primitives here are what every page composes.
 *
 * The list is explicit rather than a directory scan: each entry mounts with the
 * minimal props that component declares, and a scan would silently stop covering
 * anything that grows a required prop. Each entry is a thunk because one table
 * type for ten different prop types would have to be `any`.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';

import Button from '$lib/components/ui/Button.svelte';
import EmptyState from '$lib/components/ui/EmptyState.svelte';
import Modal from '$lib/components/ui/Modal.svelte';
import Toast from '$lib/components/ui/Toast.svelte';
import Router from '$lib/components/layout/Router.svelte';
import Sidebar from '$lib/components/layout/Sidebar.svelte';
import KeyRevealModal from '$modals/KeyRevealModal.svelte';
import WebhookTokenModal from '$modals/WebhookTokenModal.svelte';
import HookRunResultModal from '$modals/HookRunResultModal.svelte';
import Placeholder from './pages/Placeholder.svelte';

const text = (s: string) => createRawSnippet(() => ({ render: () => `<span>${s}</span>` }));
const noop = () => {};

// Svelte gives up on a runaway effect after ~20s; without this the failure would
// arrive as a bare 5s test timeout instead of the error that names the cause.
const MOUNT_TIMEOUT_MS = 30_000;

const CASES: Array<{ name: string; mount: () => void }> = [
  { name: 'ui/Button', mount: () => render(Button, { props: { children: text('ok') } }) },
  // Placeholder is the router's catch-all page and the one page with no store
  // load, so it belongs here rather than with the six that need stubs.
  { name: 'pages/Placeholder', mount: () => render(Placeholder) },
  {
    name: 'ui/EmptyState',
    mount: () => render(EmptyState, { props: { message: 'nothing here' } }),
  },
  {
    name: 'ui/Modal',
    mount: () =>
      render(Modal, { props: { open: true, title: 'T', onClose: noop, children: text('body') } }),
  },
  { name: 'ui/Toast', mount: () => render(Toast) },
  {
    name: 'layout/Router',
    // resolveRoute falls back to the '*' entry, so a table without one is not a
    // valid input — the router is mounted the way the app mounts it.
    mount: () => render(Router, { props: { routes: { '*': { component: Placeholder } } } }),
  },
  { name: 'layout/Sidebar', mount: () => render(Sidebar) },
  {
    name: 'modals/KeyRevealModal',
    mount: () =>
      render(KeyRevealModal, { props: { open: true, value: 'ah_secret', onClose: noop } }),
  },
  {
    name: 'modals/WebhookTokenModal',
    mount: () =>
      render(WebhookTokenModal, { props: { open: true, token: 'whk_1', onClose: noop } }),
  },
  {
    name: 'modals/HookRunResultModal',
    mount: () =>
      render(HookRunResultModal, {
        props: { open: true, hookName: 'h', result: null, onClose: noop },
      }),
  },
];

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('component mount smoke', () => {
  it('covers ten components', () => {
    expect(CASES).toHaveLength(10);
    expect(new Set(CASES.map((c) => c.name)).size).toBe(10);
    for (const c of CASES) expect(typeof c.mount, `${c.name} has no mount`).toBe('function');
  });

  for (const { name, mount } of CASES) {
    it(
      `mounts ${name} without errors`,
      () => {
        const errors: string[] = [];
        vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
          errors.push(args.map(String).join(' '));
        });

        expect(mount, `${name} threw on mount`).not.toThrow();
        expect(errors, `${name} logged to console.error on mount`).toEqual([]);
      },
      MOUNT_TIMEOUT_MS,
    );
  }
});
