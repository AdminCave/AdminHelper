// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The notifications page (R-1531): the panel's delivery settings with the .env value for each
// empty field, password and token write-only (empty keeps, the clear box deletes), a warning for
// secrets the SECRET_KEY no longer opens, and a test message per channel.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';

import Notifications from './Notifications.svelte';
import { language } from '$lib/i18n';
import type { NotifyChannels } from '$lib/api/types';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function channels(extra: Partial<NotifyChannels> = {}): NotifyChannels {
  return {
    smtpHost: null,
    smtpPort: null,
    smtpUser: null,
    smtpFrom: null,
    privateTargets: null,
    passwordSet: false,
    tokenSet: false,
    sources: {
      smtp_host: 'env',
      smtp_port: 'env',
      smtp_user: 'none',
      smtp_password: 'none',
      smtp_from: 'env',
      telegram_token: 'none',
      private_targets: 'env',
    },
    unreadable: [],
    effective: {
      smtpHost: 'relay.example',
      smtpPort: 587,
      smtpUser: '',
      smtpFrom: 'hub@example.com',
      privateTargets: ['192.0.2.0/24'],
    },
    updatedAt: null,
    updatedBy: null,
    ...extra,
  };
}

let current: NotifyChannels;
let fetchMock: ReturnType<typeof vi.fn>;

function fetchStub(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/admin/notify/channels' && (init?.method ?? 'GET') === 'GET')
    return Promise.resolve(json(current));
  if (path === '/api/admin/notify/channels' && init?.method === 'PUT')
    return Promise.resolve(json(current));
  if (path === '/api/admin/notify/channels/test' && init?.method === 'POST')
    return Promise.resolve(json({ channel: 'email' }));
  return Promise.resolve(json({}, 404));
}

function bodyOf(path: string, method: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input).split('?')[0] === path && init?.method === method,
  );
  expect(call, `no ${method} ${path}`).toBeDefined();
  return JSON.parse(String(call![1]!.body)) as Record<string, unknown>;
}

describe('Notifications page, channels', () => {
  beforeEach(() => {
    language.set('de');
    current = channels();
    fetchMock = vi.fn(fetchStub);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('names the .env value for each field the panel leaves empty', async () => {
    const view = render(Notifications);
    await view.findByLabelText('SMTP-Host');

    expect(view.getByText('Leer: aus .env – relay.example')).toBeTruthy();
    expect(view.getByText('Leer: aus .env – 587')).toBeTruthy();
    expect(view.getByText('Leer: aus .env – hub@example.com')).toBeTruthy();
    // The user is not in the panel and not in the .env.
    expect(view.getAllByText('Leer: nicht gesetzt').length).toBeGreaterThan(0);
    expect(view.container.textContent).toContain('192.0.2.0/24');
    // Nothing stored: no clear box, no warning.
    expect(view.queryByText('Gespeicherten Wert löschen')).toBeNull();
    expect(view.queryByRole('alert')).toBeNull();
  });

  it('shows a stored password as stored and never fills it in', async () => {
    current = channels({
      smtpHost: 'mail.example',
      passwordSet: true,
      sources: { ...channels().sources, smtp_host: 'panel', smtp_password: 'panel' },
    });
    const view = render(Notifications);
    const pw = (await view.findByLabelText('SMTP-Passwort')) as HTMLInputElement;

    expect(pw.type).toBe('password');
    expect(pw.value).toBe('');
    expect(pw.placeholder).toBe('gespeichert – leer lassen zum Behalten');
    expect((view.getByLabelText('SMTP-Host') as HTMLInputElement).value).toBe('mail.example');
    expect(view.getAllByText('Gespeicherten Wert löschen')).toHaveLength(1);
  });

  it('keeps the stored secrets when their fields stay empty', async () => {
    // The host stays as stored: a new host would drop the password on the server.
    current = channels({ smtpHost: 'mail.example', passwordSet: true, tokenSet: true });
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('SMTP-Port'), { target: { value: ' 465 ' } });
    await fireEvent.click(view.getByRole('button', { name: 'Speichern' }));

    await vi.waitFor(() =>
      expect(bodyOf('/api/admin/notify/channels', 'PUT')).toEqual({
        smtpHost: 'mail.example',
        smtpPort: 465,
        smtpUser: null,
        smtpFrom: null,
        privateTargets: null,
        smtpPassword: null,
        telegramToken: null,
      }),
    );
  });

  it('sends a new password and deletes the token through its clear box', async () => {
    current = channels({ passwordSet: true, tokenSet: true });
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('SMTP-Passwort'), {
      target: { value: 's3cret' },
    });
    const boxes = view.getAllByRole('checkbox', { name: 'Gespeicherten Wert löschen' });
    expect(boxes).toHaveLength(2);
    await fireEvent.click(boxes[1]);
    expect((view.getByLabelText('Telegram-Bot-Token') as HTMLInputElement).disabled).toBe(true);
    await fireEvent.click(view.getByRole('button', { name: 'Speichern' }));

    await vi.waitFor(() => {
      const body = bodyOf('/api/admin/notify/channels', 'PUT');
      expect(body.smtpPassword).toBe('s3cret');
      expect(body.telegramToken).toBe('');
    });
    // After the answer the secret fields are empty again.
    await vi.waitFor(() =>
      expect((view.getByLabelText('SMTP-Passwort') as HTMLInputElement).value).toBe(''),
    );
  });

  it('warns that a new host drops the stored password', async () => {
    current = channels({ smtpHost: 'mail.example', passwordSet: true });
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('SMTP-Host'), {
      target: { value: 'other.example' },
    });
    expect(
      view.getByText('Ein neuer Host ohne neues Passwort verwirft das gespeicherte Passwort.'),
    ).toBeTruthy();
  });

  it('refuses a port outside 1..65535 without asking the server', async () => {
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('SMTP-Port'), { target: { value: '70000' } });

    expect(view.getByText('Port: eine Zahl von 1 bis 65535')).toBeTruthy();
    const save = view.getByRole('button', { name: 'Speichern' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await fireEvent.submit(save.closest('form')!);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);
  });

  it('warns about secrets the SECRET_KEY no longer opens', async () => {
    current = channels({ unreadable: ['smtp_password', 'telegram_token'] });
    const view = render(Notifications);
    const alert = await view.findByRole('alert');
    expect(alert.textContent).toContain('SMTP-Passwort, Telegram-Bot-Token');
    expect(alert.textContent).toContain('SECRET_KEY');
  });

  it('says so when the settings cannot be loaded', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'boom' }, 500)));
    const view = render(Notifications);
    expect(await view.findByText('Die Einstellungen ließen sich nicht laden.')).toBeTruthy();
    expect(view.queryByText('Lädt …')).toBeNull();
  });

  it('sends a test message to the target given', async () => {
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('Ziel'), {
      target: { value: ' ops@example.com ' },
    });
    await fireEvent.click(view.getByRole('button', { name: 'Test senden' }));

    await vi.waitFor(() =>
      expect(bodyOf('/api/admin/notify/channels/test', 'POST')).toEqual({
        channel: 'email',
        target: 'ops@example.com',
      }),
    );
  });
});
