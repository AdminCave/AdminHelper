// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Command palette entries and matching (R-1062).

import { describe, it, expect, vi } from 'vitest';
import type { Connection } from '$lib/bridge/types';
import { buildEntries, filterEntries, MAX_RESULTS, type PaletteEntry } from './palette';

const conn = (over: Partial<Connection>): Connection => ({
  id: 'c',
  name: '',
  kind: 'ssh',
  tags: [],
  trustCert: false,
  ...over,
});

function entry(label: string, hint?: string): PaletteEntry {
  return { id: label, kind: 'action', label, hint, run: () => {} };
}

describe('buildEntries', () => {
  it('lists connections, then pages, then actions, each running its own target', () => {
    const connect = vi.fn();
    const navigate = vi.fn();
    const action = vi.fn();
    const web = conn({ id: 'w', name: 'Wiki', kind: 'web', url: 'https://wiki.example' });
    const entries = buildEntries({
      connections: [conn({ id: 's', name: '', host: 'db1.example' }), web],
      pages: [{ id: 'monitoring', label: 'Monitoring', href: '/monitoring' }],
      actions: [{ id: 'theme', label: 'Theme wechseln', run: action }],
      connect,
      navigate,
    });
    expect(entries.map((e) => [e.id, e.kind, e.label, e.hint])).toEqual([
      ['connection:s', 'connection', 'db1.example', 'db1.example'],
      ['connection:w', 'connection', 'Wiki', 'https://wiki.example'],
      ['page:monitoring', 'page', 'Monitoring', undefined],
      ['action:theme', 'action', 'Theme wechseln', undefined],
    ]);
    entries[1].run();
    expect(connect).toHaveBeenCalledWith(web);
    entries[2].run();
    expect(navigate).toHaveBeenCalledWith('/monitoring');
    entries[3].run();
    expect(action).toHaveBeenCalledOnce();
  });
});

describe('filterEntries', () => {
  it('matches without regard to case and ranks a prefix before a substring before a hint', () => {
    const list = [
      entry('Backup-Server', 'web01'),
      entry('Web-Proxy'),
      entry('Alter Webserver'),
      entry('Drucker'),
    ];
    expect(filterEntries(list, 'WEB').map((e) => e.label)).toEqual([
      'Web-Proxy',
      'Alter Webserver',
      'Backup-Server',
    ]);
    expect(filterEntries(list, '  drUCK ').map((e) => e.label)).toEqual(['Drucker']);
    expect(filterEntries(list, 'nichts')).toEqual([]);
  });

  it('returns at most nine entries, with and without a query', () => {
    const list = Array.from({ length: 20 }, (_, i) => entry(`host-${i}`));
    expect(MAX_RESULTS).toBe(9);
    expect(filterEntries(list, '')).toHaveLength(9);
    expect(filterEntries(list, 'host')).toHaveLength(9);
    expect(filterEntries(list, '')[0].label).toBe('host-0');
  });
});
