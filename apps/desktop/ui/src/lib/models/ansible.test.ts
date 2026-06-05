// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import { buildAnsibleTargets, groupServersByTag } from './ansible';
import type { Server } from '$lib/api/types';

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
