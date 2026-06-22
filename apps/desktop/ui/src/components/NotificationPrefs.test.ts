// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Regression for the categories round-trip: the prefs editor does not expose a
// categories filter, but the PUT is replace-all — so a filter set via another
// client must survive load → save instead of being silently wiped (H2).

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';

const h = vi.hoisted(() => ({
  fetchPrefs: vi.fn(),
  savePrefs: vi.fn(async (..._a: unknown[]) => ({
    email: null,
    telegramChatId: null,
    subscriptions: [],
  })),
  fetchServers: vi.fn(async () => []),
}));
vi.mock('$lib/api/notifications', () => ({
  notificationsApi: { fetchPrefs: h.fetchPrefs, savePrefs: h.savePrefs },
}));
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { fetchServers: h.fetchServers },
}));
vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return {
    session: readable({
      serverUrl: 'https://t',
      token: 't',
      refreshToken: 'r',
      username: 'a',
      isAdmin: true,
    }),
  };
});

import NotificationPrefs from './NotificationPrefs.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('NotificationPrefs — categories round-trip', () => {
  it('preserves a categories filter through load → save', async () => {
    h.fetchPrefs.mockResolvedValueOnce({
      email: 'a@b.de',
      telegramChatId: null,
      subscriptions: [
        {
          id: 1,
          userId: 1,
          scopeType: 'all',
          scopeRef: null,
          minSeverity: 'warning',
          categories: '["pki"]',
          channelEmail: true,
          channelTelegram: false,
          enabled: true,
        },
      ],
    });

    const { findByText } = render(NotificationPrefs);
    const saveBtn = await findByText('Benachrichtigungen speichern');
    await fireEvent.click(saveBtn);

    await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
    const payload = h.savePrefs.mock.calls[0][1] as {
      subscriptions: { categories: string[] | null }[];
    };
    expect(payload.subscriptions[0].categories).toEqual(['pki']);
  });
});
