// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { FrpTunnel } from '$lib/api/types';
import { tNow } from '$lib/i18n';
import {
  emptyTunnelForm,
  tunnelToForm,
  parseTags,
  formToInput,
  validateTunnelForm,
  defaultWebScheme,
  PROTOCOL_DEFAULT_PORT,
  type TunnelForm,
} from './frpTunnel';

describe('emptyTunnelForm', () => {
  it('defaults to an stcp/ssh tunnel on the given server, no config yet', () => {
    const f = emptyTunnelForm('srv-1');
    expect(f.serverId).toBe('srv-1');
    expect(f.frpConfigId).toBe('');
    expect(f.tunnelType).toBe('stcp');
    expect(f.protocol).toBe('ssh');
    expect(f.localIp).toBe('127.0.0.1');
  });
});

describe('PROTOCOL_DEFAULT_PORT', () => {
  it('maps protocols to their default local ports', () => {
    expect(PROTOCOL_DEFAULT_PORT).toEqual({ ssh: 22, rdp: 3389, web: 8006 });
  });
});

describe('tunnelToForm', () => {
  it('maps an entity into the form and infers autoCreateConnection from connectionId', () => {
    const t: FrpTunnel = {
      id: 't1',
      serverId: 'srv-1',
      frpConfigId: 'cfg-1',
      name: 'ssh',
      tunnelType: 'stcp',
      protocol: 'ssh',
      localIp: '10.0.0.1',
      localPort: 22,
      secretKey: 'sec',
      visitorPort: 13389,
      connectionId: 'conn-9',
      enabled: true,
    };
    const f = tunnelToForm(t);
    expect(f.autoCreateConnection).toBe(true);
    expect(f.secretKey).toBe('sec');
    expect(f.visitorPort).toBe(13389);
  });
});

describe('parseTags', () => {
  it('splits, trims, dedups', () => {
    expect(parseTags(' a, a ,b ')).toEqual(['a', 'b']);
  });
});

describe('formToInput', () => {
  it('keeps secret/visitor for stcp and nulls customDomains', () => {
    const input = formToInput({
      ...emptyTunnelForm('srv-1', 'cfg-1'),
      name: 'ssh',
      tunnelType: 'stcp',
      localPort: 22,
      secretKey: ' sec ',
      visitorPort: 13389,
      customDomains: 'leftover.example',
    });
    expect(input.secret_key).toBe('sec');
    expect(input.visitor_port).toBe(13389);
    expect(input.custom_domains).toBeNull();
    expect(input.server_id).toBe('srv-1');
    expect(input.frp_config_id).toBe('cfg-1');
  });

  it('keeps customDomains for https and nulls secret/visitor', () => {
    const input = formToInput({
      ...emptyTunnelForm('srv-1', 'cfg-1'),
      name: 'web',
      tunnelType: 'https',
      localPort: 8006,
      secretKey: 'leftover',
      visitorPort: 9999,
      customDomains: ' tunnel.example ',
    });
    expect(input.custom_domains).toBe('tunnel.example');
    expect(input.secret_key).toBeNull();
    expect(input.visitor_port).toBeNull();
  });

  it('falls back to 127.0.0.1 for a blank local ip', () => {
    const input = formToInput({
      ...emptyTunnelForm('s', 'c'),
      name: 'n',
      localPort: 22,
      localIp: '',
    });
    expect(input.local_ip).toBe('127.0.0.1');
  });
});

describe('validateTunnelForm', () => {
  it('requires a config and a positive port; the own text is optional (R-1210)', () => {
    expect(validateTunnelForm(emptyTunnelForm('s')).ok).toBe(false); // no config
    expect(validateTunnelForm({ ...emptyTunnelForm('s', 'c') }).ok).toBe(false); // no port
    expect(validateTunnelForm({ ...emptyTunnelForm('s', 'c'), localPort: 22 }).ok).toBe(true);
  });

  const valid = { ...emptyTunnelForm('s', 'c'), name: 'n', localPort: 22 };

  it.each([0, 65536, -1, 1.5])('rejects the stcp visitor port %s', (visitorPort) => {
    expect(validateTunnelForm({ ...valid, tunnelType: 'stcp', visitorPort })).toEqual({
      ok: false,
      message: tNow('infra.tun.validation.visitorPortRange'),
    });
  });

  it.each([1, 65535, null])('accepts the stcp visitor port %s', (visitorPort) => {
    expect(validateTunnelForm({ ...valid, tunnelType: 'stcp', visitorPort })).toEqual({ ok: true });
  });

  it('does not check the visitor port of an https tunnel', () => {
    expect(validateTunnelForm({ ...valid, tunnelType: 'https', visitorPort: 0 })).toEqual({
      ok: true,
    });
  });
});

describe('own text of a tunnel (R-1210)', () => {
  it('edits the label, the name of a tunnel from an older server', () => {
    const base = {
      id: 't1',
      serverId: 's',
      frpConfigId: 'c',
      tunnelType: 'stcp' as const,
      protocol: 'ssh' as const,
      localIp: null,
      localPort: 22,
      secretKey: null,
      visitorPort: null,
      enabled: true,
    };
    expect(tunnelToForm({ ...base, name: 'web01 · backup (FRP)', label: 'backup' }).name).toBe(
      'backup',
    );
    expect(tunnelToForm({ ...base, name: 'k01-ssh' }).name).toBe('k01-ssh');
  });

  it('sends the own text as label, and as name or "{server}-{protocol}" without one', () => {
    const form = { ...emptyTunnelForm('s', 'c'), localPort: 22 };
    expect(formToInput({ ...form, name: ' backup ' }, 'web01')).toMatchObject({
      name: 'backup',
      label: 'backup',
    });
    expect(formToInput({ ...form, protocol: 'rdp' }, 'web01')).toMatchObject({
      name: 'web01-rdp',
      label: '',
    });
  });
});

// A web tunnel's connection gets scheme and path instead of a user (R-1540).
describe('web auto-connection', () => {
  const web = (over: Partial<TunnelForm> = {}): TunnelForm => ({
    ...emptyTunnelForm('s', 'c'),
    protocol: 'web',
    localPort: 8006,
    autoCreateConnection: true,
    autoConnectionUsername: 'root',
    ...over,
  });
  const edited = (over: Partial<TunnelForm> = {}): TunnelForm =>
    web({ initialShape: { protocol: 'web', tunnelType: 'stcp' }, ...over });

  it('guesses https for the usual TLS ports and http otherwise', () => {
    for (const p of [443, 8006, 8443, 9443]) expect(defaultWebScheme(p)).toBe('https');
    for (const p of [80, 8080, 3000]) expect(defaultWebScheme(p)).toBe('http');
    expect(defaultWebScheme(null)).toBe('http');
  });

  it('sends scheme and path for a new web tunnel and no user', () => {
    expect(formToInput(web({ autoConnectionPath: ' /ui/?a=1 ' }))).toMatchObject({
      auto_connection_scheme: 'https',
      auto_connection_path: '/ui/?a=1',
      auto_connection_username: null,
    });
  });

  it('follows the port until the user picks a scheme', () => {
    expect(formToInput(web({ localPort: 8080 })).auto_connection_scheme).toBe('http');
    expect(
      formToInput(web({ localPort: 8006, autoConnectionScheme: 'http' })).auto_connection_scheme,
    ).toBe('http');
    expect(formToInput(web()).auto_connection_path).toBeNull();
  });

  it('sends neither for another protocol, which keeps its user', () => {
    const input = formToInput(web({ protocol: 'ssh', localPort: 22 }));
    expect(input.auto_connection_username).toBe('root');
    expect('auto_connection_scheme' in input).toBe(false);
    expect('auto_connection_path' in input).toBe(false);
  });

  it('sends neither without an auto-connection', () => {
    const input = formToInput(web({ autoCreateConnection: false }));
    expect('auto_connection_scheme' in input).toBe(false);
  });

  it('sends the scheme when an existing tunnel changes protocol or type, not otherwise', () => {
    expect('auto_connection_scheme' in formToInput(edited())).toBe(false);
    expect(
      formToInput(edited({ initialShape: { protocol: 'ssh', tunnelType: 'stcp' } }))
        .auto_connection_scheme,
    ).toBe('https');
    expect(
      formToInput(edited({ initialShape: { protocol: 'web', tunnelType: 'https' } }))
        .auto_connection_scheme,
    ).toBe('https');
  });

  it('opens an existing tunnel with its shape and a scheme that follows the port', () => {
    const f = tunnelToForm({
      id: 't',
      serverId: 's',
      frpConfigId: 'c',
      name: 'n',
      tunnelType: 'https',
      protocol: 'web',
      localIp: '127.0.0.1',
      localPort: 443,
      enabled: true,
      connectionId: 'conn',
    });
    expect(f.initialShape).toEqual({ protocol: 'web', tunnelType: 'https' });
    expect(f.autoConnectionScheme).toBeNull();
    expect(f.autoConnectionPath).toBe('');
  });

  it.each(['ui', '/a b', '/a#b', '/a\nb', '/a\u0080b', '/' + 'a'.repeat(255)])(
    'rejects the path %j like the server',
    (path) => {
      const r = validateTunnelForm(web({ autoConnectionPath: path }));
      expect(r).toEqual({ ok: false, message: tNow('infra.tun.validation.path') });
    },
  );

  it('accepts a path the server takes and ignores one it would not send', () => {
    expect(validateTunnelForm(web({ autoConnectionPath: '/' + 'a'.repeat(254) }))).toEqual({
      ok: true,
    });
    expect(validateTunnelForm(web({ autoConnectionPath: '/pve/?x=1&y=%20' })).ok).toBe(true);
    expect(validateTunnelForm(edited({ autoConnectionPath: 'stale' })).ok).toBe(true);
  });
});
