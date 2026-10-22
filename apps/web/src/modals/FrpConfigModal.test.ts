// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * The FRP config form before saving (frps-supervisor T14).
 *
 * Every field but name and server_addr lands in frps.toml, and frps restarts once that file
 * changes. So the form asks before an edit that changes one of them or carries a new token,
 * and says more for a new token. A bind port other than the one the stack publishes gets a
 * warning at the field; saving stays possible.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import type * as FrpApi from '$lib/api/frp';

vi.mock('$lib/api/frp', async (importOriginal) => ({
  ...(await importOriginal<typeof FrpApi>()),
  createConfig: vi.fn(),
  updateConfig: vi.fn(),
  supervisorStatus: vi.fn(),
}));
// The form sits behind the login, and the confirm dialog asks only inside a session.
vi.mock('$lib/api/auth', () => ({
  login: vi.fn(async () => ({ id: 1, username: 'admin', is_admin: true })),
  logout: vi.fn(async () => {}),
  me: vi.fn(),
}));

import FrpConfigModal from './FrpConfigModal.svelte';
import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
import {
  createConfig,
  updateConfig,
  supervisorStatus,
  type FrpSupervisorStatus,
} from '$lib/api/frp';
import { ApiError, type FrpConfig } from '$lib/api/types';
import { language } from '$lib/i18n';
import { translations } from '$lib/i18n/dictionaries';
import { toasts, dismissToast } from '$lib/stores/notifications';
import { auth } from '$lib/stores/auth';

const de = translations.de;
const RESTART = de['modal.frpConfig.confirm.restart'];
const NEW_TOKEN = de['modal.frpConfig.confirm.newToken'];

// Every optional field set, so a change is a change from a stored value.
const FILLED: FrpConfig = {
  id: 'frp-1',
  name: 'edge',
  serverAddr: 'frp.example.com',
  bindPort: 7000,
  vhostHttpsPort: 443,
  authToken: null,
  subdomainHost: 'ops.example.net',
  maxPortsPerClient: 16,
  dashboardPort: 7500,
  dashboardUser: 'admin',
  dashboardPassword: null,
};

// Every optional field empty, the way the server returns a fresh config.
const EMPTY: FrpConfig = {
  id: 'frp-1',
  name: 'edge',
  serverAddr: 'frp.example.com',
  bindPort: 7000,
  vhostHttpsPort: null,
  authToken: null,
  subdomainHost: null,
  maxPortsPerClient: null,
  dashboardPort: null,
  dashboardUser: null,
  dashboardPassword: null,
};

const STATUS: FrpSupervisorStatus = {
  state: 'running',
  reason: 'none',
  since: '2026-10-17T08:00:00Z',
  stale: false,
  lastEvent: 'started',
  lastEventAt: '2026-10-17T08:00:00Z',
  publishedBindPort: 7000,
};

// The confirm dialog keeps its question in a module store: a test that fails before it answers
// would leave the question standing for the next test.
let dropQuestion: () => Promise<unknown> = async () => {};

/** The modal open on `editing`, with the app's confirm dialog mounted beside it. */
function renderModal(editing: FrpConfig | null) {
  const onClose = vi.fn();
  const question = render(ConfirmDialog);
  const view = render(FrpConfigModal, { props: { open: true, editing, onClose } });
  const field = (id: string) => view.container.querySelector(`#${id}`) as HTMLInputElement;
  const asked = () => question.container.querySelector('.modal-body p')?.textContent ?? null;
  const answer = (ok: boolean) =>
    fireEvent.click(
      question.container.querySelector(ok ? '.btn.danger' : '.btn.ghost') as HTMLButtonElement,
    );
  dropQuestion = async () => {
    if (asked() !== null) await answer(false);
  };
  return {
    view,
    onClose,
    field,
    type: (id: string, value: string) => fireEvent.input(field(id), { target: { value } }),
    submit: () => fireEvent.submit(view.container.querySelector('#frp-config-form') as Element),
    asked,
    answer,
    warning: () => view.queryByTestId('frp-bind-port-warning'),
  };
}

/** Lets the status request and the save settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(async () => {
  vi.mocked(updateConfig)
    .mockReset()
    .mockImplementation(async (id) => ({ ...FILLED, id }));
  vi.mocked(createConfig)
    .mockReset()
    .mockImplementation(async () => ({ ...EMPTY }));
  vi.mocked(supervisorStatus).mockReset().mockResolvedValue(STATUS);
  language.set('de');
  await auth.login('admin', 'pw');
});

afterEach(async () => {
  await dropQuestion();
  dropQuestion = async () => {};
  cleanup();
  for (const t of get(toasts)) dismissToast(t.id);
});

describe('asking before saving an edit', () => {
  it.each([
    ['bind port', 'fcBindPort', '7001'],
    ['vHost HTTPS port', 'fcVhostPort', '8443'],
    ['vHost HTTPS port, cleared', 'fcVhostPort', ''],
    ['subdomain host', 'fcSubdomainHost', 'tun.example.net'],
    ['subdomain host, cleared', 'fcSubdomainHost', ''],
    ['max ports per client', 'fcMaxPorts', '8'],
    ['dashboard port', 'fcDashPort', '7501'],
    ['dashboard user', 'fcDashUser', 'ops'],
    ['dashboard password, typed', 'fcDashPass', 'a-new-dashboard-password'],
  ])('asks when the %s changes, without the token hint', async (_name, id, value) => {
    const m = renderModal(FILLED);
    await m.type(id, value);

    await m.submit();

    await waitFor(() => expect(m.asked()).toBe(RESTART));
    expect(m.asked()).not.toContain(NEW_TOKEN);
    expect(updateConfig).not.toHaveBeenCalled();
    await m.answer(false);
  });

  it('asks with the token hint when a token is typed', async () => {
    const m = renderModal(FILLED);
    await m.type('fcAuthToken', 'a-new-token-of-enough-length');

    await m.submit();

    await waitFor(() => expect(m.asked()).toBe(`${RESTART} ${NEW_TOKEN}`));
    await m.answer(false);
  });

  it('says it in English too', async () => {
    language.set('en');
    const m = renderModal(FILLED);
    await m.type('fcAuthToken', 'a-new-token-of-enough-length');

    await m.submit();

    const en = translations.en;
    await waitFor(() =>
      expect(m.asked()).toBe(
        `${en['modal.frpConfig.confirm.restart']} ${en['modal.frpConfig.confirm.newToken']}`,
      ),
    );
    await m.answer(false);
  });

  it('saves a new name and server address without asking', async () => {
    const m = renderModal(FILLED);
    await m.type('fcName', 'edge-renamed');
    await m.type('fcServerAddr', 'frp2.example.com');

    await m.submit();

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1));
    expect(m.asked()).toBeNull();
    expect(vi.mocked(updateConfig).mock.calls[0][1]).toMatchObject({
      name: 'edge-renamed',
      server_addr: 'frp2.example.com',
      bind_port: 7000,
    });
    expect(vi.mocked(updateConfig).mock.calls[0][1]).not.toHaveProperty('auth_token');
    expect(m.onClose).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['set', FILLED],
    ['empty', EMPTY],
  ])('saves an unchanged form with every field %s without asking', async (_name, editing) => {
    const m = renderModal(editing);

    await m.submit();

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1));
    expect(m.asked()).toBeNull();
  });

  it('treats a stored empty text like an empty one', async () => {
    const m = renderModal({ ...EMPTY, subdomainHost: '', dashboardUser: '' });

    await m.submit();

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1));
    expect(m.asked()).toBeNull();
  });

  it('does not ask for fields typed into and emptied again, and sends them empty', async () => {
    const m = renderModal(EMPTY);
    for (const id of ['fcVhostPort', 'fcMaxPorts', 'fcDashPort']) {
      await m.type(id, '443');
      await m.type(id, '');
    }
    // An empty bind port is sent as the default, which is the stored 7000.
    await m.type('fcBindPort', '');
    await m.type('fcSubdomainHost', 'x.example.net');
    await m.type('fcSubdomainHost', ' ');
    await m.type('fcAuthToken', '   ');

    await m.submit();

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1));
    expect(m.asked()).toBeNull();
    expect(vi.mocked(updateConfig).mock.calls[0][1]).toEqual({
      name: 'edge',
      server_addr: 'frp.example.com',
      bind_port: 7000,
      vhost_https_port: null,
      subdomain_host: null,
      max_ports_per_client: null,
      dashboard_port: null,
      dashboard_user: null,
    });
  });

  it('sends nothing when cancelled, and keeps the form open for another try', async () => {
    const m = renderModal(FILLED);
    await m.type('fcBindPort', '7001');
    await m.submit();
    await waitFor(() => expect(m.asked()).not.toBeNull());

    await m.answer(false);
    await settle();

    expect(updateConfig).not.toHaveBeenCalled();
    expect(createConfig).not.toHaveBeenCalled();
    expect(m.onClose).not.toHaveBeenCalled();
    expect(m.asked()).toBeNull();
    expect(m.field('fcBindPort').value).toBe('7001');
    expect((m.view.container.querySelector('.btn.primary') as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it('sends exactly once when confirmed', async () => {
    const m = renderModal(FILLED);
    await m.type('fcBindPort', '7001');
    await m.type('fcAuthToken', 'a-new-token-of-enough-length');
    await m.submit();
    await waitFor(() => expect(m.asked()).not.toBeNull());

    await m.answer(true);

    await waitFor(() => expect(m.onClose).toHaveBeenCalledTimes(1));
    await settle();
    expect(updateConfig).toHaveBeenCalledTimes(1);
    expect(updateConfig).toHaveBeenCalledWith(
      'frp-1',
      expect.objectContaining({ bind_port: 7001, auth_token: 'a-new-token-of-enough-length' }),
    );
  });

  it('asks again after a cancel and sends once on the second answer', async () => {
    const m = renderModal(FILLED);
    await m.type('fcMaxPorts', '8');
    await m.submit();
    await waitFor(() => expect(m.asked()).not.toBeNull());
    await m.answer(false);
    await settle();

    await m.submit();
    await waitFor(() => expect(m.asked()).not.toBeNull());
    await m.answer(true);

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1));
    await settle();
    expect(updateConfig).toHaveBeenCalledTimes(1);
  });

  it('closes only the question on Escape, and the form on a second Escape', async () => {
    const m = renderModal(FILLED);
    await m.type('fcBindPort', '7001');
    await m.submit();
    await waitFor(() => expect(m.asked()).not.toBeNull());

    await fireEvent.keyDown(m.field('fcBindPort'), { key: 'Escape' });
    await settle();

    expect(m.asked()).toBeNull();
    expect(m.onClose).not.toHaveBeenCalled();
    expect(updateConfig).not.toHaveBeenCalled();
    expect(m.field('fcBindPort').value).toBe('7001');

    await fireEvent.keyDown(m.field('fcBindPort'), { key: 'Escape' });
    await settle();

    expect(m.onClose).toHaveBeenCalledTimes(1);
    expect(updateConfig).not.toHaveBeenCalled();
  });
});

describe('creating a config', () => {
  it('saves without asking, a typed token included', async () => {
    const m = renderModal(null);
    await m.type('fcName', 'edge');
    await m.type('fcServerAddr', 'frp.example.com');
    await m.type('fcBindPort', '7001');
    await m.type('fcAuthToken', 'a-new-token-of-enough-length');

    await m.submit();

    await waitFor(() => expect(createConfig).toHaveBeenCalledTimes(1));
    expect(m.asked()).toBeNull();
    expect(updateConfig).not.toHaveBeenCalled();
  });
});

describe('the bind port warning', () => {
  it('shows at the field once the bind port differs from the published one', async () => {
    const m = renderModal(FILLED);
    await settle();
    expect(m.warning()).toBeNull();

    await m.type('fcBindPort', '7001');

    expect(m.warning()?.textContent?.trim()).toBe(
      de['modal.frpConfig.bindPortMismatch'].replace('{port}', '7000'),
    );
    expect(m.field('fcBindPort').getAttribute('aria-describedby')).toBe(m.warning()?.id);

    await m.type('fcBindPort', '7000');
    expect(m.warning()).toBeNull();
  });

  it('shows for a stored bind port the stack does not publish', async () => {
    vi.mocked(supervisorStatus).mockResolvedValue({ ...STATUS, publishedBindPort: 7443 });
    const m = renderModal(FILLED);

    await waitFor(() => expect(m.warning()).not.toBeNull());
    expect(m.warning()?.textContent).toContain('7443');
  });

  it('shows on create for the default bind port', async () => {
    vi.mocked(supervisorStatus).mockResolvedValue({ ...STATUS, publishedBindPort: 7443 });
    const m = renderModal(null);

    await waitFor(() => expect(m.warning()).not.toBeNull());
  });

  it('leaves saving possible', async () => {
    const m = renderModal(FILLED);
    await settle();
    await m.type('fcBindPort', '7001');
    expect(m.warning()).not.toBeNull();

    await m.submit();
    await waitFor(() => expect(m.asked()).not.toBeNull());
    await m.answer(true);

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateConfig).mock.calls[0][1]).toMatchObject({ bind_port: 7001 });
  });

  it.each([
    ['a network error', () => vi.mocked(supervisorStatus).mockRejectedValue(new TypeError('x'))],
    [
      'a server without the route',
      () => vi.mocked(supervisorStatus).mockRejectedValue(new ApiError(404, 'Not Found')),
    ],
    [
      'an answer with a null port',
      () =>
        vi.mocked(supervisorStatus).mockResolvedValue({
          ...STATUS,
          publishedBindPort: null,
        } as unknown as FrpSupervisorStatus),
    ],
    [
      'an answer without the port',
      () => {
        const without: Partial<FrpSupervisorStatus> = { ...STATUS };
        delete without.publishedBindPort;
        vi.mocked(supervisorStatus).mockResolvedValue(without as FrpSupervisorStatus);
      },
    ],
  ])('stays away on %s', async (_name, arrange) => {
    arrange();
    const m = renderModal(FILLED);
    await waitFor(() => expect(supervisorStatus).toHaveBeenCalledTimes(1));
    await settle();

    await m.type('fcBindPort', '7001');

    expect(m.warning()).toBeNull();
  });
});
