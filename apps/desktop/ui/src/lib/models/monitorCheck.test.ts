// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { MonitorCheck } from '$lib/api/types';
import {
  emptyCheckForm,
  checkToForm,
  formToInput,
  validateCheckForm,
  CHECK_TYPES,
  INTERVALS,
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
      description: '',
      config: { target: 'host.lan', timeout: 5 },
    });
    // config is copied, not aliased
    expect(f.config).not.toBe(config);
  });

  it('defaults missing serverId/consecutiveFails/config', () => {
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
    expect(CHECK_TYPES).toHaveLength(10);
    expect(INTERVALS).toEqual(['1m', '5m', '15m', '30m', '1h', '6h', '12h', '24h']);
    expect(SEVERITIES).toEqual(['critical', 'warning', 'info']);
  });
});
