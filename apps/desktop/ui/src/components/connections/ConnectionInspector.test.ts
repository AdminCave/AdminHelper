// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The connection inspector (R-1065): its fields, command preview, notes and actions, and the
// last sessions of the connection (R-1068).

import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, within } from '@testing-library/svelte';
import type { Connection, ConnectionSession } from '$lib/bridge/types';
import type { Reach } from '$lib/models/connectionList';
import { setLanguage, tNow } from '$lib/i18n';

const h = vi.hoisted(() => ({
  recent: vi.fn(async (..._a: unknown[]): Promise<ConnectionSession[]> => []),
}));
vi.mock('$lib/stores/connections', async () => {
  const { writable } = await import('svelte/store');
  const version = writable(0);
  return {
    recentSessions: h.recent,
    sessionsVersion: version,
    sessionsChanged: () => version.update((n) => n + 1),
  };
});

import { sessionsChanged } from '$lib/stores/connections';
import ConnectionInspector from './ConnectionInspector.svelte';

const SSH: Connection = {
  id: 'a',
  name: 'web01',
  kind: 'ssh',
  host: 'web01.example',
  port: 2222,
  username: 'deploy',
  domain: null,
  keyPath: '/home/me/.ssh/id_ed25519',
  url: null,
  notes: 'Reboot only on Sunday.',
  tags: ['prod', 'web'],
  trustCert: false,
  lastUsed: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  serverId: 's1',
};
const WEB: Connection = {
  ...SSH,
  id: 'c',
  name: 'portal',
  kind: 'web',
  host: null,
  port: null,
  username: null,
  keyPath: null,
  url: 'https://portal.example',
  notes: null,
  tags: [],
};

function renderInsp(
  over: Partial<{
    conn: Connection | null;
    favorite: boolean;
    reach: Reach;
    tunnel: string | null;
    server: string | null;
  }> = {},
) {
  const props = {
    conn: SSH as Connection | null,
    favorite: false,
    reach: undefined as Reach,
    tunnel: null as string | null,
    server: null as string | null,
    onConnect: vi.fn(),
    onEdit: vi.fn(),
    onFavorite: vi.fn(),
    ...over,
  };
  render(ConnectionInspector, { props });
  return props;
}

// The value next to a field label in the definition list.
function field(label: string): string | null {
  const dt = screen.queryAllByText(label).find((el) => el.tagName === 'DT');
  return dt?.nextElementSibling?.textContent?.trim() ?? null;
}

beforeAll(() => {
  setLanguage('en');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  h.recent.mockReset();
  h.recent.mockResolvedValue([]);
});

describe('ConnectionInspector', () => {
  it('asks for a selection while none is made', () => {
    renderInsp({ conn: null });
    expect(screen.getByText(tNow('connections.insp.empty'))).not.toBeNull();
    expect(screen.queryByRole('button', { name: tNow('action.connect') })).toBeNull();
  });

  it('shows the fields, tags, command preview and notes of an SSH connection', () => {
    renderInsp({ tunnel: 'db-tunnel', server: 'web01 (prod)', reach: 12 });
    expect(screen.getByRole('heading', { name: 'web01' })).not.toBeNull();
    expect(field(tNow('connections.insp.kind'))).toBe('SSH');
    expect(field(tNow('connections.insp.host'))).toBe('web01.example');
    expect(field(tNow('connections.insp.port'))).toBe('2222');
    expect(field(tNow('connections.insp.user'))).toBe('deploy');
    expect(field(tNow('connections.insp.key'))).toBe('/home/me/.ssh/id_ed25519');
    expect(field(tNow('connections.insp.tunnel'))).toBe('db-tunnel');
    expect(field(tNow('connections.insp.server'))).toBe('web01 (prod)');
    expect(field(tNow('connections.insp.reach'))).toBe(tNow('connections.ping.ms', { ms: 12 }));
    expect(field(tNow('connections.insp.last'))).not.toBeNull();
    expect(screen.getByText('prod')).not.toBeNull();
    expect(screen.getByText('web')).not.toBeNull();
    expect(
      screen.getByText('ssh -p 2222 -i /home/me/.ssh/id_ed25519 -- deploy@web01.example'),
    ).not.toBeNull();
    expect(screen.getByText('Reboot only on Sunday.')).not.toBeNull();
  });

  it('leaves out key, tunnel, server and notes when there are none and shows the default port', () => {
    renderInsp({
      conn: { ...SSH, port: null, keyPath: null, notes: '  ', domain: 'CORP', kind: 'rdp' },
    });
    expect(field(tNow('connections.insp.port'))).toBe('3389');
    expect(field(tNow('connections.insp.user'))).toBe('CORP\\deploy');
    expect(field(tNow('connections.insp.key'))).toBeNull();
    expect(field(tNow('connections.insp.tunnel'))).toBeNull();
    expect(field(tNow('connections.insp.server'))).toBeNull();
    expect(screen.queryByText(tNow('connections.insp.notes'))).toBeNull();
  });

  it('shows unreachable, tunnel and unknown reachability', () => {
    renderInsp({ reach: null });
    expect(field(tNow('connections.insp.reach'))).toBe(tNow('connections.ping.down'));
    cleanup();
    renderInsp({ reach: 'tunnel' });
    expect(field(tNow('connections.insp.reach'))).toBe(tNow('tunnel.badge'));
    cleanup();
    renderInsp({ reach: undefined });
    expect(field(tNow('connections.insp.reach'))).toBe(tNow('connections.insp.unknown'));
  });

  it('shows the URL of a web connection and opens it', async () => {
    const p = renderInsp({ conn: WEB });
    expect(field(tNow('connections.insp.url'))).toBe('https://portal.example');
    expect(field(tNow('connections.insp.host'))).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: tNow('connections.open') }));
    expect(p.onConnect).toHaveBeenCalledWith(WEB);
  });

  it('connects, edits and stars the connection', async () => {
    const p = renderInsp({ favorite: true });
    await fireEvent.click(screen.getByRole('button', { name: tNow('action.connect') }));
    expect(p.onConnect).toHaveBeenCalledWith(SSH);
    await fireEvent.click(screen.getByRole('button', { name: tNow('action.edit') }));
    expect(p.onEdit).toHaveBeenCalledWith(SSH);
    const star = screen.getByRole('button', { name: tNow('connections.favorite.remove') });
    expect(star.getAttribute('aria-pressed')).toBe('true');
    await fireEvent.click(star);
    expect(p.onFavorite).toHaveBeenCalledWith(SSH);
  });

  it('copies the command preview', async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    renderInsp();
    const preview = screen.getByText(tNow('connections.insp.command')).parentElement!;
    await fireEvent.click(within(preview).getByRole('button', { name: tNow('action.copy') }));
    expect(writeText).toHaveBeenCalledWith(
      'ssh -p 2222 -i /home/me/.ssh/id_ed25519 -- deploy@web01.example',
    );
  });
});

describe('ConnectionInspector recent sessions', () => {
  const ago = (min: number): string => new Date(Date.now() - min * 60_000).toISOString();
  const rows = (): string[] =>
    [...screen.getByTestId('insp-sessions').querySelectorAll('li')].map((li) =>
      [...li.querySelectorAll('span')].map((s) => s.textContent?.trim()).join(' | '),
    );

  it('loads the last five sessions with start, duration and device', async () => {
    h.recent.mockResolvedValueOnce([
      { id: '1', device: null, startedAt: ago(3), endedAt: null },
      { id: '2', device: 'laptop', startedAt: ago(30), endedAt: ago(18) },
      { id: '3', device: 'desk', startedAt: ago(200), endedAt: ago(70) },
      { id: '4', device: 'desk', startedAt: ago(300), endedAt: ago(299.5) },
    ]);
    renderInsp();
    expect(h.recent).toHaveBeenCalledWith('a', 5);
    await vi.waitFor(() => expect(rows()).toHaveLength(4));
    expect(rows()).toEqual([
      `${tNow('timeAgo.minutes', { count: 3 })} | — | —`,
      `${tNow('timeAgo.minutes', { count: 30 })} | 12 min | laptop`,
      `${tNow('timeAgo.hours', { count: 3 })} | 2 h 10 min | desk`,
      `${tNow('timeAgo.hours', { count: 5 })} | < 1 min | desk`,
    ]);
  });

  it('says so when there are none, or when they could not be loaded', async () => {
    renderInsp();
    expect(await screen.findByText(tNow('connections.insp.sessions.empty'))).not.toBeNull();
    cleanup();
    h.recent.mockRejectedValueOnce(new Error('offline'));
    renderInsp();
    expect(await screen.findByText(tNow('connections.insp.sessions.failed'))).not.toBeNull();
  });

  it('reloads when a session was written or ended, with the selection unchanged', async () => {
    renderInsp();
    expect(await screen.findByText(tNow('connections.insp.sessions.empty'))).not.toBeNull();
    h.recent.mockResolvedValueOnce([{ id: '1', device: 'box', startedAt: ago(1), endedAt: null }]);
    sessionsChanged();
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(h.recent).toHaveBeenCalledTimes(2);
  });

  it('loads nothing without a selection', () => {
    renderInsp({ conn: null });
    expect(h.recent).not.toHaveBeenCalled();
  });
});
