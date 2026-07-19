<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount } from 'svelte';
  import type {
    MaintenanceWindow,
    MonitorCheck,
    MonitoringTemplateFull,
    Server,
    TemplateAssignment,
  } from '$lib/api/types';
  import { monitoringApi } from '$lib/api/monitoring';
  import { statusClass } from '$lib/models/monitoring';
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import MonitorCheckModal from '../../monitoring/MonitorCheckModal.svelte';
  import MaintenanceModal from '../../monitoring/MaintenanceModal.svelte';
  import { t } from '$lib/i18n';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let items = $state<MonitorCheck[]>([]);
  let loading = $state(false);
  let modalOpen = $state(false);
  let editing = $state<MonitorCheck | null>(null);
  let running = $state<string | null>(null);
  let assignments = $state<TemplateAssignment[]>([]);
  let maintenance = $state<MaintenanceWindow[]>([]);
  let maintModalOpen = $state(false);
  let maintEditing = $state<MaintenanceWindow | null>(null);
  let templates = $state<MonitoringTemplateFull[]>([]);
  let selectedTemplateId = $state('');
  let assignBusy = $state(false);

  let availableTemplates = $derived(
    templates.filter((tpl) => !assignments.some((a) => a.templateId === tpl.id)),
  );
  let builtinById = $derived(new Map(templates.map((tpl) => [tpl.id, tpl.builtinSlug ?? null])));

  async function load(): Promise<void> {
    const s = $session;
    if (!s) return;
    loading = true;
    try {
      const all = await monitoringApi.fetchStatus(s);
      items = (Array.isArray(all) ? all : [])
        .filter((c) => c.serverId === server.id)
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      loading = false;
    }
  }

  function openNew(): void {
    editing = null;
    modalOpen = true;
  }
  function openEdit(c: MonitorCheck): void {
    editing = c;
    modalOpen = true;
  }

  async function onRun(c: MonitorCheck): Promise<void> {
    const s = $session;
    if (!s) return;
    running = c.id;
    try {
      await monitoringApi.runCheck(s, c.id);
      await load();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      running = null;
    }
  }

  async function loadAssignments(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const [a, tpls] = await Promise.all([
        monitoringApi.fetchAssignments(s, server.id),
        monitoringApi.fetchTemplates(s),
      ]);
      assignments = Array.isArray(a) ? a : [];
      templates = Array.isArray(tpls) ? tpls : [];
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function onAssign(): Promise<void> {
    const s = $session;
    if (!s || !selectedTemplateId || assignBusy) return;
    assignBusy = true;
    try {
      await monitoringApi.assignTemplate(
        s,
        selectedTemplateId,
        server.id,
        server.hostname,
        server.name,
      );
      selectedTemplateId = '';
      // Assigning materializes checks — refresh both lists.
      await Promise.all([loadAssignments(), load()]);
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      assignBusy = false;
    }
  }

  async function onUnassignTemplate(templateId: string): Promise<void> {
    const s = $session;
    if (!s || assignBusy) return;
    assignBusy = true;
    try {
      await monitoringApi.unassignTemplate(s, templateId, server.id);
      await Promise.all([loadAssignments(), load()]);
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      assignBusy = false;
    }
  }

  async function loadMaintenance(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const all = await monitoringApi.fetchMaintenance(s);
      // This server's windows plus global ones (serverId null).
      maintenance = (Array.isArray(all) ? all : []).filter(
        (w) => w.serverId == null || w.serverId === server.id,
      );
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  function maintSummary(w: MaintenanceWindow): string {
    if (w.kind === 'once') {
      const fmt = (iso: string | null | undefined) =>
        iso ? new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString() : '?';
      return `${fmt(w.startsAt)} – ${fmt(w.endsAt)}`;
    }
    const days = (w.weekdays ?? []).map((d) => $t(`monitoring.maint.day.${d}`)).join(', ');
    return `${days} ${w.startTime ?? ''} (${w.durationMinutes ?? 0} min, ${w.timezone})`;
  }

  onMount(() => {
    void load();
    void loadAssignments();
    void loadMaintenance();
  });
</script>

<div class="mon-tab">
  <div class="tpl-section">
    <h4 class="tpl-title">{$t('infra.monTab.templates')}</h4>
    {#if assignments.length === 0}
      <p class="muted">{$t('infra.monTab.noTemplates')}</p>
    {:else}
      <div class="tpl-list">
        {#each assignments as a (a.templateId)}
          <span class="tpl-pill">
            {a.templateName ?? a.templateId}
            {#if builtinById.get(a.templateId)}
              <span class="tpl-badge">{$t('infra.monTab.builtin')}</span>
            {/if}
            {#if a.source === 'tag'}
              <span class="tpl-via-tag">{$t('monitoring.tplEdit.viaTag')}</span>
            {:else}
              <button
                class="tpl-remove"
                title={$t('monitoring.tplEdit.remove')}
                aria-label={`${$t('monitoring.tplEdit.remove')} ${a.templateName ?? a.templateId}`}
                disabled={assignBusy}
                onclick={() => onUnassignTemplate(a.templateId)}>×</button
              >
            {/if}
          </span>
        {/each}
      </div>
    {/if}
    {#if availableTemplates.length > 0}
      <div class="tpl-assign">
        <select bind:value={selectedTemplateId} disabled={assignBusy}>
          <option value="">{$t('infra.monTab.selectTemplate')}</option>
          {#each availableTemplates as tpl (tpl.id)}
            <option value={tpl.id}>{tpl.name}</option>
          {/each}
        </select>
        <button class="btn small" disabled={assignBusy || !selectedTemplateId} onclick={onAssign}
          >{$t('infra.monTab.assign')}</button
        >
      </div>
    {/if}
  </div>

  <div class="tpl-section">
    <h4 class="tpl-title">{$t('monitoring.maint.title')}</h4>
    {#if maintenance.length === 0}
      <p class="muted">{$t('monitoring.maint.empty')}</p>
    {:else}
      <div class="maint-list">
        {#each maintenance as w (w.id)}
          <div class="maint-row" class:disabled={!w.enabled}>
            <span class="maint-kind"
              >{w.kind === 'once'
                ? $t('monitoring.maint.kindOnce')
                : $t('monitoring.maint.kindWeekly')}</span
            >
            <span class="maint-summary">{maintSummary(w)}</span>
            {#if w.note}<span class="maint-note">{w.note}</span>{/if}
            {#if w.serverId == null}
              <span class="tpl-badge">{$t('monitoring.maint.globalBadge')}</span>
            {/if}
            <button
              class="btn small"
              onclick={() => {
                maintEditing = w;
                maintModalOpen = true;
              }}>{$t('action.edit')}</button
            >
          </div>
        {/each}
      </div>
    {/if}
    <div>
      <button
        class="btn small"
        onclick={() => {
          maintEditing = null;
          maintModalOpen = true;
        }}>+ {$t('monitoring.maint.add')}</button
      >
    </div>
  </div>

  <div class="mon-toolbar">
    <button class="btn primary small" onclick={openNew}>+ {$t('monitoring.checkEdit.add')}</button>
  </div>

  {#if loading}
    <p class="muted">{$t('loading.generic')}</p>
  {:else if items.length === 0}
    <p class="muted">{$t('monitoring.checkEdit.empty')}</p>
  {:else}
    <div class="mon-list">
      {#each items as c (c.id)}
        <div class="mon-row" class:disabled={!c.enabled}>
          <span class="status-dot {statusClass(c.state?.status)}"></span>
          <div class="mon-info">
            <div class="mon-name">{c.name}</div>
            <div class="mon-meta">{c.checkType}</div>
          </div>
          <button
            class="btn small"
            onclick={() => onRun(c)}
            disabled={running === c.id || !c.enabled}
          >
            {$t('action.run')}
          </button>
          <button class="btn small" onclick={() => openEdit(c)}>{$t('action.edit')}</button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<MonitorCheckModal
  open={modalOpen}
  target={editing}
  serverId={server.id}
  onClose={() => (modalOpen = false)}
  onSaved={load}
/>

<MaintenanceModal
  open={maintModalOpen}
  editing={maintEditing}
  serverId={server.id}
  onClose={() => (maintModalOpen = false)}
  onSaved={() => void loadMaintenance()}
/>

<style>
  .mon-tab {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .mon-toolbar {
    display: flex;
    justify-content: flex-end;
  }
  .tpl-section {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-bottom: var(--sp-3);
    border-bottom: 1px solid var(--border);
  }
  .tpl-title {
    margin: 0;
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .tpl-list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .tpl-pill {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-2);
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 2px var(--sp-3);
    font-size: var(--text-xs);
  }
  .tpl-badge {
    background: var(--accent);
    color: var(--bg-panel);
    border-radius: var(--radius-sm);
    padding: 0 var(--sp-2);
    font-size: 10px;
    font-weight: 600;
  }
  .tpl-via-tag {
    color: var(--text-muted);
    font-size: 11px;
  }
  .tpl-remove {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 0;
    font-size: 13px;
    line-height: 1;
  }
  .tpl-remove:hover:not(:disabled) {
    color: var(--danger);
  }
  .tpl-assign {
    display: flex;
    gap: var(--sp-2);
  }
  .maint-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .maint-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
  }
  .maint-row.disabled {
    opacity: 0.55;
  }
  .maint-kind {
    font-weight: 600;
    flex-shrink: 0;
  }
  .maint-summary {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .maint-note {
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .tpl-assign select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-1) var(--sp-2);
    font-size: var(--text-sm);
    font-family: inherit;
    max-width: 260px;
  }
  .muted {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .mon-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .mon-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .mon-row.disabled {
    opacity: 0.55;
  }
  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--text-muted);
  }
  .status-dot.mon-ok {
    background: var(--success);
  }
  .status-dot.mon-warning {
    background: var(--warning);
  }
  .status-dot.mon-critical {
    background: var(--danger);
  }
  .status-dot.mon-pending,
  .status-dot.mon-unknown {
    background: var(--text-muted);
  }
  .mon-info {
    flex: 1;
    min-width: 0;
  }
  .mon-name {
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .mon-meta {
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
</style>
