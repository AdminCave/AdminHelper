// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { Server } from '$lib/api/types';
import {
  emptyServerInput,
  serverToInput,
  parseTags,
  normalizeServerInput,
  validateServerInput,
  filterServers,
} from './infra';

const srv = (over: Partial<Server>): Server => ({
  id: 'id',
  name: 'name',
  hostname: 'host',
  osType: null,
  tags: [],
  notes: null,
  ...over,
});

describe('emptyServerInput', () => {
  it('returns blank, server-API-shaped input', () => {
    expect(emptyServerInput()).toEqual({
      name: '',
      hostname: '',
      os_type: null,
      tags: [],
      notes: '',
    });
  });
});

describe('serverToInput', () => {
  it('maps a server entity (camelCase) onto the snake_case input', () => {
    const input = serverToInput(
      srv({ name: 'web', hostname: 'web.lan', osType: 'linux', tags: ['prod'], notes: 'x' }),
    );
    expect(input).toEqual({
      name: 'web',
      hostname: 'web.lan',
      os_type: 'linux',
      tags: ['prod'],
      notes: 'x',
    });
  });

  it('coerces missing osType/notes to null/empty', () => {
    const input = serverToInput(srv({ name: 'w', hostname: 'h', osType: null, notes: null }));
    expect(input.os_type).toBeNull();
    expect(input.notes).toBe('');
  });

  it('copies the tags array (no shared reference)', () => {
    const original = srv({ tags: ['a'] });
    const input = serverToInput(original);
    input.tags.push('b');
    expect(original.tags).toEqual(['a']);
  });
});

describe('parseTags', () => {
  it('splits, trims, drops empties and dedups', () => {
    expect(parseTags(' a , b ,, a , c ')).toEqual(['a', 'b', 'c']);
  });

  it('returns [] for a blank string', () => {
    expect(parseTags('   ')).toEqual([]);
  });
});

describe('normalizeServerInput', () => {
  it('trims fields, dedups tags and maps blank osType to null', () => {
    expect(
      normalizeServerInput({
        name: '  web  ',
        hostname: '  web.lan ',
        os_type: '   ',
        tags: [' a ', 'a', ' b '],
        notes: '  hi  ',
      }),
    ).toEqual({
      name: 'web',
      hostname: 'web.lan',
      os_type: null,
      tags: ['a', 'b'],
      notes: 'hi',
    });
  });
});

describe('the address follows the name (R-1210)', () => {
  it('sends the name as the address when none of its own is entered', () => {
    const input = normalizeServerInput({ ...emptyServerInput(), name: ' web01.example.org ' });
    expect(input.hostname).toBe('web01.example.org');
  });

  it('keeps an own address', () => {
    const input = normalizeServerInput({
      ...emptyServerInput(),
      name: 'mail',
      hostname: ' 192.0.2.10 ',
    });
    expect(input.hostname).toBe('192.0.2.10');
  });

  it('shows an empty address field while the address follows the name', () => {
    const following = srv({ name: 'web01', hostname: 'web01', customHostname: false });
    const own = srv({ name: 'mail', hostname: '192.0.2.10', customHostname: true });
    const before = srv({ name: 'old', hostname: 'old.lan' });
    expect(serverToInput(following).hostname).toBe('');
    expect(serverToInput(own).hostname).toBe('192.0.2.10');
    // A server from before R-1210 sends no flag: its hostname stays in the field.
    expect(serverToInput(before).hostname).toBe('old.lan');
  });
});

describe('validateServerInput', () => {
  it('requires a name', () => {
    const r = validateServerInput({ ...emptyServerInput(), hostname: 'h' });
    expect(r.ok).toBe(false);
    expect(r.message).toBeTruthy();
  });

  it('takes a name alone: the address follows it (R-1210)', () => {
    expect(validateServerInput({ ...emptyServerInput(), name: 'n' }).ok).toBe(true);
  });

  it('accepts a name + hostname', () => {
    expect(validateServerInput({ ...emptyServerInput(), name: 'n', hostname: 'h' }).ok).toBe(true);
  });
});

describe('filterServers', () => {
  const servers = [
    srv({ id: '1', name: 'Gamma', hostname: 'gamma.lan', osType: 'linux', tags: ['db'] }),
    srv({ id: '2', name: 'Alpha', hostname: 'alpha.lan', osType: 'windows' }),
    srv({ id: '3', name: 'Beta', hostname: 'beta.lan', tags: ['prod', 'web'] }),
  ];

  it('sorts by name when search is empty', () => {
    expect(filterServers(servers, '').map((s) => s.name)).toEqual(['Alpha', 'Beta', 'Gamma']);
  });

  it('matches name, hostname, osType and tags (case-insensitive)', () => {
    expect(filterServers(servers, 'GAMMA').map((s) => s.id)).toEqual(['1']);
    expect(filterServers(servers, 'beta.lan').map((s) => s.id)).toEqual(['3']);
    expect(filterServers(servers, 'windows').map((s) => s.id)).toEqual(['2']);
    expect(filterServers(servers, 'prod').map((s) => s.id)).toEqual(['3']);
  });

  it('returns [] when nothing matches', () => {
    expect(filterServers(servers, 'zzz')).toEqual([]);
  });
});
