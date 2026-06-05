// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import * as api from '$lib/api/monitoring';
import type {
  AlertLogEntry,
  AlertRule,
  AlertRuleInput,
  MonitorCheck,
  MonitorCheckInput,
  MonitoringTemplateFull,
  MonitoringTemplateInput,
} from '$lib/api/types';

const _checks = writable<MonitorCheck[]>([]);
const _alerts = writable<AlertRule[]>([]);
const _log = writable<AlertLogEntry[]>([]);
const _templates = writable<MonitoringTemplateFull[]>([]);

export const monitorChecks = {
  subscribe: _checks.subscribe,

  async refresh(): Promise<void> {
    _checks.set(await api.listChecks());
  },

  async create(data: MonitorCheckInput): Promise<MonitorCheck> {
    const created = await api.createCheck(data);
    _checks.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: MonitorCheckInput): Promise<MonitorCheck> {
    const updated = await api.updateCheck(id, data);
    _checks.update((list) => list.map((c) => (c.id === id ? { ...c, ...updated } : c)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.removeCheck(id);
    _checks.update((list) => list.filter((c) => c.id !== id));
  },

  async toggle(id: string): Promise<void> {
    const updated = await api.toggleCheck(id);
    _checks.update((list) => list.map((c) => (c.id === id ? { ...c, ...updated } : c)));
  },

  async run(id: string): Promise<void> {
    const updated = await api.runCheck(id);
    _checks.update((list) => list.map((c) => (c.id === id ? { ...c, ...updated } : c)));
  },
};

export const alertRules = {
  subscribe: _alerts.subscribe,

  async refresh(): Promise<void> {
    _alerts.set(await api.listAlerts());
  },

  async create(data: AlertRuleInput): Promise<AlertRule> {
    const created = await api.createAlert(data);
    _alerts.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: AlertRuleInput): Promise<AlertRule> {
    const updated = await api.updateAlert(id, data);
    _alerts.update((list) => list.map((r) => (r.id === id ? { ...r, ...updated } : r)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.removeAlert(id);
    _alerts.update((list) => list.filter((r) => r.id !== id));
  },

  async toggle(id: string): Promise<void> {
    const updated = await api.toggleAlert(id);
    _alerts.update((list) => list.map((r) => (r.id === id ? { ...r, ...updated } : r)));
  },
};

export const alertLog = {
  subscribe: _log.subscribe,

  async refresh(limit = 50): Promise<void> {
    _log.set(await api.alertLog(limit));
  },
};

export const monitoringTemplates = {
  subscribe: _templates.subscribe,

  async refresh(): Promise<void> {
    _templates.set(await api.listTemplatesFull());
  },

  async create(data: MonitoringTemplateInput): Promise<MonitoringTemplateFull> {
    const created = await api.createTemplate(data);
    _templates.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: MonitoringTemplateInput): Promise<MonitoringTemplateFull> {
    const updated = await api.updateTemplate(id, data);
    _templates.update((list) => list.map((t) => (t.id === id ? { ...t, ...updated } : t)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.removeTemplate(id);
    _templates.update((list) => list.filter((t) => t.id !== id));
  },
};
