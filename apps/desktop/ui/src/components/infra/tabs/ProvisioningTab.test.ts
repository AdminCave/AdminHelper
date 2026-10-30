// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The provisioning tab is the trusted courier for the agent's first-contact
// trust anchors: with an enrolled desktop it must embed the pinned CA
// fingerprint (--ca-fp) into BOTH generated commands (install script +
// provision-only) and display it for out-of-band comparison; without an
// enrolled identity it must fall back to the previous TOFU behaviour and say
// so visibly.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';

const FP = 'ab'.repeat(32);
const SERVER_ID = '3f2b8c1e-5d4a-4b6f-9e2d-7a1c0b9e8f42';

const h = vi.hoisted(() => ({
  pinnedCaFingerprint: vi.fn(async (): Promise<string | null> => null),
  createToken: vi.fn(async () => ({ token: 'tok-123', id: 't1' })),
  listTokens: vi.fn(async () => []),
  allowSelfSigned: { value: false },
  serverUrl: { value: 'https://srm.example' },
}));

vi.mock('$lib/bridge', () => ({ pinnedCaFingerprint: h.pinnedCaFingerprint }));
vi.mock('$lib/api/provisioning', () => ({
  provisioningApi: { createToken: h.createToken, listTokens: h.listTokens },
}));
vi.mock('$lib/stores/session', async () => {
  const { readable, writable } = await import('svelte/store');
  return {
    session: readable({
      // Read at click time, so a test can hand the tab another session URL.
      get serverUrl() {
        return h.serverUrl.value;
      },
      username: 'admin',
      isAdmin: true,
    }),
    settings: writable({ mode: 'server', allowSelfSignedCerts: h.allowSelfSigned.value }),
  };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import ProvisioningTab from './ProvisioningTab.svelte';
import { reportError, showStatus } from '$lib/stores/statusBar';

const server = { id: SERVER_ID, name: 'srv' } as never;

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  h.serverUrl.value = 'https://srm.example';
});

describe('ProvisioningTab — trust anchor handover', () => {
  it('embeds --ca-fp in both commands and shows the fingerprint when enrolled', async () => {
    h.pinnedCaFingerprint.mockResolvedValue(FP);
    const { getByTestId, queryByTestId, getByText } = render(ProvisioningTab, { server });

    await waitFor(() => expect(getByTestId('ca-fp').textContent).toContain(FP));
    expect(queryByTestId('no-ca-fp')).toBeNull();

    await fireEvent.click(getByText('Token erzeugen'));

    await waitFor(() => expect(queryByTestId('script-command')).not.toBeNull());
    const script = getByTestId('script-command').textContent ?? '';
    expect(script).toContain('scripts/agent-install.sh');
    expect(script).toContain('--server https://srm.example');
    expect(script).not.toContain('--token');
    expect(script).not.toContain('tok-123');
    expect(script).toContain(`--server-id ${SERVER_ID}`);
    expect(script).toContain(`--ca-fp ${FP}`);

    const plain = getByTestId('provision-command').textContent ?? '';
    expect(plain).toContain('adminhelper-agent provision');
    // The token is read from stdin, like the one-liner asks for it: never an argument.
    expect(plain).toContain('--token-stdin');
    expect(plain).not.toContain('--token ');
    expect(plain).not.toContain('tok-123');
    expect(plain).toContain(`--ca-fp ${FP}`);
    expect(plain).not.toContain('--insecure');
  });

  it('falls back to TOFU without an enrolled identity and warns visibly', async () => {
    h.pinnedCaFingerprint.mockResolvedValue(null);
    h.allowSelfSigned.value = true;
    const { getByTestId, queryByTestId, getByText } = render(ProvisioningTab, { server });

    await waitFor(() => expect(queryByTestId('no-ca-fp')).not.toBeNull());

    await fireEvent.click(getByText('Token erzeugen'));
    await waitFor(() => expect(queryByTestId('script-command')).not.toBeNull());

    expect(getByTestId('script-command').textContent).not.toContain('--ca-fp');
    // The settings store was built with allowSelfSignedCerts at mock-module init;
    // the plain command honours it exactly like the login path does.
    const plain = getByTestId('provision-command').textContent ?? '';
    expect(plain).not.toContain('--ca-fp');
  });
});

// Both commands run as root on the target host. A token or server ID that is not in the form
// the server issues yields no command at all; every value is exactly one shell word.
describe('ProvisioningTab — the values in the commands', () => {
  async function createWith(srv: unknown) {
    h.pinnedCaFingerprint.mockResolvedValue(null);
    const view = render(ProvisioningTab, { server: srv as never });
    await waitFor(() => expect(h.listTokens).toHaveBeenCalledTimes(1));
    await fireEvent.click(view.getByText('Token erzeugen'));
    return view;
  }

  async function expectNoCommand(view: Awaited<ReturnType<typeof createWith>>): Promise<void> {
    await waitFor(() => expect(reportError).toHaveBeenCalledWith(tNow('infra.prov.badResponse')));
    expect(view.queryByTestId('script-command')).toBeNull();
    expect(view.queryByTestId('provision-command')).toBeNull();
    // The token exists on the server all the same, so the list is reloaded.
    await waitFor(() => expect(h.listTokens).toHaveBeenCalledTimes(2));
  }

  // A token with a leading `-` would be read as an option by the script it is handed to.
  it.each(['tok;id', '$(id)', '-x', '--server'])(
    'shows no command for the token %s',
    async (token) => {
      h.createToken.mockResolvedValueOnce({ token, id: 't1' });
      await expectNoCommand(await createWith(server));
    },
  );

  it('shows no command for a server ID that is not a UUID', async () => {
    await expectNoCommand(await createWith({ id: 'sid-9;id', name: 'srv' }));
  });

  it('clears the commands of an earlier token when the next response is malformed', async () => {
    const view = await createWith(server);
    await waitFor(() => expect(view.queryByTestId('provision-command')).not.toBeNull());

    h.createToken.mockResolvedValueOnce({ token: 'tok;id', id: 't2' });
    await fireEvent.click(view.getByText('Token erzeugen'));
    await waitFor(() => expect(reportError).toHaveBeenCalledWith(tNow('infra.prov.badResponse')));
    expect(view.queryByTestId('script-command')).toBeNull();
    expect(view.queryByTestId('provision-command')).toBeNull();
    expect(view.queryByTestId('prov-token')).toBeNull();
  });

  it('puts a session URL with a quote into single quotes in both commands', async () => {
    h.serverUrl.value = "https://srm.example/a'b";
    const view = await createWith(server);
    await waitFor(() => expect(view.queryByTestId('script-command')).not.toBeNull());

    const quoted = "'https://srm.example/a'\\''b'";
    const script = view.getByTestId('script-command').textContent ?? '';
    const plain = view.getByTestId('provision-command').textContent ?? '';
    expect(script).toContain(`--server ${quoted} `);
    expect(plain).toContain(`--url ${quoted} `);
    // The values the server issues stay as they are.
    expect(plain).toContain('--token-stdin ');
    expect(plain).toContain(`--server-id ${SERVER_ID}`);
    expect(reportError).not.toHaveBeenCalled();
  });
});

// The one-liner carries no token: agent-install.sh asks for it on /dev/tty with the input hidden,
// so the secret stays out of shell history and the process list. The tab shows it beside the
// command to copy.
describe('ProvisioningTab — the token beside the one-liner', () => {
  async function created() {
    h.pinnedCaFingerprint.mockResolvedValue(null);
    const view = render(ProvisioningTab, { server });
    await waitFor(() => expect(h.listTokens).toHaveBeenCalledTimes(1));
    await fireEvent.click(view.getByText('Token erzeugen'));
    return view;
  }

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('shows exactly the token and copies exactly it', async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const view = await created();
    await waitFor(() => expect(view.queryByTestId('prov-token')).not.toBeNull());

    const box = view.getByTestId('prov-token');
    expect(box.querySelector('code')?.textContent).toBe('tok-123');
    expect(box.textContent).toContain(tNow('infra.prov.tokenPrompt'));
    await fireEvent.click(box.querySelector('button') as HTMLButtonElement);
    expect(writeText).toHaveBeenCalledWith('tok-123');
    expect(showStatus).toHaveBeenCalledWith(tNow('infra.prov.tokenCopied'));
  });

  it('shows no token box for a token in another form', async () => {
    h.createToken.mockResolvedValueOnce({ token: '-x', id: 't1' });
    const view = await created();
    await waitFor(() => expect(reportError).toHaveBeenCalledWith(tNow('infra.prov.badResponse')));
    expect(view.queryByTestId('prov-token')).toBeNull();
  });

  it('hides the token with the commands after a minute', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const view = await created();
    await waitFor(() => expect(view.queryByTestId('prov-token')).not.toBeNull());

    await vi.advanceTimersByTimeAsync(60_000);
    await waitFor(() => expect(view.queryByTestId('script-command')).toBeNull());
    expect(view.queryByTestId('prov-token')).toBeNull();
    expect(view.queryByTestId('provision-command')).toBeNull();
  });

  it('keeps the token on screen when the one-liner is copied, hides it shortly after the token is', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async () => {}) } });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const view = await created();
    await waitFor(() => expect(view.queryByTestId('prov-token')).not.toBeNull());

    const script = view.getByTestId('script-command');
    await fireEvent.click(script.querySelector('button') as HTMLButtonElement);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(view.queryByTestId('prov-token')).not.toBeNull();

    const box = view.getByTestId('prov-token');
    await fireEvent.click(box.querySelector('button') as HTMLButtonElement);
    await vi.advanceTimersByTimeAsync(10_000);
    await waitFor(() => expect(view.queryByTestId('prov-token')).toBeNull());
    expect(view.queryByTestId('script-command')).toBeNull();
  });

  it('keeps the token on screen when the provision-only command is copied', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async () => {}) } });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const view = await created();
    await waitFor(() => expect(view.queryByTestId('prov-token')).not.toBeNull());

    const plain = view.getByTestId('provision-command');
    await fireEvent.click(plain.querySelector('button') as HTMLButtonElement);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(view.queryByTestId('prov-token')).not.toBeNull();
  });
});
