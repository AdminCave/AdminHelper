// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  normalizeConnection,
  parseTags,
  validateConnection,
  toCardMeta,
  emptyConnection,
  DEFAULT_PORTS,
} from './connection';

describe('normalizeConnection', () => {
  it('trims strings and converts empty to null', () => {
    const out = normalizeConnection({
      name: '  Hetzner ',
      kind: 'ssh',
      host: '  example.com  ',
      username: '',
      domain: '',
    });
    expect(out.name).toBe('Hetzner');
    expect(out.host).toBe('example.com');
    expect(out.username).toBeNull();
    expect(out.domain).toBeNull();
  });

  it('parses port from string or number', () => {
    expect(normalizeConnection({ kind: 'ssh', port: '2222' as unknown as number }).port).toBe(2222);
    expect(normalizeConnection({ kind: 'ssh', port: 22 }).port).toBe(22);
    expect(normalizeConnection({ kind: 'ssh', port: '' as unknown as number }).port).toBeNull();
  });

  it('drops empty tags and trims them', () => {
    const out = normalizeConnection({ kind: 'ssh', tags: [' a ', '', 'b'] });
    expect(out.tags).toEqual(['a', 'b']);
  });

  it('generates stable id when missing', () => {
    const out = normalizeConnection({ name: 'x', kind: 'ssh' });
    expect(typeof out.id).toBe('string');
    expect(out.id.length).toBeGreaterThan(0);
  });
});

describe('parseTags', () => {
  it('splits on comma and trims', () => {
    expect(parseTags('a, b ,,c')).toEqual(['a', 'b', 'c']);
    expect(parseTags('')).toEqual([]);
  });
});

describe('validateConnection', () => {
  it('rejects empty name', () => {
    const c = emptyConnection('ssh');
    expect(validateConnection(c).ok).toBe(false);
  });

  it('web needs url', () => {
    const c = { ...emptyConnection('web'), name: 'Docs' };
    expect(validateConnection(c).ok).toBe(false);
    c.url = 'https://x';
    expect(validateConnection(c).ok).toBe(true);
  });

  it('ssh/rdp need host', () => {
    const c = { ...emptyConnection('ssh'), name: 'srv' };
    expect(validateConnection(c).ok).toBe(false);
    c.host = '1.2.3.4';
    expect(validateConnection(c).ok).toBe(true);
  });
});

describe('toCardMeta', () => {
  it('uses default port when missing', () => {
    const c = { ...emptyConnection('ssh'), name: 'srv', host: '1.2.3.4', username: 'root' };
    expect(toCardMeta(c)).toBe(`root@1.2.3.4:${DEFAULT_PORTS.ssh}`);
  });
  it('uses url for web', () => {
    const c = { ...emptyConnection('web'), url: 'https://x' };
    expect(toCardMeta(c)).toBe('https://x');
  });
});
