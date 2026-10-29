// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  hookCreatePayload,
  hookFormFrom,
  hookUpdatePayload,
  validateHookForm,
  type HookForm,
} from './hookForm';
import type { HookDetail } from '$lib/api/types';

function form(over: Partial<HookForm>): HookForm {
  return { ...hookFormFrom(null), ...over };
}

function detail(over: Partial<HookDetail>): HookDetail {
  return {
    id: 'h1',
    name: 'nightly',
    description: 'old text',
    hook_type: 'schedule',
    enabled: true,
    script: 'print(1)',
    ...over,
  } as HookDetail;
}

describe('hookFormFrom', () => {
  it('a new hook: a webhook, interval 1h, nothing else set', () => {
    expect(hookFormFrom(null)).toEqual({
      name: '',
      description: '',
      hookType: 'webhook',
      script: '',
      events: [],
      interval: '1h',
      cron: '',
    });
  });

  it('a preset interval stays a preset', () => {
    const f = hookFormFrom(detail({ schedule_interval: '6h' }));
    expect([f.interval, f.cron]).toEqual(['6h', '']);
  });

  it('an interval that is no preset is a custom cron', () => {
    const f = hookFormFrom(detail({ schedule_interval: '*/7 * * * *' }));
    expect([f.interval, f.cron]).toEqual(['custom', '*/7 * * * *']);
  });
});

describe('validateHookForm', () => {
  it('an event hook needs an event', () => {
    expect(validateHookForm(form({ hookType: 'event' }))).toBe('modal.hook.selectEvent');
    expect(validateHookForm(form({ hookType: 'event', events: ['user.created'] }))).toBeNull();
  });

  it('a custom schedule needs a cron that is not blank', () => {
    expect(validateHookForm(form({ hookType: 'schedule', interval: 'custom', cron: '   ' }))).toBe(
      'modal.hook.selectInterval',
    );
    expect(
      validateHookForm(form({ hookType: 'schedule', interval: 'custom', cron: '*/5 * * * *' })),
    ).toBeNull();
  });

  it('a webhook needs no trigger', () => {
    expect(validateHookForm(form({}))).toBeNull();
  });
});

describe('hookCreatePayload', () => {
  it('a webhook: trimmed name, a blank description as null, no trigger fields', () => {
    expect(
      hookCreatePayload(form({ name: '  deploy  ', description: '   ', script: 'echo' })),
    ).toEqual({
      name: 'deploy',
      description: null,
      hook_type: 'webhook',
      script: 'echo',
    });
  });

  it('an event hook: its events in order, no interval', () => {
    expect(hookCreatePayload(form({ name: 'e', hookType: 'event', events: ['b', 'a'] }))).toEqual({
      name: 'e',
      description: null,
      hook_type: 'event',
      script: '',
      event_triggers: ['b', 'a'],
    });
  });

  it('a schedule hook: the preset, or the custom cron trimmed; no events', () => {
    expect(hookCreatePayload(form({ name: 's', hookType: 'schedule', interval: '6h' }))).toEqual({
      name: 's',
      description: null,
      hook_type: 'schedule',
      script: '',
      schedule_interval: '6h',
    });
    expect(
      hookCreatePayload(
        form({ name: 's', hookType: 'schedule', interval: 'custom', cron: '  */5 * * * *  ' }),
      ).schedule_interval,
    ).toBe('*/5 * * * *');
  });
});

describe('hookUpdatePayload', () => {
  it('a schedule hook: no type and no events, a cleared description as null', () => {
    const f = { ...hookFormFrom(detail({ schedule_interval: '*/7 * * * *' })), description: '' };
    expect(hookUpdatePayload(f)).toEqual({
      name: 'nightly',
      description: null,
      script: 'print(1)',
      schedule_interval: '*/7 * * * *',
    });
  });

  it('an event hook: its events and no interval', () => {
    const f = hookFormFrom(detail({ hook_type: 'event', event_triggers: ['user.created'] }));
    expect(hookUpdatePayload(f)).toEqual({
      name: 'nightly',
      description: 'old text',
      script: 'print(1)',
      event_triggers: ['user.created'],
    });
  });
});
