// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The person's notification editor: the categories round-trip of the rules (H2), the
// error paths, the channel settings of R-1080 (targets, test button, matrix, muted
// categories), and quiet hours, escalation, digest and tone of R-1081.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import { IpcError } from '$lib/utils/errors';
import type { NotificationPrefs as Prefs } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchPrefs: vi.fn(),
  savePrefs: vi.fn(async (..._a: unknown[]): Promise<unknown> => ({
    email: null,
    telegramChatId: null,
    subscriptions: [],
  })),
  testChannel: vi.fn(async (..._a: unknown[]): Promise<unknown> => ({ channel: 'ntfy' })),
  fetchServers: vi.fn(async () => []),
  showNotice: vi.fn(),
  notifyOs: vi.fn(async (..._a: unknown[]) => {}),
  setDesktopPrefs: vi.fn(),
  osNotifications: false,
}));
vi.mock('$lib/api/notifications', () => ({
  notificationsApi: {
    fetchPrefs: h.fetchPrefs,
    savePrefs: h.savePrefs,
    testChannel: h.testChannel,
  },
}));
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { fetchServers: h.fetchServers },
}));
vi.mock('$lib/stores/statusBar', () => ({ showNotice: h.showNotice }));
vi.mock('$lib/osNotify', () => ({ notifyOs: h.notifyOs }));
vi.mock('$lib/stores/notifyPrefs', () => ({ setDesktopPrefs: h.setDesktopPrefs }));
vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return {
    session: readable({
      serverUrl: 'https://t',
      username: 'a',
      isAdmin: true,
    }),
    settings: {
      subscribe: (fn: (v: { osNotifications: boolean }) => void) => {
        fn({ osNotifications: h.osNotifications });
        return () => {};
      },
    },
  };
});

import NotificationPrefs from './NotificationPrefs.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  h.osNotifications = false;
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

describe('NotificationPrefs — save error path', () => {
  it('surfaces an error message when savePrefs rejects, without crashing', async () => {
    // The replace-all PUT can fail (network, 4xx); the editor must show the error, not throw and leave
    // the user with a half-saved silent failure (6.114).
    h.fetchPrefs.mockResolvedValueOnce({
      email: 'a@b.de',
      telegramChatId: null,
      subscriptions: [],
    });
    h.savePrefs.mockRejectedValueOnce(new Error('server down'));

    const { findByText } = render(NotificationPrefs);
    const saveBtn = await findByText('Benachrichtigungen speichern');
    await fireEvent.click(saveBtn);

    await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
    // The rejection is caught and rendered as the error span, not thrown.
    await findByText(/server down/);
  });
});

// R-0261: a network error from the backend carries the ERR_* codes in its source chain
// (error.rs); they are for the code, the editor shows the prose.
const PIN_MISMATCH =
  'error sending request: client error (Connect): ' +
  'ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für t hat sich geändert';
const PROSE =
  'error sending request: client error (Connect): ' +
  'AdminHelper TOFU: Das Server-Zertifikat für t hat sich geändert';

describe('NotificationPrefs — errors without the machine codes (R-0261)', () => {
  it('shows a failed load as prose', async () => {
    h.fetchPrefs.mockRejectedValueOnce(PIN_MISMATCH);

    const { container } = render(NotificationPrefs);

    await waitFor(() => expect(container.querySelector('.np-err')).not.toBeNull());
    expect(container.querySelector('.np-err')?.textContent).toBe(PROSE);
  });

  it('shows a failed save as prose', async () => {
    h.fetchPrefs.mockResolvedValueOnce({
      email: 'a@b.de',
      telegramChatId: null,
      subscriptions: [],
    });
    h.savePrefs.mockRejectedValueOnce(PIN_MISMATCH);

    const { container, findByText } = render(NotificationPrefs);
    await fireEvent.click(await findByText('Benachrichtigungen speichern'));

    await waitFor(() => expect(container.querySelector('.np-err')).not.toBeNull());
    expect(container.querySelector('.np-err')?.textContent).toBe(PROSE);
  });
});

const NTFY = 'https://ntfy.example/alerts?auth=SECRETAUTH';

const prefs = (over: Partial<Prefs> = {}): Prefs => ({
  email: 'a@b.de',
  telegramChatId: null,
  ntfyUrl: NTFY,
  webhookUrl: null,
  matrix: {
    critical: ['desktop', 'email'],
    warning: ['desktop'],
    info: ['desktop'],
    ok: ['desktop'],
  },
  disabledChannels: [],
  mutedCategories: [],
  available: { desktop: true, email: true, ntfy: true, telegram: false, webhook: true },
  subscriptions: [],
  ...over,
});

const row = (c: HTMLElement, ch: string): HTMLElement => {
  const el = c.querySelector<HTMLElement>(`.np-channel[data-channel="${ch}"]`);
  if (!el) throw new Error(`no row ${ch}`);
  return el;
};
const testBtn = (c: HTMLElement, ch: string): HTMLButtonElement | null =>
  [...row(c, ch).querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Test') ?? null;

describe('NotificationPrefs — channel settings (R-1080)', () => {
  it('shows the stored targets, the URLs masked', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs({ webhookUrl: 'https://hooks.example/SECRET' }));
    const { container, findByLabelText } = render(NotificationPrefs);
    const ntfy = (await findByLabelText('ntfy-Topic-URL')) as HTMLInputElement;
    expect([ntfy.type, ntfy.value]).toEqual(['password', NTFY]);
    const hook = (await findByLabelText('Webhook-URL')) as HTMLInputElement;
    expect(hook.type).toBe('password');
    const chat = (await findByLabelText('Telegram-Chat-ID')) as HTMLInputElement;
    expect(chat.type).toBe('text');
    expect(container.querySelectorAll('.np-channel')).toHaveLength(5);
  });

  it('saves targets, matrix, switches and muted categories in one PUT', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText, getByLabelText, getByText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');

    await fireEvent.input(getByLabelText('Webhook-URL'), {
      target: { value: ' https://hooks.example/x ' },
    });
    await fireEvent.click(getByLabelText('Warnung an E-Mail'));
    await fireEvent.click(getByLabelText('Erledigt an Desktop'));
    const ntfySwitch = row(container, 'ntfy').querySelector<HTMLElement>('[role="switch"]');
    if (!ntfySwitch) throw new Error('no switch');
    await fireEvent.click(ntfySwitch);
    await fireEvent.click(getByText('Tunnel'));
    await fireEvent.click(getByText('Benachrichtigungen speichern'));

    await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
    expect(h.savePrefs.mock.calls[0][1]).toEqual({
      email: 'a@b.de',
      telegram_chat_id: null,
      ntfy_url: NTFY,
      webhook_url: 'https://hooks.example/x',
      matrix: {
        critical: ['desktop', 'email'],
        warning: ['desktop', 'email'],
        info: ['desktop'],
        ok: [],
      },
      disabled_channels: ['ntfy'],
      muted_categories: ['tunnel'],
      subscriptions: [],
    });
  });

  it('hands the saved settings to the desktop pop-ups', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const saved = prefs({ mutedCategories: ['agent'] });
    h.savePrefs.mockResolvedValueOnce(saved);
    const { findByText } = render(NotificationPrefs);
    await fireEvent.click(await findByText('Benachrichtigungen speichern'));
    await waitFor(() => expect(h.setDesktopPrefs).toHaveBeenCalledWith(saved));
  });

  it('a muted category shows as not pressed, a switched-off channel greys its column', async () => {
    h.fetchPrefs.mockResolvedValueOnce(
      prefs({ mutedCategories: ['security'], disabledChannels: ['email'] }),
    );
    const { findByText, getByLabelText } = render(NotificationPrefs);
    expect((await findByText('Sicherheit')).getAttribute('aria-pressed')).toBe('false');
    expect((await findByText('Monitoring')).getAttribute('aria-pressed')).toBe('true');
    expect((getByLabelText('Kritisch an E-Mail') as HTMLInputElement).disabled).toBe(true);
    expect((getByLabelText('Kritisch an E-Mail') as HTMLInputElement).checked).toBe(true);
  });

  it('the test button sends to the stored target and says so', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    const btn = testBtn(container, 'ntfy');
    if (!btn) throw new Error('no test button');
    await fireEvent.click(btn);
    await waitFor(() => expect(row(container, 'ntfy').querySelector('.np-ok')).not.toBeNull());
    expect(h.testChannel).toHaveBeenCalledWith(expect.anything(), 'ntfy');
    expect(row(container, 'ntfy').querySelector('.np-ok')?.textContent?.trim()).toBe(
      'Test gesendet',
    );
  });

  it.each([
    [409, 'ntfy: no target stored'],
    [422, 'ntfy: target address not allowed'],
    [429, 'ntfy: wait a few seconds before the next test'],
    [502, 'ntfy: HTTP 500'],
  ])('a refused test (%i) shows the server text at the channel', async (status, text) => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    h.testChannel.mockRejectedValueOnce(new IpcError(text, undefined, status));
    const { container, findByText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    const btn = testBtn(container, 'ntfy');
    if (!btn) throw new Error('no test button');
    await fireEvent.click(btn);
    await waitFor(() => expect(row(container, 'ntfy').querySelector('.np-err')).not.toBeNull());
    expect(row(container, 'ntfy').querySelector('.np-err')?.textContent?.trim()).toBe(text);
  });

  it('an unsaved target locks its test until it is saved', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText, getByLabelText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    await fireEvent.input(getByLabelText('ntfy-Topic-URL'), {
      target: { value: 'https://ntfy.example/other' },
    });
    const btn = testBtn(container, 'ntfy');
    expect(btn?.disabled).toBe(true);
    expect(btn?.title).toBe('Erst speichern, dann testen');
    expect(testBtn(container, 'email')?.disabled).toBe(false);
  });

  it('a channel the server cannot deliver says so instead of a test button', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    expect(testBtn(container, 'telegram')).toBeNull();
    expect(row(container, 'telegram').textContent).toContain(
      'Auf diesem Server nicht eingerichtet',
    );
  });

  it('the desktop tests itself: a toast, and the OS notice when opted in', async () => {
    h.osNotifications = true;
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    const btn = testBtn(container, 'desktop');
    if (!btn) throw new Error('no test button');
    await fireEvent.click(btn);
    await waitFor(() => expect(row(container, 'desktop').querySelector('.np-ok')).not.toBeNull());
    expect(h.testChannel).not.toHaveBeenCalled();
    expect(h.showNotice).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'AdminHelper-Test', tone: 'info' }),
    );
    expect(h.notifyOs).toHaveBeenCalledTimes(1);
  });

  it('without the OS opt-in the desktop test is the toast only', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    const btn = testBtn(container, 'desktop');
    if (!btn) throw new Error('no test button');
    await fireEvent.click(btn);
    await waitFor(() => expect(h.showNotice).toHaveBeenCalled());
    expect(h.notifyOs).not.toHaveBeenCalled();
  });

  it('settings from a server before the matrix load with the desktop default', async () => {
    h.fetchPrefs.mockResolvedValueOnce({ email: null, telegramChatId: null, subscriptions: [] });
    const { findByText, getByLabelText } = render(NotificationPrefs);
    await findByText('Benachrichtigungen speichern');
    expect((getByLabelText('Info an Desktop') as HTMLInputElement).checked).toBe(true);
    expect((getByLabelText('Info an E-Mail') as HTMLInputElement).checked).toBe(false);
  });
});

describe('NotificationPrefs — quiet, escalation & digest (R-1081)', () => {
  const calm = (over: Partial<Prefs> = {}): Prefs =>
    prefs({
      timezone: 'Europe/Berlin',
      quiet: { enabled: true, start: '23:00', end: '06:30', critical: false },
      escalation: { enabled: true, minutes: 30, channel: 'ntfy' },
      digest: 'weekly',
      soundCritical: true,
      ...over,
    });
  const section = (c: HTMLElement, name: string): HTMLElement => {
    const el = c.querySelector<HTMLElement>(`.np-row[data-row="${name}"]`);
    if (!el) throw new Error(`no row ${name}`);
    return el;
  };
  const toggle = (c: HTMLElement, name: string): HTMLButtonElement => {
    const el = section(c, name).querySelector<HTMLButtonElement>('[role="switch"]');
    if (!el) throw new Error(`no switch ${name}`);
    return el;
  };

  it('loads the stored values', async () => {
    h.fetchPrefs.mockResolvedValueOnce(calm());
    const { container, findByLabelText, getByLabelText, getByText } = render(NotificationPrefs);
    expect(((await findByLabelText('Ruhezeit ab')) as HTMLInputElement).value).toBe('23:00');
    expect((getByLabelText('Ruhezeit bis') as HTMLInputElement).value).toBe('06:30');
    expect(toggle(container, 'quiet').getAttribute('aria-checked')).toBe('true');
    expect(toggle(container, 'pass').getAttribute('aria-checked')).toBe('false');
    expect(toggle(container, 'escalation').getAttribute('aria-checked')).toBe('true');
    expect(toggle(container, 'sound').getAttribute('aria-checked')).toBe('true');
    expect(
      (
        getByLabelText('Frist der Eskalation') as HTMLSelectElement
      ).selectedOptions[0].textContent?.trim(),
    ).toBe('nach 30 Min.');
    expect((getByLabelText('Kanal der Eskalation') as HTMLSelectElement).value).toBe('ntfy');
    expect(getByText('Wöchentlich').getAttribute('aria-pressed')).toBe('true');
  });

  it('saves the fields with the zone of this machine', async () => {
    h.fetchPrefs.mockResolvedValueOnce(calm());
    const { container, findByLabelText, getByLabelText, getByText } = render(NotificationPrefs);
    await fireEvent.input(await findByLabelText('Ruhezeit ab'), { target: { value: '21:15' } });
    await fireEvent.click(toggle(container, 'pass'));
    await fireEvent.change(getByLabelText('Frist der Eskalation'), { target: { value: '5' } });
    await fireEvent.change(getByLabelText('Kanal der Eskalation'), { target: { value: 'email' } });
    await fireEvent.click(toggle(container, 'sound'));
    await fireEvent.click(getByText('Täglich'));
    await fireEvent.click(getByText('Benachrichtigungen speichern'));

    await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
    const body = h.savePrefs.mock.calls[0][1] as Record<string, unknown>;
    expect({
      timezone: body.timezone,
      quiet: body.quiet,
      escalation: body.escalation,
      digest: body.digest,
      sound_critical: body.sound_critical,
    }).toEqual({
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      quiet: { enabled: true, start: '21:15', end: '06:30', critical: true },
      escalation: { enabled: true, minutes: 5, channel: 'email' },
      digest: 'daily',
      sound_critical: false,
    });
  });

  it('saves without a zone the server cannot know (R-1184)', async () => {
    const zone = vi
      .spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions')
      .mockReturnValue({ timeZone: 'Etc/Unknown' } as Intl.ResolvedDateTimeFormatOptions);
    try {
      h.fetchPrefs.mockResolvedValueOnce(calm());
      const { findByText } = render(NotificationPrefs);
      await fireEvent.click(await findByText('Benachrichtigungen speichern'));
      await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
      const body = h.savePrefs.mock.calls[0][1] as Record<string, unknown>;
      expect('timezone' in body).toBe(false);
      expect(body.quiet).toEqual({ enabled: true, start: '23:00', end: '06:30', critical: false });
    } finally {
      zone.mockRestore();
    }
  });

  it('a cleared quiet time saves the stored one (R-1184)', async () => {
    h.fetchPrefs.mockResolvedValueOnce(calm());
    const { findByLabelText, getByLabelText, getByText } = render(NotificationPrefs);
    await fireEvent.input(await findByLabelText('Ruhezeit ab'), { target: { value: '' } });
    await fireEvent.input(getByLabelText('Ruhezeit bis'), { target: { value: '' } });
    await fireEvent.click(getByText('Benachrichtigungen speichern'));
    await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
    const body = h.savePrefs.mock.calls[0][1] as Record<string, unknown>;
    expect(body.quiet).toEqual({ enabled: true, start: '23:00', end: '06:30', critical: false });
  });

  it('a channel without a stored target, switched off or not set up cannot be picked', async () => {
    h.fetchPrefs.mockResolvedValueOnce(
      calm({ telegramChatId: '4711', webhookUrl: null, disabledChannels: ['email'] }),
    );
    const { findByLabelText, getByText } = render(NotificationPrefs);
    const select = (await findByLabelText('Kanal der Eskalation')) as HTMLSelectElement;
    const off = Object.fromEntries([...select.options].map((o) => [o.value, o.disabled]));
    // telegram has a chat id but is not set up on this server (available.telegram false).
    expect(off).toEqual({ '': true, email: true, ntfy: false, telegram: true, webhook: true });
    expect(getByText(/sind nicht wählbar/)).toBeTruthy();
  });

  it('the escalation cannot be switched on before a channel is picked', async () => {
    h.fetchPrefs.mockResolvedValueOnce(
      calm({ escalation: { enabled: false, minutes: 10, channel: null } }),
    );
    const { container, findByLabelText } = render(NotificationPrefs);
    const select = (await findByLabelText('Kanal der Eskalation')) as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(toggle(container, 'escalation').disabled).toBe(true);
    await fireEvent.change(select, { target: { value: 'ntfy' } });
    expect(toggle(container, 'escalation').disabled).toBe(false);
  });

  it('a server before them shows no section and gets none of the fields', async () => {
    h.fetchPrefs.mockResolvedValueOnce(prefs());
    const { container, findByText, queryByText } = render(NotificationPrefs);
    await fireEvent.click(await findByText('Benachrichtigungen speichern'));
    expect(queryByText('Ruhezeiten')).toBeNull();
    expect(container.querySelector('.np-row')).toBeNull();
    await waitFor(() => expect(h.savePrefs).toHaveBeenCalled());
    const body = h.savePrefs.mock.calls[0][1] as Record<string, unknown>;
    expect(
      ['timezone', 'quiet', 'escalation', 'digest', 'sound_critical'].filter((k) => k in body),
    ).toEqual([]);
  });
});
