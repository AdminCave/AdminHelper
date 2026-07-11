<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type {
    AlertChannel,
    MonitorCheckType,
    MonitorInterval,
    MonitorSeverity,
    MonitoringTemplateFull,
    TemplateAlertDef,
    TemplateCheckDef,
  } from '$lib/api/types';
  import { CHECK_TYPES, INTERVALS, SEVERITIES } from '$lib/models/monitorCheck';
  import {
    emptyTemplateForm,
    emptyCheckDef,
    emptyAlertDef,
    templateToForm,
    formToInput,
    validateTemplateForm,
  } from '$lib/models/monitorTemplate';
  import { saveTemplate, deleteTemplate } from '$lib/stores/monitoring';
  import { reportError } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';
  import CheckConfigFields from './CheckConfigFields.svelte';

  interface Props {
    open: boolean;
    editing: MonitoringTemplateFull | null;
    onClose: () => void;
  }
  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let description = $state('');
  // Nested defs are kept as $state arrays of reactive objects so CheckConfigFields
  // can mutate def.config in place (Svelte 5 fine-grained reactivity).
  let checkDefs = $state<TemplateCheckDef[]>([]);
  let alertDefs = $state<TemplateAlertDef[]>([]);
  let saving = $state(false);
  let confirmDelete = $state(false);

  let isNew = $derived(editing === null);
  let assignments = $derived(editing?.assignments ?? []);

  $effect(() => {
    if (!open) return;
    const form = editing ? templateToForm(editing) : emptyTemplateForm();
    name = form.name;
    description = form.description;
    checkDefs = form.checkDefs;
    alertDefs = form.alertDefs;
    confirmDelete = false;
  });

  function addCheck(): void {
    checkDefs = [...checkDefs, emptyCheckDef()];
  }
  function removeCheck(idx: number): void {
    checkDefs = checkDefs.filter((_, i) => i !== idx);
  }
  function addAlert(): void {
    alertDefs = [...alertDefs, emptyAlertDef()];
  }
  function removeAlert(idx: number): void {
    alertDefs = alertDefs.filter((_, i) => i !== idx);
  }

  function recipientsVal(def: TemplateAlertDef): string {
    const r = def.channel_config.recipients;
    return Array.isArray(r) ? r.join(', ') : '';
  }
  function setRecipients(def: TemplateAlertDef, raw: string): void {
    def.channel_config = {
      recipients: raw
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    };
  }
  function setWebhookUrl(def: TemplateAlertDef, raw: string): void {
    def.channel_config = { url: raw };
  }
  function onChannelChange(def: TemplateAlertDef, channel: AlertChannel): void {
    def.channel = channel;
    def.channel_config = {};
  }

  async function onSave(): Promise<void> {
    const form = { name, description, checkDefs, alertDefs };
    const result = validateTemplateForm(form);
    if (!result.ok) {
      reportError(result.message ?? $t('monitoring.tplEdit.nameRequired'));
      return;
    }
    saving = true;
    const ok = await saveTemplate(formToInput(form), editing?.id ?? null);
    saving = false;
    if (ok) onClose();
  }

  async function onDelete(): Promise<void> {
    if (isNew || !editing) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    saving = true;
    const ok = await deleteTemplate(editing.id);
    saving = false;
    if (ok) onClose();
  }
</script>

{#if open}
  <div
    class="editor-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}
    onkeydown={(e) => e.key === 'Escape' && onClose()}
    tabindex="-1"
  >
    <div class="editor-panel">
      <div class="panel-header">
        <h2 class="panel-title">
          {isNew ? $t('monitoring.tplEdit.new') : name || $t('monitoring.tplEdit.edit')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="panel-body">
        <div class="form-grid">
          <label class="field">
            <span class="field-label">{$t('infra.field.name')}</span>
            <input type="text" bind:value={name} required />
          </label>
          <label class="field">
            <span class="field-label">{$t('monitoring.tplEdit.description')}</span>
            <input type="text" bind:value={description} />
          </label>
        </div>

        <!-- Check definitions -->
        <div class="def-section">
          <div class="def-section-head">
            <h3 class="def-section-title">{$t('monitoring.tplEdit.checkDefs')}</h3>
            <button class="btn small" onclick={addCheck}
              >+ {$t('monitoring.tplEdit.addCheck')}</button
            >
          </div>
          {#each checkDefs as def, idx (idx)}
            <div class="def-card">
              <div class="form-grid">
                <label class="field">
                  <span class="field-label">{$t('infra.field.name')}</span>
                  <input type="text" bind:value={def.name} />
                </label>
                <label class="field">
                  <span class="field-label">{$t('monitoring.checkEdit.type')}</span>
                  <select
                    value={def.check_type}
                    onchange={(e) => {
                      def.check_type = e.currentTarget.value as MonitorCheckType;
                      def.config = {};
                    }}
                  >
                    {#each CHECK_TYPES as ct (ct)}
                      <option value={ct}>{ct}</option>
                    {/each}
                  </select>
                </label>
                <label class="field">
                  <span class="field-label">{$t('monitoring.checkEdit.interval')}</span>
                  <select
                    value={def.interval}
                    onchange={(e) => (def.interval = e.currentTarget.value as MonitorInterval)}
                  >
                    {#each INTERVALS as iv (iv)}
                      <option value={iv}>{iv}</option>
                    {/each}
                  </select>
                </label>
                <label class="field">
                  <span class="field-label">{$t('monitoring.checkEdit.severity')}</span>
                  <select
                    value={def.severity}
                    onchange={(e) => (def.severity = e.currentTarget.value as MonitorSeverity)}
                  >
                    {#each SEVERITIES as sv (sv)}
                      <option value={sv}>{sv}</option>
                    {/each}
                  </select>
                </label>
                <label class="field">
                  <span class="field-label">{$t('monitoring.checkEdit.consecutiveFails')}</span>
                  <input
                    type="number"
                    min="1"
                    value={def.consecutive_fails ?? 3}
                    oninput={(e) => (def.consecutive_fails = Number(e.currentTarget.value) || 1)}
                  />
                </label>
                <CheckConfigFields checkType={def.check_type} config={def.config} />
              </div>
              <div class="def-card-actions">
                <button class="btn small danger" onclick={() => removeCheck(idx)}
                  >{$t('monitoring.tplEdit.remove')}</button
                >
              </div>
            </div>
          {/each}
        </div>

        <!-- Alert definitions -->
        <div class="def-section">
          <div class="def-section-head">
            <h3 class="def-section-title">{$t('monitoring.tplEdit.alertDefs')}</h3>
            <button class="btn small" onclick={addAlert}
              >+ {$t('monitoring.tplEdit.addAlert')}</button
            >
          </div>
          {#each alertDefs as def, idx (idx)}
            <div class="def-card">
              <div class="form-grid">
                <label class="field">
                  <span class="field-label">{$t('infra.field.name')}</span>
                  <input type="text" bind:value={def.name} />
                </label>
                <label class="field">
                  <span class="field-label">{$t('monitoring.alerts.channel')}</span>
                  <select
                    value={def.channel}
                    onchange={(e) => onChannelChange(def, e.currentTarget.value as AlertChannel)}
                  >
                    <option value="webhook">{$t('monitoring.alerts.channelWebhook')}</option>
                    <option value="email">{$t('monitoring.alerts.channelEmail')}</option>
                  </select>
                </label>
                {#if def.channel === 'webhook'}
                  <label class="field span2">
                    <span class="field-label">{$t('monitoring.alerts.webhookUrl')}</span>
                    <input
                      type="url"
                      placeholder="https://hooks.example.com/alert"
                      value={def.channel_config.url ?? ''}
                      oninput={(e) => setWebhookUrl(def, e.currentTarget.value)}
                    />
                  </label>
                {:else}
                  <label class="field span2">
                    <span class="field-label">{$t('monitoring.alertEdit.recipients')}</span>
                    <input
                      type="text"
                      placeholder="admin@example.com, ops@example.com"
                      value={recipientsVal(def)}
                      oninput={(e) => setRecipients(def, e.currentTarget.value)}
                    />
                  </label>
                {/if}
                <label class="field">
                  <span class="field-label">{$t('monitoring.alerts.severity')}</span>
                  <select
                    value={def.match_severity ?? ''}
                    onchange={(e) =>
                      (def.match_severity = (e.currentTarget.value as MonitorSeverity) || null)}
                  >
                    <option value="">{$t('monitoring.alertEdit.allSeverities')}</option>
                    <option value="critical">critical</option>
                    <option value="warning">warning</option>
                  </select>
                </label>
                <label class="field">
                  <span class="field-label">{$t('monitoring.alerts.cooldown')} (min)</span>
                  <input
                    type="number"
                    value={def.cooldown_minutes}
                    oninput={(e) => (def.cooldown_minutes = Number(e.currentTarget.value) || 30)}
                  />
                </label>
              </div>
              <div class="def-card-actions">
                <button class="btn small danger" onclick={() => removeAlert(idx)}
                  >{$t('monitoring.tplEdit.remove')}</button
                >
              </div>
            </div>
          {/each}
        </div>

        <!-- Assignments (read-only) -->
        <div class="def-section">
          <h3 class="def-section-title">{$t('monitoring.tplEdit.assignments')}</h3>
          {#if assignments.length === 0}
            <div class="mon-empty">{$t('monitoring.tplEdit.noAssignments')}</div>
          {:else}
            <div class="assign-list">
              {#each assignments as a (a.serverId)}
                <span class="assign-pill">{a.serverName ?? a.serverId}</span>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete} disabled={saving}>
            {confirmDelete ? $t('infra.server.confirmDelete') : $t('action.delete')}
          </button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onClose} disabled={saving}>{$t('action.cancel')}</button>
        <button class="btn primary" onclick={onSave} disabled={saving}>{$t('action.save')}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .editor-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: var(--sp-4);
  }
  .editor-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 760px;
    max-height: 90vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-4) var(--sp-5);
    border-bottom: 1px solid var(--border);
  }
  .panel-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .panel-body {
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-5);
  }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field.span2 {
    grid-column: span 2;
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field input,
  .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus {
    outline: 1px solid var(--accent);
  }
  .def-section {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .def-section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .def-section-title {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .def-card {
    border: 1px solid var(--border);
    border-radius: var(--radius-md, var(--radius-sm));
    padding: var(--sp-4);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .def-card-actions {
    display: flex;
    justify-content: flex-end;
  }
  .assign-list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .assign-pill {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--sp-1, 2px) var(--sp-3);
    font-size: 12px;
  }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding: var(--sp-4) var(--sp-5);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
