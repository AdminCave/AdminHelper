// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { MonitoringTemplateFull } from '$lib/api/types';
import {
  emptyTemplateForm,
  emptyCheckDef,
  emptyAlertDef,
  templateToForm,
  formToInput,
  validateTemplateForm,
} from './monitorTemplate';

describe('emptyTemplateForm', () => {
  it('starts blank with empty def lists', () => {
    const f = emptyTemplateForm();
    expect(f.name).toBe('');
    expect(f.description).toBe('');
    expect(f.checkDefs).toEqual([]);
    expect(f.alertDefs).toEqual([]);
  });

  it('returns fresh arrays each call', () => {
    const a = emptyTemplateForm();
    const b = emptyTemplateForm();
    expect(a.checkDefs).not.toBe(b.checkDefs);
    expect(a.alertDefs).not.toBe(b.alertDefs);
  });
});

describe('emptyCheckDef', () => {
  it('defaults to a ping check with a fresh config', () => {
    const a = emptyCheckDef();
    expect(a.check_type).toBe('ping');
    expect(a.interval).toBe('5m');
    expect(a.severity).toBe('critical');
    expect(a.consecutive_fails).toBe(3);
    expect(a.config).toEqual({});
    const b = emptyCheckDef();
    expect(a.config).not.toBe(b.config);
  });
});

describe('emptyAlertDef', () => {
  it('defaults to a webhook alert with a fresh channel config', () => {
    const a = emptyAlertDef();
    expect(a.channel).toBe('webhook');
    expect(a.cooldown_minutes).toBe(30);
    expect(a.match_severity).toBeNull();
    expect(a.enabled).toBe(true);
    expect(a.channel_config).toEqual({});
    const b = emptyAlertDef();
    expect(a.channel_config).not.toBe(b.channel_config);
  });
});

describe('templateToForm', () => {
  it('maps a full template into the editable form, copying nested defs', () => {
    const tpl: MonitoringTemplateFull = {
      id: 't1',
      name: 'Base',
      description: 'desc',
      checkDefinitions: [
        {
          def_id: 'c1',
          name: 'reachable',
          check_type: 'ping',
          config: { target: 'host.lan' },
          interval: '1m',
          severity: 'warning',
          consecutive_fails: 2,
        },
      ],
      alertDefinitions: [
        {
          def_id: 'a1',
          name: 'ops',
          channel: 'email',
          channel_config: { recipients: ['ops@example.com'] },
          match_severity: 'critical',
          cooldown_minutes: 15,
          enabled: true,
        },
      ],
      assignments: [{ serverId: 's1', serverName: 'srv-1' }],
    };
    const f = templateToForm(tpl);
    expect(f.name).toBe('Base');
    expect(f.description).toBe('desc');
    expect(f.checkDefs).toHaveLength(1);
    expect(f.checkDefs[0].config).toEqual({ target: 'host.lan' });
    // config copied, not aliased
    expect(f.checkDefs[0].config).not.toBe(tpl.checkDefinitions![0].config);
    expect(f.alertDefs[0].channel_config).toEqual({ recipients: ['ops@example.com'] });
    expect(f.alertDefs[0].channel_config).not.toBe(tpl.alertDefinitions![0].channel_config);
  });

  it('coerces a null description and missing def lists to empties', () => {
    const tpl: MonitoringTemplateFull = { id: 't2', name: 'Empty', description: null };
    const f = templateToForm(tpl);
    expect(f.description).toBe('');
    expect(f.checkDefs).toEqual([]);
    expect(f.alertDefs).toEqual([]);
  });
});

describe('formToInput', () => {
  it('trims name/description, nulls empty description, maps to snake_case payload', () => {
    const form = {
      ...emptyTemplateForm(),
      name: '  Base  ',
      description: '  notes  ',
      checkDefs: [{ ...emptyCheckDef(), name: '  ping  ', config: { target: 'a' } }],
      alertDefs: [{ ...emptyAlertDef(), name: '  ops  ', channel_config: { url: 'https://x' } }],
    };
    const input = formToInput(form);
    expect(input.name).toBe('Base');
    expect(input.description).toBe('notes');
    expect(input.check_definitions).toHaveLength(1);
    expect(input.check_definitions[0].name).toBe('ping');
    expect(input.check_definitions[0].config).toEqual({ target: 'a' });
    expect(input.alert_definitions[0].name).toBe('ops');
    expect(input.alert_definitions[0].channel_config).toEqual({ url: 'https://x' });
  });

  it('nulls an empty description', () => {
    const input = formToInput({ ...emptyTemplateForm(), name: 'x', description: '   ' });
    expect(input.description).toBeNull();
  });

  it('copies nested config objects rather than aliasing the form', () => {
    const form = {
      ...emptyTemplateForm(),
      name: 'x',
      checkDefs: [{ ...emptyCheckDef(), name: 'c', config: { target: 'a' } }],
    };
    const input = formToInput(form);
    expect(input.check_definitions[0].config).not.toBe(form.checkDefs[0].config);
    expect(input.check_definitions[0].config).toEqual({ target: 'a' });
  });
});

describe('validateTemplateForm', () => {
  it('requires a name', () => {
    expect(validateTemplateForm(emptyTemplateForm()).ok).toBe(false);
    expect(validateTemplateForm({ ...emptyTemplateForm(), name: '  ' }).ok).toBe(false);
  });

  it('passes once a name is present', () => {
    expect(validateTemplateForm({ ...emptyTemplateForm(), name: 'ok' }).ok).toBe(true);
  });
});
