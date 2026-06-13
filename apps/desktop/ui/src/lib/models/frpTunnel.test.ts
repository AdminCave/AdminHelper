// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { FrpTunnel } from '$lib/api/types';
import {
  emptyTunnelForm,
  tunnelToForm,
  parseTags,
  formToInput,
  validateTunnelForm,
  PROTOCOL_DEFAULT_PORT,
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
  it('requires a config, a name and a positive port', () => {
    expect(validateTunnelForm(emptyTunnelForm('s')).ok).toBe(false); // no config
    expect(validateTunnelForm({ ...emptyTunnelForm('s', 'c') }).ok).toBe(false); // no name
    expect(validateTunnelForm({ ...emptyTunnelForm('s', 'c'), name: 'n' }).ok).toBe(false); // no port
    expect(validateTunnelForm({ ...emptyTunnelForm('s', 'c'), name: 'n', localPort: 22 }).ok).toBe(
      true,
    );
  });
});
