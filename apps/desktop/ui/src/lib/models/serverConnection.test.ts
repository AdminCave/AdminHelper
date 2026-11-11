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
      kind: 'rdp',
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
      kind: 'rdp',
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
      label: 'web',
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

describe('own text of a connection of a server (R-1210)', () => {
  it('a new connection starts at the given server address', () => {
    expect(emptyConnectionForm('srv-1', 'web01.example.org').host).toBe('web01.example.org');
  });

  it('edits the label of a connection of a server, the name without one', () => {
    const bound = { id: 'c', name: 'web01 · root', label: 'root', kind: 'ssh', serverId: 's' };
    const before = { id: 'c', name: 'old name', kind: 'ssh', serverId: 's' };
    const free = { id: 'c', name: 'Prod-Gateway', label: 'Prod-Gateway', kind: 'ssh' };
    expect(connectionToForm(bound as Connection).name).toBe('root');
    expect(connectionToForm(before as Connection).name).toBe('old name');
    expect(connectionToForm(free as Connection).name).toBe('Prod-Gateway');
  });

  it('sends the own text as label, and as name or the server name without one', () => {
    const form = { ...emptyConnectionForm('srv-1', 'h'), name: ' root ' };
    expect(formToPayload(form, 'web01')).toMatchObject({ name: 'root', label: 'root' });
    const empty = emptyConnectionForm('srv-1', 'h');
    expect(formToPayload(empty, 'web01')).toMatchObject({ name: 'web01', label: '' });
    const free = { ...emptyConnectionForm(null, 'h'), name: 'Prod' };
    const payload = formToPayload(free);
    expect(payload).toMatchObject({ name: 'Prod' });
    expect('label' in payload).toBe(false);
  });

  it('needs a name only without a server', () => {
    expect(validateConnectionForm(emptyConnectionForm('srv-1', 'h')).ok).toBe(true);
    expect(validateConnectionForm(emptyConnectionForm(null, 'h')).ok).toBe(false);
  });
});
