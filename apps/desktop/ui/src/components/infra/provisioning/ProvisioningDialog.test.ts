// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The provisioning dialog builds the command from the server's catalog (R-1595/R-1596). It is
// the trusted courier for the agent's first contact: with an enrolled desktop it embeds the
// pinned CA fingerprint (--ca-fp) and shows it for out-of-band comparison; the token stays out
// of the command unless the admin switches to automation.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import type { ProvisionPlatform } from '$lib/api/types';

const FP = 'ab'.repeat(32);
const SERVER_ID = '3f2b8c1e-5d4a-4b6f-9e2d-7a1c0b9e8f42';
const TOKEN = 'adminhelper_prov_tok-123';
const INSTALL = 'curl -fsSL https://example/agent-install.sh | sudo bash -s --';
const WIN_EXE = "& 'C:\\Program Files\\AdminHelper\\adminhelper-agent.exe'";

const REGISTER = [
  { flag: '--server', value: 'serverUrl', optional: false, mode: null },
  { flag: '--server-id', value: 'serverId', optional: false, mode: null },
  { flag: '--ca-fp', value: 'caFp', optional: true, mode: null },
  { flag: '--token', value: 'token', optional: false, mode: 'automation' },
];
const PORTS = [
  { port: 443, purpose: 'api', tunnelOnly: false },
  { port: 7000, purpose: 'tunnel', tunnelOnly: true },
];

function platform(over: Partial<ProvisionPlatform>): ProvisionPlatform {
  return {
    id: 'linux',
    available: true,
    reason: null,
    versions: ['0.47.0'],
    arch: ['amd64'],
    abis: [],
    prerequisites: { systems: ['Debian 12/13'], ports: PORTS },
    commands: [],
    doc: { de: 'admin/agent-deployment.html#linux', en: 'en/admin/agent-deployment.html#linux' },
    ...over,
  } as ProvisionPlatform;
}

const LINUX = platform({
  commands: [
    { action: 'install', shell: 'bash', base: INSTALL, args: REGISTER },
    { action: 'update', shell: 'bash', base: 'sudo apt-get install --only-upgrade x', args: [] },
    { action: 'reregister', shell: 'bash', base: INSTALL, args: REGISTER },
    { action: 'remove', shell: 'bash', base: 'sudo apt-get purge -y x', args: [] },
  ],
} as Partial<ProvisionPlatform>);
const WINDOWS = platform({
  id: 'windows',
  reason: 'notYet',
  prerequisites: { systems: ['Windows (amd64)'], ports: PORTS },
  commands: [
    {
      action: 'reregister',
      shell: 'powershell',
      base: `${WIN_EXE} provision`,
      args: [
        { flag: '--url', value: 'serverUrl', optional: false, mode: null },
        { flag: '--server-id', value: 'serverId', optional: false, mode: null },
        { flag: '--token-stdin', value: 'flag', optional: false, mode: 'interactive' },
        { flag: '--token', value: 'token', optional: false, mode: 'automation' },
      ],
    },
    { action: 'remove', shell: 'powershell', base: `${WIN_EXE} service uninstall`, args: [] },
  ],
} as Partial<ProvisionPlatform>);
const FREEBSD = platform({
  id: 'freebsd',
  available: false,
  reason: 'noRepo',
  commands: [],
} as Partial<ProvisionPlatform>);
// A platform a later server adds: this desktop has no label for it and leaves it out.
const FUTURE = platform({ id: 'plan9' } as Partial<ProvisionPlatform>);

const h = vi.hoisted(() => ({
  pinnedCaFingerprint: vi.fn(async (): Promise<string | null> => null),
  createToken: vi.fn(async () => ({ token: 'adminhelper_prov_tok-123', id: 't1' })),
  platforms: vi.fn(async (): Promise<{ platforms: unknown[] }> => ({ platforms: [] })),
  serverUrl: { value: 'https://srm.example' },
}));

vi.mock('$lib/bridge', () => ({ pinnedCaFingerprint: h.pinnedCaFingerprint }));
vi.mock('$lib/api/provisioning', () => ({
  provisioningApi: { createToken: h.createToken, platforms: h.platforms },
}));
vi.mock('$lib/stores/session', async () => {
  const { readable, writable } = await import('svelte/store');
  return {
    session: readable({
      get serverUrl() {
        return h.serverUrl.value;
      },
      username: 'admin',
      isAdmin: true,
    }),
    settings: writable({ mode: 'server', allowSelfSignedCerts: false }),
  };
});
vi.mock('$lib/stores/statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));

import ProvisioningDialog from './ProvisioningDialog.svelte';
import { reportError, showStatus } from '$lib/stores/statusBar';

const server = { id: SERVER_ID, name: 'srv', osType: 'linux' };

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  h.serverUrl.value = 'https://srm.example';
});

async function open(srv: object = server, list: ProvisionPlatform[] = [LINUX, WINDOWS, FREEBSD]) {
  h.platforms.mockResolvedValue({ platforms: list });
  const onTokenCreated = vi.fn();
  const view = render(ProvisioningDialog, {
    server: srv as never,
    onClose: vi.fn(),
    onTokenCreated,
  });
  await waitFor(() => expect(view.container.ownerDocument.querySelector('select')).not.toBeNull());
  return { ...view, onTokenCreated, doc: view.container.ownerDocument };
}

function byTestId(doc: Document, id: string): HTMLElement | null {
  return doc.querySelector(`[data-testid="${id}"]`);
}

function commandText(doc: Document): string {
  return byTestId(doc, 'provision-command')?.querySelector('pre')?.textContent ?? '';
}

async function choose(doc: Document, id: string): Promise<void> {
  await fireEvent.change(doc.querySelector('select') as HTMLSelectElement, {
    target: { value: id },
  });
}

async function tab(doc: Document, label: string): Promise<void> {
  const btn = Array.from(doc.querySelectorAll('[role="tab"]')).find(
    (b) => b.textContent?.trim() === label,
  );
  expect(btn).toBeDefined();
  await fireEvent.click(btn as HTMLElement);
}

async function mint(doc: Document): Promise<void> {
  await fireEvent.click(doc.querySelector('[data-action="prov-mint"]') as HTMLButtonElement);
}

describe('ProvisioningDialog — catalog', () => {
  it('preselects the server platform and lists only platforms it can label', async () => {
    const { doc } = await open(server, [LINUX, WINDOWS, FREEBSD, FUTURE]);
    const select = doc.querySelector('select') as HTMLSelectElement;
    expect(select.value).toBe('linux');
    const labels = Array.from(select.options).map((o) => o.textContent?.trim());
    expect(labels).toEqual(['Linux', 'Windows', 'FreeBSD (nicht verfügbar)']);
  });

  it('starts on the first available platform when the server has none', async () => {
    const { doc } = await open({ id: SERVER_ID, name: 'srv', osType: null }, [FREEBSD, WINDOWS]);
    expect((doc.querySelector('select') as HTMLSelectElement).value).toBe('windows');
  });

  it('shows the prerequisites with the tunnel-only port marked', async () => {
    const { doc } = await open();
    const prereq = byTestId(doc, 'prov-prereq')?.textContent ?? '';
    expect(prereq).toContain('Debian 12/13');
    expect(prereq).toContain('443: API');
    expect(prereq).toContain(`7000: Tunnel (${tNow('infra.prov.tunnelOnly')})`);
  });

  it('shows the reason and no command for a platform without packages', async () => {
    const { doc } = await open();
    await choose(doc, 'freebsd');
    await waitFor(() => expect(byTestId(doc, 'prov-unavailable')).not.toBeNull());
    expect(byTestId(doc, 'prov-unavailable')?.textContent).toContain(
      tNow('infra.prov.reason.noRepo'),
    );
    expect(byTestId(doc, 'provision-command')).toBeNull();
    expect(doc.querySelector('[data-action="prov-mint"]')).toBeNull();
  });

  it('shows an error and no command when the catalog does not load', async () => {
    h.platforms.mockRejectedValueOnce(new Error('boom'));
    const view = render(ProvisioningDialog, {
      server: server as never,
      onClose: vi.fn(),
    });
    const doc = view.container.ownerDocument;
    await waitFor(() =>
      expect(doc.body.textContent).toContain(tNow('infra.prov.catalogError', { message: 'boom' })),
    );
    expect(byTestId(doc, 'provision-command')).toBeNull();
  });

  it('offers only the actions the catalog has, with the Windows hint', async () => {
    const { doc } = await open();
    await choose(doc, 'windows');
    await waitFor(() => expect(doc.body.textContent).toContain(tNow('infra.prov.reason.notYet')));
    const tabs = Array.from(doc.querySelectorAll('[role="tab"]')).map((b) => b.textContent?.trim());
    expect(tabs).toEqual(['Neu registrieren', 'Entfernen']);
    const text = commandText(doc);
    expect(text).toContain(`${WIN_EXE} provision`);
    expect(text).toContain(`--server-id '${SERVER_ID}'`);
    expect(text).toContain('--token-stdin');
  });
});

describe('ProvisioningDialog — trust anchor handover', () => {
  it('embeds --ca-fp and shows the fingerprint when enrolled', async () => {
    h.pinnedCaFingerprint.mockResolvedValue(FP);
    const { doc } = await open();
    await waitFor(() => expect(byTestId(doc, 'ca-fp')?.textContent).toContain(FP));
    expect(byTestId(doc, 'no-ca-fp')).toBeNull();

    const text = commandText(doc);
    expect(text).toContain(INSTALL);
    expect(text).toContain('--server https://srm.example');
    expect(text).toContain(`--server-id ${SERVER_ID}`);
    expect(text).toContain(`--ca-fp ${FP}`);
    expect(text).not.toContain('--token');
  });

  it('warns visibly and leaves --ca-fp out without an enrolled identity', async () => {
    h.pinnedCaFingerprint.mockResolvedValue(null);
    const { doc } = await open();
    await waitFor(() => expect(byTestId(doc, 'no-ca-fp')).not.toBeNull());
    expect(commandText(doc)).not.toContain('--ca-fp');
  });

  it('puts a session URL with a quote into single quotes', async () => {
    h.serverUrl.value = "https://srm.example/a'b";
    const { doc } = await open();
    expect(commandText(doc)).toContain("--server 'https://srm.example/a'\\''b' ");
  });

  it('shows no command for a server ID that is not a UUID', async () => {
    const { doc } = await open({ id: 'sid-9;id', name: 'srv', osType: 'linux' });
    expect(byTestId(doc, 'provision-command')).toBeNull();
    expect(byTestId(doc, 'prov-no-command')).not.toBeNull();
  });

  it('switches the command with the action tab', async () => {
    const { doc } = await open();
    await tab(doc, 'Entfernen');
    await waitFor(() => expect(commandText(doc)).toBe('sudo apt-get purge -y x'));
    expect(doc.querySelector('[data-action="prov-mint"]')).toBeNull();
  });
});

describe('ProvisioningDialog — the token', () => {
  it('shows exactly the token beside the command and copies exactly it', async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const { doc, onTokenCreated } = await open();
    await mint(doc);
    await waitFor(() => expect(byTestId(doc, 'prov-token')).not.toBeNull());
    expect(onTokenCreated).toHaveBeenCalledTimes(1);

    const box = byTestId(doc, 'prov-token') as HTMLElement;
    expect(box.querySelector('code')?.textContent).toBe(TOKEN);
    expect(commandText(doc)).not.toContain(TOKEN);
    await fireEvent.click(box.querySelector('button') as HTMLButtonElement);
    expect(writeText).toHaveBeenCalledWith(TOKEN);
    expect(showStatus).toHaveBeenCalledWith(tNow('infra.prov.tokenCopied'));
  });

  // A token with a leading `-` would be read as an option by the script it is handed to.
  it.each(['tok;id', '$(id)', '-x', '--server'])(
    'shows no token for the token %s, and the list reloads all the same',
    async (token) => {
      h.createToken.mockResolvedValueOnce({ token, id: 't1' });
      const { doc, onTokenCreated } = await open();
      await mint(doc);
      await waitFor(() => expect(reportError).toHaveBeenCalledWith(tNow('infra.prov.badResponse')));
      expect(byTestId(doc, 'prov-token')).toBeNull();
      expect(onTokenCreated).toHaveBeenCalledTimes(1);
    },
  );

  it('hides the token after a minute', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { doc } = await open();
    await mint(doc);
    await waitFor(() => expect(byTestId(doc, 'prov-token')).not.toBeNull());
    await vi.advanceTimersByTimeAsync(60_000);
    await waitFor(() => expect(byTestId(doc, 'prov-token')).toBeNull());
  });

  it('keeps the token on screen when the command is copied, hides it shortly after the token is', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async () => {}) } });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { doc } = await open();
    await mint(doc);
    await waitFor(() => expect(byTestId(doc, 'prov-token')).not.toBeNull());

    const cmd = byTestId(doc, 'provision-command') as HTMLElement;
    await fireEvent.click(cmd.querySelector('button') as HTMLButtonElement);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(byTestId(doc, 'prov-token')).not.toBeNull();

    const box = byTestId(doc, 'prov-token') as HTMLElement;
    await fireEvent.click(box.querySelector('button') as HTMLButtonElement);
    await vi.advanceTimersByTimeAsync(10_000);
    await waitFor(() => expect(byTestId(doc, 'prov-token')).toBeNull());
  });
});

describe('ProvisioningDialog — automation', () => {
  async function automate(doc: Document): Promise<void> {
    await fireEvent.click(doc.querySelector('[role="switch"]') as HTMLElement);
  }

  it('asks for a token first, then puts it into the command with a warning', async () => {
    const { doc } = await open();
    await automate(doc);
    await waitFor(() => expect(byTestId(doc, 'prov-automation-warn')).not.toBeNull());
    expect(byTestId(doc, 'prov-need-token')).not.toBeNull();
    expect(byTestId(doc, 'provision-command')).toBeNull();

    await mint(doc);
    await waitFor(() => expect(commandText(doc)).toContain(`--token ${TOKEN}`));
    // The token is in the command, the separate box would only show it twice.
    expect(byTestId(doc, 'prov-token')).toBeNull();
  });

  it('drops the interactive --token-stdin for automation on Windows', async () => {
    const { doc } = await open();
    await choose(doc, 'windows');
    await waitFor(() => expect(commandText(doc)).toContain('--token-stdin'));
    await automate(doc);
    await mint(doc);
    await waitFor(() => expect(commandText(doc)).toContain(`--token '${TOKEN}'`));
    expect(commandText(doc)).not.toContain('--token-stdin');
  });

  it('hides the command with the token shortly after it was copied', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async () => {}) } });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { doc } = await open();
    await automate(doc);
    await mint(doc);
    await waitFor(() => expect(commandText(doc)).toContain(TOKEN));

    const cmd = byTestId(doc, 'provision-command') as HTMLElement;
    await fireEvent.click(cmd.querySelector('button') as HTMLButtonElement);
    await vi.advanceTimersByTimeAsync(10_000);
    await waitFor(() => expect(byTestId(doc, 'provision-command')).toBeNull());
    expect(byTestId(doc, 'prov-need-token')).not.toBeNull();
  });
});
