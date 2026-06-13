// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { Connection } from '$lib/api/types';
import {
  emptyConnectionForm,
  connectionToForm,
  parseTags,
  formToPayload,
  validateConnectionForm,
} from './serverConnection';

describe('emptyConnectionForm', () => {
  it('defaults to an ssh form carrying the given serverId', () => {
    const f = emptyConnectionForm('srv-1');
    expect(f.kind).toBe('ssh');
    expect(f.serverId).toBe('srv-1');
    expect(f.id).toBeNull();
    expect(f.tags).toEqual([]);
  });
});

describe('connectionToForm', () => {
  it('maps an API connection into the editable form, coercing nulls', () => {
    const c: Connection = {
      id: 'c1',
      name: 'box',
      kind: 'vnc',
      host: 'box.lan',
      port: 5900,
      username: null,
      serverId: 'srv-1',
      tags: ['a'],
      trustCert: true,
    };
    expect(connectionToForm(c)).toEqual({
      id: 'c1',
      name: 'box',
      kind: 'vnc',
      host: 'box.lan',
      port: 5900,
      username: '',
      domain: '',
      keyPath: '',
      url: '',
      notes: '',
      tags: ['a'],
      trustCert: true,
      serverId: 'srv-1',
    });
  });
});

describe('parseTags', () => {
  it('splits, trims, drops empties and dedups', () => {
    expect(parseTags(' a, b ,a ,, ')).toEqual(['a', 'b']);
  });
});

describe('formToPayload', () => {
  it('trims, nulls empties, keeps serverId and never emits an id', () => {
    const payload = formToPayload({
      ...emptyConnectionForm('srv-1'),
      name: '  web  ',
      kind: 'ssh',
      host: ' box.lan ',
      username: '  ',
      tags: [' a ', 'a'],
    });
    expect(payload).toEqual({
      name: 'web',
      kind: 'ssh',
      host: 'box.lan',
      port: null,
      username: null,
      domain: null,
      keyPath: null,
      url: null,
      notes: null,
      tags: ['a'],
      trustCert: false,
      serverId: 'srv-1',
    });
    expect('id' in payload).toBe(false);
  });
});

describe('validateConnectionForm', () => {
  it('requires a name', () => {
    expect(validateConnectionForm(emptyConnectionForm()).ok).toBe(false);
  });

  it('requires a url for web connections', () => {
    const f = { ...emptyConnectionForm(), name: 'w', kind: 'web' as const };
    expect(validateConnectionForm(f).ok).toBe(false);
    expect(validateConnectionForm({ ...f, url: 'https://x' }).ok).toBe(true);
  });

  it('requires a host for non-web connections', () => {
    const f = { ...emptyConnectionForm(), name: 'w', kind: 'rdp' as const };
    expect(validateConnectionForm(f).ok).toBe(false);
    expect(validateConnectionForm({ ...f, host: 'h' }).ok).toBe(true);
  });
});
