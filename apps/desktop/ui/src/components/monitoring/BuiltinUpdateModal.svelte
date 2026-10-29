<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitoringBuiltinUpdate, MonitoringTemplateFull } from '$lib/api/types';
  import { monitoringApi } from '$lib/api/monitoring';
  import { currentSession } from '$lib/stores/session';
  import { loadTemplates } from '$lib/stores/monitoring';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { errMsg, errStatus } from '$lib/utils/errors';
  import { t } from '$lib/i18n';
  import Modal from '../ui/Modal.svelte';

  interface Props {
    // The standard template whose update to show; null keeps the modal closed.
    template: MonitoringTemplateFull | null;
    onClose: () => void;
  }
  let { template, onClose }: Props = $props();

  type Def = Readonly<Record<string, unknown>>;
  type DefStatus = 'added' | 'removed' | 'changed';
  interface FieldChange {
    field: string;
    current: unknown;
    shipped: unknown;
  }
  interface DefChange {
    key: string;
    name: string;
    status: DefStatus;
    fields: FieldChange[];
  }

  // Schema defaults of TemplateCheckDef and TemplateAlertDef in
  // apps/monitoring/app/schemas.py; keep in sync there. The server leaves a key at its
  // default out of both sides, so a side without the key holds this value. Only used
  // to show that value: whether a field changed is read from the keys themselves, so
  // a stale copy here can show a wrong value but never hide a change.
  const CHECK_DEFAULTS: Def = {
    description: null,
    config: {},
    enabled: true,
    interval: '5m',
    severity: 'critical',
    consecutive_fails: 3,
    consecutive_oks: 2,
  };
  const ALERT_DEFAULTS: Def = {
    channel_config: {},
    match_severity: null,
    cooldown_minutes: 30,
    enabled: true,
  };

  // The editor's words for the definition fields, in this order; a field the UI
  // does not know shows by its raw name, after these.
  const FIELD_LABELS = new Map<string, string>([
    ['name', 'infra.field.name'],
    ['description', 'monitoring.checkEdit.description'],
    ['check_type', 'monitoring.checkEdit.type'],
    ['channel', 'monitoring.alerts.channel'],
    ['config', 'monitoring.check.field.config'],
    ['channel_config', 'monitoring.check.field.config'],
    ['enabled', 'monitoring.check.field.enabled'],
    ['interval', 'monitoring.checkEdit.interval'],
    ['severity', 'monitoring.checkEdit.severity'],
    ['match_severity', 'monitoring.alerts.severity'],
    ['consecutive_fails', 'monitoring.checkEdit.consecutiveFails'],
    ['consecutive_oks', 'monitoring.checkEdit.consecutiveOks'],
    ['cooldown_minutes', 'monitoring.alerts.cooldown'],
  ]);
  const FIELD_ORDER = [...FIELD_LABELS.keys()];
  const STATUS_LABELS: Record<DefStatus, string> = {
    added: 'monitoring.builtinUpdate.added',
    removed: 'monitoring.builtinUpdate.removed',
    changed: 'monitoring.builtinUpdate.changed',
  };

  let update = $state<MonitoringBuiltinUpdate | null>(null);
  let applying = $state(false);
  let templateId = $derived(template?.id ?? null);
  let checkChanges = $derived(
    update
      ? diff(update.current.checkDefinitions, update.shipped.checkDefinitions, CHECK_DEFAULTS)
      : [],
  );
  let alertChanges = $derived(
    update
      ? diff(update.current.alertDefinitions, update.shipped.alertDefinitions, ALERT_DEFAULTS)
      : [],
  );

  $effect(() => {
    const id = templateId;
    update = null;
    if (id === null) return;
    // Closed or switched to another template meanwhile: the answer is stale.
    let stillOpen = true;
    void loadUpdate(id, () => stillOpen);
    return () => {
      stillOpen = false;
    };
  });

  async function loadUpdate(id: string, stillOpen: () => boolean): Promise<void> {
    const session = currentSession();
    if (!session) return;
    try {
      const data = await monitoringApi.fetchBuiltinUpdate(session, id);
      if (stillOpen()) update = data;
    } catch (err) {
      if (!stillOpen()) return;
      reportError(errMsg(err));
      onClose();
    }
  }

  async function onApply(): Promise<void> {
    const session = currentSession();
    if (!template || !update || !session || applying) return;
    applying = true;
    try {
      await monitoringApi.applyBuiltinUpdate(session, template.id);
      showStatus($t('monitoring.builtinUpdate.applied'));
      await loadTemplates();
      onClose();
    } catch (err) {
      // 409: no newer version any more, e.g. another admin took it meanwhile. The
      // list still shows the badge until it is loaded again.
      if (errStatus(err) === 409) {
        showStatus($t('monitoring.builtinUpdate.gone'));
        await loadTemplates();
        onClose();
      } else {
        reportError(errMsg(err));
      }
    } finally {
      applying = false;
    }
  }

  // JSON with sorted object keys: a config is the same in any key order, as for the
  // server's hash. A missing key and null both mean "unset".
  function canonical(value: unknown): string {
    return JSON.stringify(value ?? null, (_key, v: unknown) =>
      v !== null && typeof v === 'object' && !Array.isArray(v)
        ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
        : v,
    );
  }

  // The server sets def_id on every stored and shipped definition; the name is only a
  // fallback so a definition without one still gets a key.
  function keyOf(def: Def): string {
    return typeof def.def_id === 'string' ? def.def_id : String(def.name);
  }

  function rank(field: string): number {
    const i = FIELD_ORDER.indexOf(field);
    return i < 0 ? FIELD_ORDER.length : i;
  }

  function changedFields(current: Def, shipped: Def, defaults: Def): FieldChange[] {
    const fields = [...new Set([...Object.keys(current), ...Object.keys(shipped)])];
    return fields
      .filter((f) => f !== 'def_id' && canonical(current[f]) !== canonical(shipped[f]))
      .sort((a, b) => rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0))
      .map((f) => ({
        field: f,
        current: f in current ? current[f] : defaults[f],
        shipped: f in shipped ? shipped[f] : defaults[f],
      }));
  }

  // Only the definitions that differ: changed or removed ones in the current order,
  // then the new ones in the shipped order.
  function diff(current: readonly Def[], shipped: readonly Def[], defaults: Def): DefChange[] {
    const shippedByKey = new Map(shipped.map((d) => [keyOf(d), d]));
    const currentKeys = new Set(current.map(keyOf));
    const changes: DefChange[] = [];
    for (const def of current) {
      const key = keyOf(def);
      const next = shippedByKey.get(key);
      const fields = next ? changedFields(def, next, defaults) : [];
      if (!next) changes.push({ key, name: String(def.name), status: 'removed', fields });
      else if (fields.length > 0)
        changes.push({ key, name: String(def.name), status: 'changed', fields });
    }
    for (const def of shipped) {
      const key = keyOf(def);
      if (!currentKeys.has(key))
        changes.push({ key, name: String(def.name), status: 'added', fields: [] });
    }
    return changes;
  }

  function fieldLabel(field: string): string {
    const key = FIELD_LABELS.get(field);
    return key ? $t(key) : field;
  }

  function show(value: unknown): string {
    if (value === undefined || value === null || value === '') return '—';
    if (typeof value === 'boolean')
      return $t(value ? 'monitoring.builtinUpdate.yes' : 'monitoring.builtinUpdate.no');
    if (typeof value === 'object') return canonical(value);
    return String(value);
  }
</script>

{#snippet changeList(title: string, changes: DefChange[])}
  <div class="bu-section">
    <h3 class="bu-section-title">{title}</h3>
    {#each changes as c (c.key)}
      <div class="bu-def" data-def={c.key}>
        <div class="bu-def-head">
          <span class="bu-def-name">{c.name}</span>
          <span class="bu-pill bu-{c.status}">{$t(STATUS_LABELS[c.status])}</span>
        </div>
        {#if c.fields.length > 0}
          <table class="bu-fields">
            <thead>
              <tr>
                <td></td>
                <th scope="col">{$t('monitoring.builtinUpdate.current')}</th>
                <th scope="col">{$t('monitoring.builtinUpdate.shipped')}</th>
              </tr>
            </thead>
            <tbody>
              {#each c.fields as f (f.field)}
                <tr class="bu-field-row">
                  <th scope="row" class="bu-cell">{fieldLabel(f.field)}</th>
                  <td class="bu-cell">{show(f.current)}</td>
                  <td class="bu-cell">{show(f.shipped)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    {/each}
  </div>
{/snippet}

<Modal
  open={template !== null}
  title={$t('monitoring.builtinUpdate.title', { name: template?.name ?? '' })}
  width="640px"
  {onClose}
>
  {#if update === null}
    <div class="mon-empty">{$t('loading.generic')}</div>
  {:else}
    <div class="bu-versions">
      {$t('monitoring.builtinUpdate.versions', {
        current: update.currentVersion ?? '—',
        shipped: update.shippedVersion,
      })}
    </div>
    {#if checkChanges.length === 0 && alertChanges.length === 0}
      <div class="mon-empty bu-none">{$t('monitoring.builtinUpdate.noChanges')}</div>
    {/if}
    {#if checkChanges.length > 0}
      {@render changeList($t('monitoring.tplEdit.checkDefs'), checkChanges)}
    {/if}
    {#if alertChanges.length > 0}
      {@render changeList($t('monitoring.tplEdit.alertDefs'), alertChanges)}
    {/if}
    <p class="bu-hint">{$t('monitoring.builtinUpdate.hint')}</p>
  {/if}
  {#snippet footer()}
    <button class="btn" onclick={onClose}>{$t('action.cancel')}</button>
    <button class="btn primary" disabled={update === null || applying} onclick={onApply}>
      {$t('monitoring.builtinUpdate.apply')}
    </button>
  {/snippet}
</Modal>

<style>
  .bu-versions {
    font-size: 13px;
    color: var(--text-muted);
  }
  .bu-section {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .bu-section-title {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }
  .bu-def {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--sp-2) var(--sp-3);
  }
  .bu-def-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .bu-def-name {
    font-weight: 600;
  }
  .bu-pill {
    border-radius: var(--radius-sm);
    padding: 0 var(--sp-2);
    font-size: 11px;
    font-weight: 600;
    color: var(--bg-panel);
  }
  .bu-added {
    background: var(--success);
  }
  .bu-removed {
    background: var(--danger);
  }
  .bu-changed {
    background: var(--warning);
  }
  .bu-fields {
    width: 100%;
    margin-top: var(--sp-2);
    border-collapse: collapse;
    font-size: 12px;
  }
  .bu-fields th,
  .bu-fields td {
    text-align: left;
    padding: 2px var(--sp-2) 2px 0;
    vertical-align: top;
  }
  .bu-fields thead th {
    color: var(--text-muted);
    font-weight: 600;
  }
  .bu-fields tbody th {
    font-weight: 400;
    color: var(--text-muted);
    white-space: nowrap;
  }
  .bu-fields tbody td {
    word-break: break-word;
  }
  .bu-hint {
    margin: 0;
    font-size: 12px;
    color: var(--text-muted);
  }
</style>
