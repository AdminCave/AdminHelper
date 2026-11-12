// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { MonitorCheck } from '$lib/api/types';
import { tNow } from '$lib/i18n';
import {
  emptyCheckForm,
  centralConfigFor,
  centralSensorOf,
  checkToForm,
  failsAfterTypeChange,
  formToInput,
  intervalsFor,
  learnsBaseline,
  partnersFor,
  validateCheckForm,
  CENTRAL_SENSOR_NAMES,
  CHECK_TYPES,
  INTERVALS,
  SERVER_CHECK_TYPES,
  SEVERITIES,
} from './monitorCheck';

describe('emptyCheckForm', () => {
  it('defaults to a ping check carrying the given serverId', () => {
    const f = emptyCheckForm('srv-1');
    expect(f.checkType).toBe('ping');
    expect(f.serverId).toBe('srv-1');
    expect(f.id).toBeNull();
    expect(f.interval).toBe('5m');
    expect(f.severity).toBe('critical');
    expect(f.consecutiveFails).toBe(3);
    expect(f.consecutiveOks).toBe(2);
    expect(f.config).toEqual({});
  });

  it('returns a fresh config object each call', () => {
    const a = emptyCheckForm('srv-1');
    const b = emptyCheckForm('srv-1');
    expect(a.config).not.toBe(b.config);
  });
});

describe('checkToForm', () => {
  it('maps an API check into the editable form, coercing nulls and copying config', () => {
    const config = { target: 'host.lan', timeout: 5 };
    const c: MonitorCheck = {
      id: 'm1',
      name: 'reachable',
      serverId: 'srv-1',
      checkType: 'ping',
      interval: '1m',
      severity: 'warning',
      consecutiveFails: 2,
      consecutiveOks: 4,
      description: null,
      enabled: true,
      config,
    };
    const f = checkToForm(c);
    expect(f).toEqual({
      id: 'm1',
      serverId: 'srv-1',
      name: 'reachable',
      checkType: 'ping',
      interval: '1m',
      severity: 'warning',
      consecutiveFails: 2,
      consecutiveOks: 4,
      description: '',
      config: { target: 'host.lan', timeout: 5 },
    });
    // config is copied, not aliased
    expect(f.config).not.toBe(config);
  });

  it('defaults missing serverId/consecutiveFails/consecutiveOks/config', () => {
    const c: MonitorCheck = {
      id: 'm2',
      name: 'x',
      checkType: 'tcp',
      interval: '5m',
      severity: 'critical',
      enabled: false,
    };
    const f = checkToForm(c);
    expect(f.serverId).toBe('');
    expect(f.consecutiveFails).toBe(3);
    expect(f.consecutiveOks).toBe(2);
    expect(f.config).toEqual({});
  });
});

describe('formToInput', () => {
  it('trims name/description, nulls empty description, maps to snake_case', () => {
    const input = formToInput({
      ...emptyCheckForm('srv-1'),
      name: '  reachable  ',
      checkType: 'http',
      interval: '15m',
      severity: 'info',
      consecutiveFails: 5,
      consecutiveOks: 4,
      description: '  notes  ',
      config: { url: 'https://x', method: 'GET' },
    });
    expect(input).toEqual({
      name: 'reachable',
      server_id: 'srv-1',
      check_type: 'http',
      interval: '15m',
      severity: 'info',
      consecutive_fails: 5,
      consecutive_oks: 4,
      description: 'notes',
      config: { url: 'https://x', method: 'GET' },
    });
  });

  it('emits null server_id when empty and nulls an empty description', () => {
    const input = formToInput({ ...emptyCheckForm(''), name: 'x', description: '   ' });
    expect(input.server_id).toBeNull();
    expect(input.description).toBeNull();
  });

  it('falls back consecutive_fails to 3 when zero/falsy', () => {
    const input = formToInput({ ...emptyCheckForm('srv-1'), name: 'x', consecutiveFails: 0 });
    expect(input.consecutive_fails).toBe(3);
  });

  it('falls back consecutive_oks to 2 when zero/falsy', () => {
    const input = formToInput({ ...emptyCheckForm('srv-1'), name: 'x', consecutiveOks: 0 });
    expect(input.consecutive_oks).toBe(2);
  });

  it('copies config rather than aliasing the form config', () => {
    const form = { ...emptyCheckForm('srv-1'), name: 'x', config: { target: 'a' } };
    const input = formToInput(form);
    expect(input.config).not.toBe(form.config);
    expect(input.config).toEqual({ target: 'a' });
  });
});

describe('validateCheckForm', () => {
  it('requires a name', () => {
    expect(validateCheckForm(emptyCheckForm('srv-1')).ok).toBe(false);
    expect(validateCheckForm({ ...emptyCheckForm('srv-1'), name: '  ' }).ok).toBe(false);
  });

  it('passes once a name is present', () => {
    expect(validateCheckForm({ ...emptyCheckForm('srv-1'), name: 'ok' }).ok).toBe(true);
  });
});

describe('constants', () => {
  it('expose every check type, interval and severity', () => {
    expect(CHECK_TYPES).toContain('smart_health');
    expect(CHECK_TYPES).toContain('system_state');
    expect(CHECK_TYPES).toHaveLength(12); // + disk_forecast (T29), + system_state (R-0423)
    expect(INTERVALS).toEqual(['1m', '5m', '15m', '30m', '1h', '6h', '12h', '24h']);
    expect(SEVERITIES).toEqual(['critical', 'warning', 'info']);
  });
});

// monitoring-linux-base-v2 T20 (R-0423): an OOM kill is in one report only, so
// a system_state check needs one fail in a row to report it.
describe('failsAfterTypeChange', () => {
  it('suggests 1 for system_state over the default and over a value entered', () => {
    expect(failsAfterTypeChange('ping', 'system_state', 3)).toBe(1);
    expect(failsAfterTypeChange('agent_resources', 'system_state', 5)).toBe(1);
  });

  it('goes back to 3 when system_state is left with its 1 untouched', () => {
    expect(failsAfterTypeChange('system_state', 'ping', 1)).toBe(3);
  });

  // monitoring-linux-base-v2 T28: the value from before the pick comes back.
  it('goes back to the remembered value when system_state is left with its 1 untouched', () => {
    expect(failsAfterTypeChange('system_state', 'ping', 1, 5)).toBe(5);
    expect(failsAfterTypeChange('system_state', 'ping', 2, 5)).toBe(2);
    expect(failsAfterTypeChange('ping', 'tcp', 1, 5)).toBe(1);
  });

  it('keeps a value changed under system_state', () => {
    expect(failsAfterTypeChange('system_state', 'ping', 2)).toBe(2);
  });

  it('keeps the value between other types, a 1 included', () => {
    expect(failsAfterTypeChange('ping', 'tcp', 5)).toBe(5);
    expect(failsAfterTypeChange('ping', 'tcp', 1)).toBe(1);
  });
});

// R-1224 T11: a central check — the monitoring service probes a public endpoint itself.
describe('central checks', () => {
  function probe(id: string, config: Record<string, unknown>): MonitorCheck {
    return {
      id,
      name: id,
      serverId: 'srv-1',
      checkType: 'probe',
      interval: '5m',
      severity: 'warning',
      enabled: true,
      config,
    };
  }

  function central(
    config: Record<string, unknown>,
    checkType: MonitorCheck['checkType'] = 'central',
  ) {
    return { ...probe('c1', config), checkType };
  }

  it('offers central in the check form, never in a template', () => {
    expect(SERVER_CHECK_TYPES).toEqual([...CHECK_TYPES, 'central']);
    expect(CHECK_TYPES).not.toContain('central');
    expect(CENTRAL_SENSOR_NAMES).toEqual([
      'tls',
      'dns',
      'rdap',
      'smtp',
      'imap',
      'mail_dns',
      'dnsbl',
    ]);
  });

  it('knows a sensor only by its own name', () => {
    expect(centralSensorOf({ sensor: 'dns' })).toBe('dns');
    expect(centralSensorOf({ sensor: 'toString' })).toBeNull();
    expect(centralSensorOf({ sensor: 'http' })).toBeNull();
    expect(centralSensorOf({})).toBeNull();
    expect(centralSensorOf(undefined)).toBeNull();
  });

  it('offers the intervals from the shortest one of the sensor', () => {
    expect(intervalsFor('central', { sensor: 'tls' })).toEqual([
      '15m',
      '30m',
      '1h',
      '6h',
      '12h',
      '24h',
    ]);
    expect(intervalsFor('central', { sensor: 'dns' })).toEqual(INTERVALS.slice(1));
    expect(intervalsFor('central', { sensor: 'rdap' })).toEqual(['24h']);
    expect(intervalsFor('central', { sensor: 'mail_dns' })).toEqual(['1h', '6h', '12h', '24h']);
    // An unknown sensor and the other types keep every interval.
    expect(intervalsFor('central', {})).toEqual(INTERVALS);
    expect(intervalsFor('ping', { sensor: 'rdap' })).toEqual(INTERVALS);
  });

  it('keeps the host on a sensor change and gives the port to the new sensor', () => {
    const from = {
      sensor: 'tls',
      host: 'mail.example',
      port: 8443,
      params: { x: 1 },
      pair_check_id: 'p1',
    };
    expect(centralConfigFor('smtp', from)).toEqual({
      sensor: 'smtp',
      host: 'mail.example',
      port: 25,
    });
    expect(centralConfigFor('imap', from)).toEqual({
      sensor: 'imap',
      host: 'mail.example',
      port: 993,
    });
    expect(centralConfigFor('dns', from)).toEqual({ sensor: 'dns', host: 'mail.example' });
    expect(centralConfigFor('tls', {})).toEqual({ sensor: 'tls', host: '', port: 443 });
  });

  it('pairs a sensor with the agent probes of the same service', () => {
    const checks = [
      probe('p-tls', { sensor: 'tls' }),
      probe('p-http', { sensor: 'http' }),
      probe('p-file', { sensor: 'certfile', fields: ['not_after', 'issuer'] }),
      probe('p-file-bare', { sensor: 'certfile', fields: ['issuer'] }),
      probe('p-load', { sensor: 'load' }),
      { ...probe('ping', {}), checkType: 'ping' as const },
    ];
    const ids = (sensor: Parameters<typeof partnersFor>[0]) =>
      partnersFor(sensor, checks).map((c) => c.id);
    // A certfile probe only for tls, and only when it stores not_after.
    expect(ids('tls')).toEqual(['p-tls', 'p-http', 'p-file']);
    expect(ids('smtp')).toEqual(['p-tls', 'p-http']);
    expect(ids('dns')).toEqual(['p-tls', 'p-http']);
    for (const sensor of ['rdap', 'mail_dns', 'dnsbl'] as const) expect(ids(sensor)).toEqual([]);
  });

  it('learns a baseline only as a dns check without expected addresses', () => {
    expect(learnsBaseline(central({ sensor: 'dns', host: 'example.org' }))).toBe(true);
    expect(learnsBaseline(central({ sensor: 'dns', params: { expected: ['192.0.2.1'] } }))).toBe(
      false,
    );
    expect(learnsBaseline(central({ sensor: 'tls' }))).toBe(false);
    expect(learnsBaseline(central({ sensor: 'dns' }, 'probe'))).toBe(false);
    expect(learnsBaseline(null)).toBe(false);
  });

  it('requires a host and sends it trimmed', () => {
    const form = { ...emptyCheckForm('srv-1'), name: 'web', checkType: 'central' as const };
    const noHost = validateCheckForm({ ...form, config: { sensor: 'tls', host: '  ' } });
    expect(noHost.ok).toBe(false);
    expect(noHost.message).toBe(tNow('monitoring.checkEdit.hostRequired'));
    expect(validateCheckForm({ ...form, config: { sensor: 'tls' } }).ok).toBe(false);
    const ok = { ...form, config: { sensor: 'tls', host: ' web.example ', port: 443 } };
    expect(validateCheckForm(ok).ok).toBe(true);
    expect(formToInput(ok).config).toEqual({ sensor: 'tls', host: 'web.example', port: 443 });
    // The form keeps what was typed; only the payload is trimmed.
    expect(ok.config.host).toBe(' web.example ');
    // Other types send their host as entered.
    const ping = { ...emptyCheckForm('srv-1'), name: 'p', config: { host: ' a ' } };
    expect(formToInput(ping).config.host).toBe(' a ');
  });
});
