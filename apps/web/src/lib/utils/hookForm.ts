// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { HookCreate, HookDetail, HookType, HookUpdate } from '$lib/api/types';
import { HOOK_INTERVAL_PRESETS } from '$lib/utils/hooks';

// The hook dialog's fields. `interval` is a preset or 'custom', then `cron` holds the expression.
export interface HookForm {
  name: string;
  description: string;
  hookType: HookType;
  script: string;
  events: string[];
  interval: string;
  cron: string;
}

export function hookFormFrom(editing: HookDetail | null): HookForm {
  const iv = editing?.schedule_interval ?? '1h';
  const preset = HOOK_INTERVAL_PRESETS.includes(iv as (typeof HOOK_INTERVAL_PRESETS)[number]);
  return {
    name: editing?.name ?? '',
    description: editing?.description ?? '',
    hookType: editing?.hook_type ?? 'webhook',
    script: editing?.script ?? '',
    events: [...(editing?.event_triggers ?? [])],
    interval: preset ? iv : 'custom',
    cron: preset ? '' : iv,
  };
}

function scheduleInterval(form: HookForm): string {
  return form.interval === 'custom' ? form.cron.trim() : form.interval;
}

// The i18n key of what is missing, or null if the form can be sent.
export function validateHookForm(
  form: HookForm,
): 'modal.hook.selectEvent' | 'modal.hook.selectInterval' | null {
  if (form.hookType === 'event' && form.events.length === 0) return 'modal.hook.selectEvent';
  if (form.hookType === 'schedule' && !scheduleInterval(form)) return 'modal.hook.selectInterval';
  return null;
}

// The trigger field only for the type that has one: an event hook its events, a schedule hook its
// interval.
function withTrigger<T extends HookCreate | HookUpdate>(form: HookForm, payload: T): T {
  if (form.hookType === 'event') payload.event_triggers = [...form.events];
  if (form.hookType === 'schedule') payload.schedule_interval = scheduleInterval(form);
  return payload;
}

export function hookCreatePayload(form: HookForm): HookCreate {
  return withTrigger(form, {
    name: form.name.trim(),
    description: form.description.trim() || null,
    hook_type: form.hookType,
    script: form.script,
  });
}

// The type of a hook does not change: an update carries no hook_type.
export function hookUpdatePayload(form: HookForm): HookUpdate {
  return withTrigger(form, {
    name: form.name.trim(),
    description: form.description.trim() || null,
    script: form.script,
  });
}
