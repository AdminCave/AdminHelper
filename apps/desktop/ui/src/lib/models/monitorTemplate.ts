// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for monitoring templates. Mirrors the monitorCheck/serverConnection
// models (empty/toForm/toInput/validate). A template bundles a list of check
// definitions and alert definitions that get applied to assigned servers; the
// nested defs reuse the same MonitorCheckConfig/AlertChannelConfig shapes the API
// round-trips unchanged. Pure logic so the mapping and validation stay
// unit-testable; the per-check config fields are rendered by CheckConfigFields.

import type {
  MonitoringTemplateFull,
  MonitoringTemplateInput,
  TemplateAlertDef,
  TemplateCheckDef,
} from '$lib/api/types';
import { tNow } from '$lib/i18n';

export interface TemplateForm {
  name: string;
  description: string;
  checkDefs: TemplateCheckDef[];
  alertDefs: TemplateAlertDef[];
}

export interface ValidationResult {
  ok: boolean;
  message?: string;
}

export function emptyCheckDef(): TemplateCheckDef {
  return {
    name: '',
    check_type: 'ping',
    config: {},
    interval: '5m',
    severity: 'critical',
    consecutive_fails: 3,
  };
}

export function emptyAlertDef(): TemplateAlertDef {
  return {
    name: '',
    channel: 'webhook',
    channel_config: {},
    match_severity: null,
    cooldown_minutes: 30,
    enabled: true,
  };
}

export function emptyTemplateForm(): TemplateForm {
  return {
    name: '',
    description: '',
    checkDefs: [],
    alertDefs: [],
  };
}

export function templateToForm(tpl: MonitoringTemplateFull): TemplateForm {
  return {
    name: tpl.name,
    description: tpl.description ?? '',
    checkDefs: (tpl.checkDefinitions ?? []).map((d) => ({
      ...d,
      config: { ...d.config },
    })),
    alertDefs: (tpl.alertDefinitions ?? []).map((d) => ({
      ...d,
      channel_config: { ...d.channel_config },
    })),
  };
}

export function formToInput(form: TemplateForm): MonitoringTemplateInput {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    check_definitions: form.checkDefs.map((d) => ({
      ...d,
      name: d.name.trim(),
      config: { ...d.config },
    })),
    alert_definitions: form.alertDefs.map((d) => ({
      ...d,
      name: d.name.trim(),
      channel_config: { ...d.channel_config },
    })),
  };
}

export function validateTemplateForm(form: TemplateForm): ValidationResult {
  if (!form.name.trim()) return { ok: false, message: tNow('monitoring.tplEdit.nameRequired') };
  return { ok: true };
}
