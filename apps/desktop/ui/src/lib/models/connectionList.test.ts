// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { Connection } from '$lib/bridge/types';
import { emptyConnection } from './connection';
import {
  commandPreview,
  connectionsCsv,
  filterConnections,
  groupConnections,
  kindCounts,
  libraryCounts,
  NO_GROUP,
  probeTarget,
  quickAccess,
  sortConnections,
  tagCounts,
  type ListContext,
} from './connectionList';

const NOW = Date.parse('2026-11-02T12:00:00Z');
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

function conn(id: string, over: Partial<Connection> = {}): Connection {
  return { ...emptyConnection('ssh'), id, name: id, host: `${id}.example`, ...over };
}

const items: Connection[] = [
  conn('alpha', { tags: ['prod', 'db'], lastUsed: hoursAgo(2) }),
  conn('bravo', { kind: 'rdp', host: 'win.example', tags: ['prod'], lastUsed: hoursAgo(30) }),
  conn('charlie', { kind: 'web', host: null, url: 'https://Web.example:8443/x', username: 'ops' }),
  conn('delta', { host: 'win.example', lastUsed: hoursAgo(1) }),
];

const ctx: ListContext = {
  favorites: new Set(['bravo', 'charlie']),
  tunneled: new Set(['delta']),
  now: NOW,
};
const ids = (cs: Connection[]) => cs.map((c) => c.id);
const all = { library: 'all' as const, kind: null, tag: null, search: '' };

describe('filterConnections', () => {
  it('filters by library', () => {
    expect(ids(filterConnections(items, { ...all, library: 'favorites' }, ctx))).toEqual([
      'bravo',
      'charlie',
    ]);
    // 24 hours back from now: bravo (30 h) is out, charlie was never used.
    expect(ids(filterConnections(items, { ...all, library: 'recent' }, ctx))).toEqual([
      'alpha',
      'delta',
    ]);
    expect(ids(filterConnections(items, { ...all, library: 'tunnel' }, ctx))).toEqual(['delta']);
  });

  it('combines kind, tag and a search over name, host, url, user and tags', () => {
    expect(ids(filterConnections(items, { ...all, kind: 'ssh', tag: 'prod' }, ctx))).toEqual([
      'alpha',
    ]);
    expect(ids(filterConnections(items, { ...all, search: ' WIN.ex ' }, ctx))).toEqual([
      'bravo',
      'delta',
    ]);
    expect(ids(filterConnections(items, { ...all, search: 'ops' }, ctx))).toEqual(['charlie']);
    expect(ids(filterConnections(items, { ...all, search: 'db' }, ctx))).toEqual(['alpha']);
  });

  it('counts per library, kind and tag', () => {
    expect(libraryCounts(items, ctx)).toEqual({ all: 4, favorites: 2, recent: 2, tunnel: 1 });
    expect(kindCounts(items)).toEqual({ ssh: 2, rdp: 1, web: 1 });
    expect(tagCounts(items)).toEqual([
      ['db', 1],
      ['prod', 2],
    ]);
  });
});

describe('sortConnections', () => {
  it('sorts by name both ways', () => {
    expect(ids(sortConnections(items, 'name', 'desc'))).toEqual([
      'delta',
      'charlie',
      'bravo',
      'alpha',
    ]);
  });

  it('keeps connections without a value last in both directions', () => {
    const reach = { alpha: 30, bravo: null, charlie: 'tunnel' as const, delta: 5 };
    expect(ids(sortConnections(items, 'ping', 'asc', reach))).toEqual([
      'delta',
      'alpha',
      'bravo',
      'charlie',
    ]);
    expect(ids(sortConnections(items, 'ping', 'desc', reach))).toEqual([
      'alpha',
      'delta',
      'bravo',
      'charlie',
    ]);
    expect(ids(sortConnections(items, 'lastUsed', 'desc'))).toEqual([
      'delta',
      'alpha',
      'bravo',
      'charlie',
    ]);
    expect(ids(sortConnections(items, 'lastUsed', 'asc'))).toEqual([
      'bravo',
      'alpha',
      'delta',
      'charlie',
    ]);
  });
});

describe('groupConnections', () => {
  it('groups by host (web by its URL host), keeping the order inside', () => {
    const groups = groupConnections(items, 'host');
    expect(groups.map((g) => [g.key, ids(g.connections)])).toEqual([
      ['alpha.example', ['alpha']],
      ['web.example', ['charlie']],
      ['win.example', ['bravo', 'delta']],
    ]);
  });

  it('groups by tag with a connection in each of its tags, untagged last', () => {
    const groups = groupConnections(items, 'tag');
    expect(groups.map((g) => [g.key, ids(g.connections)])).toEqual([
      ['db', ['alpha']],
      ['prod', ['alpha', 'bravo']],
      [NO_GROUP, ['charlie', 'delta']],
    ]);
  });

  it('groups by kind in the order ssh, rdp, web, or not at all', () => {
    expect(groupConnections(items, 'kind').map((g) => g.key)).toEqual(['ssh', 'rdp', 'web']);
    expect(groupConnections(items, 'none')).toEqual([{ key: NO_GROUP, connections: items }]);
  });
});

describe('quickAccess', () => {
  it('puts favorites first, then the most recently used, at most four', () => {
    expect(ids(quickAccess(items, ctx))).toEqual(['bravo', 'charlie', 'delta', 'alpha']);
    const many = [...items, conn('echo', { lastUsed: hoursAgo(0.5) })];
    expect(ids(quickAccess(many, ctx))).toEqual(['bravo', 'charlie', 'echo', 'delta']);
  });
});

describe('commandPreview', () => {
  it('shows ssh as the backend builds it', () => {
    expect(commandPreview(conn('a', { host: 'h', username: 'u' }))).toBe('ssh -- u@h');
    expect(
      commandPreview(conn('a', { host: 'h', port: 2222, keyPath: '/k/my key', username: 'u' })),
    ).toBe("ssh -p 2222 -i '/k/my key' -- u@h");
    expect(commandPreview(conn('a', { host: 'h', username: "o'neil" }))).toBe(
      "ssh -- 'o'\\''neil@h'",
    );
  });

  it('shows xfreerdp with target, user and domain, and web as its URL', () => {
    expect(
      commandPreview(conn('a', { kind: 'rdp', host: 'w', username: 'adm', domain: 'CORP' })),
    ).toBe('xfreerdp /v:w:3389 /u:adm /d:CORP');
    expect(commandPreview(conn('a', { kind: 'web', url: 'intranet.example' }))).toBe(
      'https://intranet.example',
    );
  });
});

describe('probeTarget', () => {
  it('dials host and port, the default port when none is set', () => {
    expect(probeTarget(conn('a', { host: 'h', port: 2200 }))).toEqual({ host: 'h', port: 2200 });
    expect(probeTarget(conn('a', { kind: 'rdp', host: 'w' }))).toEqual({ host: 'w', port: 3389 });
    expect(probeTarget(conn('a', { host: null }))).toBeNull();
    expect(probeTarget(conn('a', { host: 'h', port: 0 }))).toBeNull();
  });

  it('takes the URL host and port for web, 443 or 80 by scheme', () => {
    expect(probeTarget(items[2])).toEqual({ host: 'web.example', port: 8443 });
    expect(probeTarget(conn('a', { kind: 'web', url: 'http://[2001:db8::1]/' }))).toEqual({
      host: '2001:db8::1',
      port: 80,
    });
    expect(probeTarget(conn('a', { kind: 'web', url: 'intranet.example' }))).toEqual({
      host: 'intranet.example',
      port: 443,
    });
    expect(probeTarget(conn('a', { kind: 'web', url: null }))).toBeNull();
    expect(probeTarget(conn('a', { kind: 'web', url: 'https://h.example:0/' }))).toBeNull();
    expect(probeTarget(conn('a', { kind: 'web', url: 'ftp://h.example/' }))).toBeNull();
    expect(probeTarget(conn('a', { kind: 'web', url: 'https://' }))).toBeNull();
  });
});

describe('connectionsCsv', () => {
  it('writes one row per connection under a header', () => {
    expect(
      connectionsCsv([
        conn('a', { port: 2222, username: 'root', tags: ['prod', 'db'] }),
        conn('b', { kind: 'web', host: null, url: 'https://x.example/?a=1,2' }),
      ]),
    ).toBe(
      'name,type,host,port,user,url,tags\n' +
        'a,ssh,a.example,2222,root,,prod db\n' +
        'b,web,,,,"https://x.example/?a=1,2",\n',
    );
  });

  it('quotes cells a spreadsheet would run as a formula', () => {
    expect(connectionsCsv([conn('=HYPERLINK("x")', { host: '+cmd' })]).split('\n')[1]).toBe(
      '"\'=HYPERLINK(""x"")",ssh,\'+cmd,,,,',
    );
  });
});
