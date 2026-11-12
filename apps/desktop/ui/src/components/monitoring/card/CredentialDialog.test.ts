// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T10 (R-1225, concept decision 3): the dialog that stores a module
// check's credentials on its host. The secret is typed on the host only, so the dialog
// has no field for it: it opens the terminal action of T9 over one of the server's SSH
// connections, or shows the command to run there. Its ref comes from the server and is
// checked against the agent's rule before it becomes command text.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  connectCredential: vi.fn(async (..._a: unknown[]): Promise<void> => undefined),
}));
vi.mock('$lib/stores/connectFlow', () => ({ connectCredential: h.connectCredential }));

import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import type { MonitorCheck } from '$lib/api/types';
import type { Connection } from '$lib/bridge/types';
import { setLanguage } from '$lib/i18n';
import CredentialDialog, { credentialRefOf } from './CredentialDialog.svelte';

const REF = 'mysql/3306/monitor';

function ssh(id: string, name: string): Connection {
  return {
    id,
    name,
    kind: 'ssh',
    host: `${id}.example.test`,
    port: 22,
    tags: [],
    trustCert: false,
    serverId: 'srv-1',
  };
}

function show(connections: Connection[], windows = false) {
  const onClose = vi.fn();
  const view = render(CredentialDialog, {
    open: true,
    checkName: 'MySQL',
    credentialRef: REF,
    connections,
    windows,
    onClose,
  });
  return { ...view, onClose };
}

beforeEach(() => {
  setLanguage('en');
  h.connectCredential.mockClear();
});
afterEach(cleanup);

describe('CredentialDialog', () => {
  it('opens the credential action over the one SSH connection, then closes', async () => {
    const box = ssh('c1', 'Box');
    const { getByRole, onClose } = show([box]);
    expect(document.body.textContent).toContain(
      `sudo adminhelper-agent monitor credential set ${REF}`,
    );
    await fireEvent.click(getByRole('button', { name: 'Open terminal' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(h.connectCredential).toHaveBeenCalledExactlyOnceWith(box, REF);
  });

  it('opens it over the connection the admin picks', async () => {
    const a = ssh('c1', 'Box A');
    const b = ssh('c2', 'Box B');
    const { getByRole } = show([a, b]);
    await fireEvent.click(getByRole('radio', { name: /Box B/ }));
    await fireEvent.click(getByRole('button', { name: 'Open terminal' }));
    await waitFor(() => expect(h.connectCredential).toHaveBeenCalledExactlyOnceWith(b, REF));
  });

  it('shows the command to run as root when the server has no SSH connection', () => {
    const { queryByRole } = show([]);
    expect(queryByRole('button', { name: 'Open terminal' })).toBeNull();
    expect(document.body.textContent).toContain('no SSH connection');
    expect(document.body.textContent).toContain(
      `sudo adminhelper-agent monitor credential set ${REF}`,
    );
  });

  it('shows the PowerShell form on a Windows host and opens no terminal', () => {
    const { queryByRole } = show([ssh('c1', 'Box')], true);
    expect(queryByRole('button', { name: 'Open terminal' })).toBeNull();
    expect(document.body.textContent).toContain(
      `& 'C:\\Program Files\\AdminHelper\\adminhelper-agent.exe' monitor credential set ${REF}`,
    );
    expect(document.body.textContent).not.toContain('sudo');
  });

  it('asks for no secret in the desktop', () => {
    show([ssh('c1', 'Box')]);
    expect(document.querySelector('input:not([type="radio"]), textarea')).toBeNull();
  });
});

describe('credentialRefOf', () => {
  const withConfig = (config: unknown) => ({ id: 'k', config }) as unknown as MonitorCheck;

  it('takes the ref the server built for the module check', () => {
    expect(credentialRefOf(withConfig({ credential: { ref: REF, use: 'password' } }))).toBe(REF);
    expect(credentialRefOf(withConfig({ credential: { ref: 'a.b:c@d-e_f' } }))).toBe('a.b:c@d-e_f');
  });

  it.each([
    ['a;rm -rf /'],
    ['$(id)'],
    ['a b'],
    ['.hidden'],
    ['/abs'],
    ['a//b'],
    ['a/'],
    ["a'b"],
    ['x'.repeat(256)],
  ])('refuses %j, which the agent would refuse too', (ref) => {
    expect(credentialRefOf(withConfig({ credential: { ref } }))).toBeNull();
  });

  it('takes a ref of exactly 255 characters', () => {
    const ref = 'x'.repeat(255);
    expect(credentialRefOf(withConfig({ credential: { ref } }))).toBe(ref);
  });

  it.each([
    [undefined],
    [{}],
    [{ credential: null }],
    [{ credential: 'a' }],
    [{ credential: { ref: 5 } }],
  ])('finds none in %j', (config) => {
    expect(credentialRefOf(withConfig(config))).toBeNull();
  });
});
