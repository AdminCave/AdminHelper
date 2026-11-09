// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  ansibleConnectionOf,
  buildAnsibleTargets,
  groupServersByTag,
  sshConnectionsOf,
  visitorMissing,
} from './ansible';
import type { Server } from '$lib/api/types';
import type { Connection, ResolvedConnection, TunnelMapping } from '$lib/bridge/types';

const srv = (id: string, hostname: string, tags: string[] = []): Server => ({
  id,
  name: id,
  hostname,
  tags,
});

describe('buildAnsibleTargets', () => {
  it('maps servers to {hostname, groups}', () => {
    const servers = [srv('a', 'a.example', ['web', 'prod']), srv('b', 'b.example')];
    expect(buildAnsibleTargets(servers)).toEqual([
      { hostname: 'a.example', groups: ['web', 'prod'] },
      { hostname: 'b.example', groups: [] },
    ]);
  });
});

const conn = (id: string, over: Partial<Connection> = {}): Connection => ({
  id,
  name: id,
  kind: 'ssh',
  host: '192.0.2.10',
  port: 22,
  tags: [],
  trustCert: false,
  serverId: 'a',
  ...over,
});

describe('buildAnsibleTargets with connections (R-1202)', () => {
  it('hands the reached connection along and leaves a server without one at its hostname', () => {
    const via = conn('c1', { host: '127.0.0.1', port: 23001 });
    const servers = [srv('a', 'a.example', ['web']), srv('b', 'b.example')];
    expect(buildAnsibleTargets(servers, new Map([['a', via]]))).toEqual([
      { hostname: 'a.example', groups: ['web'], connection: via },
      { hostname: 'b.example', groups: [] },
    ]);
  });
});

describe('the SSH connection Ansible takes', () => {
  const server = srv('a', 'a.example');
  const all = [
    conn('zeta'),
    conn('rdp', { kind: 'rdp' }),
    conn('other', { serverId: 'b' }),
    conn('alpha'),
  ];

  it('lists only the SSH connections of the server, by name', () => {
    expect(sshConnectionsOf(server, all).map((c) => c.id)).toEqual(['alpha', 'zeta']);
  });

  it('takes the first by name unless one of the server is chosen', () => {
    expect(ansibleConnectionOf(server, all, {})?.id).toBe('alpha');
    expect(ansibleConnectionOf(server, all, { a: 'zeta' })?.id).toBe('zeta');
    // A choice that is no longer one of the server's SSH connections counts for nothing.
    expect(ansibleConnectionOf(server, all, { a: 'rdp' })?.id).toBe('alpha');
    expect(ansibleConnectionOf(srv('c', 'c.example'), all, {})).toBeNull();
  });
});

describe('visitorMissing', () => {
  const stcp: TunnelMapping = {
    id: 't1',
    serverId: 'a',
    tunnelType: 'stcp',
    protocol: 'tcp',
    localPort: 22,
    visitorPort: 6022,
    customDomains: null,
    connectionId: 'c1',
    enabled: true,
    name: 'a-ssh',
  };
  const resolved = (c: Connection, over: Partial<ResolvedConnection> = {}): ResolvedConnection => ({
    connection: c,
    viaTunnel: false,
    ...over,
  });

  it('is true for an STCP mapping that left the target as it was', () => {
    const c = conn('c1');
    expect(visitorMissing(c, resolved(c, { viaTunnel: true, tunnelType: 'stcp' }), [stcp])).toBe(
      true,
    );
    const atVisitor = { ...c, host: '127.0.0.1', port: 23001 };
    expect(
      visitorMissing(c, resolved(atVisitor, { viaTunnel: true, tunnelType: 'stcp' }), [stcp]),
    ).toBe(false);
    expect(visitorMissing(c, resolved(c, { viaTunnel: true, tunnelType: 'https' }), [stcp])).toBe(
      false,
    );
  });

  it('is true for a loopback target at the visitor port of an STCP tunnel', () => {
    for (const host of ['127.0.0.1', 'localhost', 'LocalHost']) {
      const c = conn('auto', { host, port: 6022 });
      expect(visitorMissing(c, resolved(c), [stcp]), host).toBe(true);
    }
    const otherPort = conn('auto', { host: '127.0.0.1', port: 2222 });
    expect(visitorMissing(otherPort, resolved(otherPort), [stcp])).toBe(false);
    const remote = conn('remote', { port: 6022 });
    expect(visitorMissing(remote, resolved(remote), [stcp])).toBe(false);
    const auto = conn('auto', { host: '127.0.0.1', port: 6022 });
    expect(visitorMissing(auto, resolved(auto), [{ ...stcp, enabled: false }])).toBe(false);
  });
});

describe('groupServersByTag', () => {
  it('groups by tag, each server in every matching tag', () => {
    const servers = [
      srv('a', 'a.example', ['web', 'eu']),
      srv('b', 'b.example', ['web']),
      srv('c', 'c.example', ['db']),
    ];
    const groups = groupServersByTag(servers);
    expect(Object.keys(groups).sort()).toEqual(['db', 'eu', 'web']);
    expect(groups.web.map((s) => s.id)).toEqual(['a', 'b']);
    expect(groups.db.map((s) => s.id)).toEqual(['c']);
  });

  it('returns empty object for servers without tags', () => {
    expect(groupServersByTag([srv('a', 'a.example')])).toEqual({});
  });
});
