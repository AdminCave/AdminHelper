// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The reconnect button of the tunnel indicator: it shows only while the tunnel is
// disconnected, so no click can drop the sessions of a connected one, and a click
// waits for its reconnection before the next one starts another. The tunnel store is
// a writable here, so a state change reaches the mounted component as in the app.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import { setLanguage } from '$lib/i18n';
import type { TunnelUiState } from '$lib/stores/tunnel';

vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return {
    sessionStore: readable({
      settings: { mode: 'server', url: null, intervalMinutes: 5 },
      session: { username: 'admin', serverUrl: 'https://example.invalid' },
      ready: true,
    }),
  };
});
const h = vi.hoisted(() => ({
  reconnectNow: vi.fn(),
  reconnectResult: (): Promise<void> => Promise.resolve(),
}));
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return {
    tunnel: writable({ ui: 'idle', status: null, mappings: [] }),
    // A plain function around the spy: vi.fn handles every promise it returns itself,
    // which would hide a rejection the button leaves unhandled.
    reconnectNow: (): Promise<void> => {
      h.reconnectNow();
      return h.reconnectResult();
    },
  };
});

import TunnelIndicator from './TunnelIndicator.svelte';
import { tunnel } from '$lib/stores/tunnel';

type MockState = { ui: TunnelUiState; status: null; mappings: never[] };
const tunnelState = tunnel as unknown as Writable<MockState>;

function reconnectButton(container: HTMLElement): HTMLButtonElement | null {
  return container.querySelector<HTMLButtonElement>('button');
}

async function showUi(ui: TunnelUiState): Promise<void> {
  tunnelState.set({ ui, status: null, mappings: [] });
  await tick();
}

/** A reconnection the test settles by hand. */
function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve = (): void => {};
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

setLanguage('de');
afterEach(async () => {
  cleanup();
  vi.clearAllMocks();
  h.reconnectResult = () => Promise.resolve();
  await showUi('idle');
});

describe('TunnelIndicator — reconnect button', () => {
  it('shows the button only while the tunnel is disconnected', async () => {
    await showUi('disconnected');
    const { container, getByText } = render(TunnelIndicator);
    getByText('Tunnel getrennt');
    expect(reconnectButton(container)?.textContent?.trim()).toBe('Neu verbinden');
  });

  it.each<TunnelUiState>(['connected', 'connecting', 'idle'])(
    'shows no button while the tunnel is %s',
    async (ui) => {
      await showUi(ui);
      const { container } = render(TunnelIndicator);
      expect(container.querySelector('.tunnel-indicator')).not.toBeNull();
      expect(reconnectButton(container)).toBeNull();
    },
  );

  it('a click calls reconnectNow exactly once', async () => {
    await showUi('disconnected');
    const { getByRole } = render(TunnelIndicator);
    await fireEvent.click(getByRole('button', { name: 'Neu verbinden' }));
    expect(h.reconnectNow).toHaveBeenCalledTimes(1);
  });

  it('is disabled while its click runs, and clickable again once it settled', async () => {
    const run = deferred();
    h.reconnectResult = () => run.promise;
    await showUi('disconnected');
    const { getByRole } = render(TunnelIndicator);
    const button = getByRole('button', { name: 'Neu verbinden' }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    await fireEvent.click(button);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    await fireEvent.click(button);
    expect(h.reconnectNow).toHaveBeenCalledTimes(1);

    run.resolve();
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(button.getAttribute('aria-busy')).not.toBe('true');
    await fireEvent.click(button);
    expect(h.reconnectNow).toHaveBeenCalledTimes(2);
  });

  it('goes away when the tunnel connects and is clickable when it disconnects again', async () => {
    const first = deferred();
    h.reconnectResult = () => first.promise;
    await showUi('disconnected');
    const { container, getByRole } = render(TunnelIndicator);
    const button = getByRole('button', { name: 'Neu verbinden' }) as HTMLButtonElement;
    await fireEvent.click(button);
    expect(button.disabled).toBe(true);

    await showUi('connected');
    expect(reconnectButton(container)).toBeNull();
    // frpc ended again before the first click's reconnection settled.
    await showUi('disconnected');
    const again = getByRole('button', { name: 'Neu verbinden' }) as HTMLButtonElement;
    expect(again.disabled).toBe(false);

    const second = deferred();
    h.reconnectResult = () => second.promise;
    await fireEvent.click(again);
    expect(h.reconnectNow).toHaveBeenCalledTimes(2);
    // The first click settling does not end the wait of the second.
    first.resolve();
    await first.promise;
    await tick();
    expect(again.disabled).toBe(true);
    second.resolve();
    await waitFor(() => expect(again.disabled).toBe(false));
  });
});
