// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The notifications page (R-1531): the panel's delivery settings with the .env value for each
// empty field, password and token write-only (empty keeps, the clear box deletes), a warning for
// secrets the SECRET_KEY no longer opens, and a test message per channel.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const confirmMock = vi.hoisted(() => vi.fn(() => Promise.resolve(true)));
vi.mock('$lib/components/ui/ConfirmDialog.svelte', () => ({ confirmDialog: confirmMock }));
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';

import Notifications from './Notifications.svelte';
import { language } from '$lib/i18n';
import type { NotifyChannels, NotifyTemplate, NotifyTemplatePreview } from '$lib/api/types';

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

function template(extra: Partial<NotifyTemplate> = {}): NotifyTemplate {
  return {
    subjectPrefix: '',
    fromName: '',
    html: '',
    text: '',
    logoSet: false,
    logoType: null,
    placeholders: ['title', 'body', 'severity', 'category', 'time', 'source', 'logo'],
    updatedAt: null,
    updatedBy: null,
    ...extra,
  };
}

let current: NotifyChannels;
let currentTemplate: NotifyTemplate;
let previewAnswer: NotifyTemplatePreview;
let fetchMock: ReturnType<typeof vi.fn>;

function fetchStub(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/admin/notify/channels' && (init?.method ?? 'GET') === 'GET')
    return Promise.resolve(json(current));
  if (path === '/api/admin/notify/channels' && init?.method === 'PUT')
    return Promise.resolve(json(current));
  if (path === '/api/admin/notify/channels/test' && init?.method === 'POST')
    return Promise.resolve(json({ channel: 'email' }));
  if (path === '/api/admin/notify/template') {
    if (init?.method === 'DELETE') currentTemplate = template();
    return Promise.resolve(json(currentTemplate));
  }
  if (path === '/api/admin/notify/template/preview' && init?.method === 'POST')
    return Promise.resolve(json(previewAnswer));
  if (path === '/api/admin/notify/template/test' && init?.method === 'POST')
    return Promise.resolve(json({ channel: 'email' }));
  if (path === '/api/admin/notify/template/logo') {
    currentTemplate = template({
      logoSet: init?.method === 'PUT',
      logoType: init?.method === 'PUT' ? 'image/png' : null,
    });
    return Promise.resolve(json(currentTemplate));
  }
  return Promise.resolve(json({}, 404));
}

// The page has two forms with a save and two with a send button: scope a query to one.
function section(view: { container: HTMLElement }, name: string) {
  return within(view.container.querySelector(`form[data-section="${name}"]`) as HTMLElement);
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
    currentTemplate = template();
    previewAnswer = { subject: 'Disk full', fromName: '', text: 'Disk full', html: null };
    confirmMock.mockClear();
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
    await fireEvent.click(section(view, 'channels').getByRole('button', { name: 'Speichern' }));

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
    await fireEvent.click(section(view, 'channels').getByRole('button', { name: 'Speichern' }));

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
    const save = section(view, 'channels').getByRole('button', {
      name: 'Speichern',
    }) as HTMLButtonElement;
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
    await fireEvent.click(
      section(view, 'channel-test').getByRole('button', { name: 'Test senden' }),
    );

    await vi.waitFor(() =>
      expect(bodyOf('/api/admin/notify/channels/test', 'POST')).toEqual({
        channel: 'email',
        target: 'ops@example.com',
      }),
    );
  });
});

describe('Notifications page, mail design', () => {
  beforeEach(() => {
    language.set('de');
    current = channels();
    currentTemplate = template();
    previewAnswer = { subject: 'Disk full', fromName: '', text: 'Disk full', html: null };
    confirmMock.mockClear();
    confirmMock.mockImplementation(() => Promise.resolve(true));
    fetchMock = vi.fn(fetchStub);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('fills the stored design and lists the placeholders', async () => {
    currentTemplate = template({ subjectPrefix: '[Ops]', html: '<p>{{body}}</p>' });
    const view = render(Notifications);
    const prefix = (await view.findByLabelText('Betreff-Präfix')) as HTMLInputElement;
    expect(prefix.value).toBe('[Ops]');
    expect((view.getByLabelText('HTML-Teil') as HTMLTextAreaElement).value).toBe('<p>{{body}}</p>');
    expect(view.container.textContent).toContain('{{title}} {{body}}');
    expect(view.getByText('Kein Logo')).toBeTruthy();
  });

  it('saves the design as typed, the prefix trimmed', async () => {
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('Betreff-Präfix'), {
      target: { value: ' [Ops] ' },
    });
    await fireEvent.input(view.getByLabelText('HTML-Teil'), {
      target: { value: '<h1>{{title}}</h1>' },
    });
    const form = view.container.querySelector('form[data-section="design"]') as HTMLFormElement;
    await fireEvent.submit(form);

    await vi.waitFor(() =>
      expect(bodyOf('/api/admin/notify/template', 'PUT')).toEqual({
        subjectPrefix: '[Ops]',
        fromName: '',
        html: '<h1>{{title}}</h1>',
        text: '',
      }),
    );
  });

  it('renders the preview only in an iframe sandbox without scripts', async () => {
    previewAnswer = {
      subject: '[Ops] Disk full',
      fromName: 'Ops',
      text: 'Disk full',
      html: '<h1>Disk full</h1><script>parent.pwned = 1</script>',
    };
    const view = render(Notifications);
    await fireEvent.input(await view.findByLabelText('HTML-Teil'), {
      target: { value: '<h1>{{title}}</h1>' },
    });
    await fireEvent.click(view.getByRole('button', { name: 'Vorschau' }));

    const frame = (await view.findByTitle('Vorschau des HTML-Teils')) as HTMLIFrameElement;
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.getAttribute('srcdoc')).toContain('<h1>Disk full</h1>');
    // The page itself never carries the admin's markup.
    expect(view.container.querySelector('script')).toBeNull();
    expect(view.container.querySelector('h1')).toBeNull();
    expect(view.getByText('[Ops] Disk full')).toBeTruthy();
    // The preview renders what is typed, not what is stored.
    expect(bodyOf('/api/admin/notify/template/preview', 'POST').html).toBe('<h1>{{title}}</h1>');
  });

  it('says so when the preview has no HTML part', async () => {
    const view = render(Notifications);
    await fireEvent.click(await view.findByRole('button', { name: 'Vorschau' }));
    expect(await view.findByText('Kein HTML-Teil: die Mail geht als reiner Text.')).toBeTruthy();
    expect(view.container.querySelector('iframe')).toBeNull();
  });

  it('uploads a logo as base64 and removes it again', async () => {
    const view = render(Notifications);
    const input = (await view.findByLabelText('Logo hochladen')) as HTMLInputElement;
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    await fireEvent.change(input, {
      target: { files: [new File([png], 'logo.png', { type: 'image/png' })] },
    });

    await vi.waitFor(() =>
      expect(bodyOf('/api/admin/notify/template/logo', 'PUT')).toEqual({ data: 'iVBORw0KGgo=' }),
    );
    expect(await view.findByText('Logo gespeichert (image/png)')).toBeTruthy();

    await fireEvent.click(view.getByRole('button', { name: 'Logo entfernen' }));
    expect(await view.findByText('Kein Logo')).toBeTruthy();
    expect(
      fetchMock.mock.calls.some(
        ([i, init]) => String(i) === '/api/admin/notify/template/logo' && init?.method === 'DELETE',
      ),
    ).toBe(true);
  });

  it('refuses a logo over 200 KB without uploading it', async () => {
    const view = render(Notifications);
    const input = (await view.findByLabelText('Logo hochladen')) as HTMLInputElement;
    const big = new File([new Uint8Array(200 * 1024 + 1)], 'big.png', { type: 'image/png' });
    await fireEvent.change(input, { target: { files: [big] } });
    expect(fetchMock.mock.calls.some(([i]) => String(i).endsWith('/template/logo'))).toBe(false);
  });

  it('resets to the default only after the confirmation', async () => {
    currentTemplate = template({ subjectPrefix: '[Ops]' });
    confirmMock.mockImplementationOnce(() => Promise.resolve(false));
    const view = render(Notifications);
    const reset = await view.findByRole('button', { name: 'Auf Standard zurücksetzen' });
    await fireEvent.click(reset);
    await vi.waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);

    await fireEvent.click(reset);
    await vi.waitFor(() =>
      expect((view.getByLabelText('Betreff-Präfix') as HTMLInputElement).value).toBe(''),
    );
  });

  it('sends a test mail in the saved design', async () => {
    const view = render(Notifications);
    const form = await vi.waitFor(() => {
      const f = view.container.querySelector('form[data-section="design-test"]');
      expect(f).not.toBeNull();
      return f as HTMLFormElement;
    });
    const target = form.querySelector('input[name="designTarget"]') as HTMLInputElement;
    await fireEvent.input(target, { target: { value: ' ops@example.com ' } });
    await fireEvent.submit(form);
    await vi.waitFor(() =>
      expect(bodyOf('/api/admin/notify/template/test', 'POST')).toEqual({
        target: 'ops@example.com',
      }),
    );
  });
});
