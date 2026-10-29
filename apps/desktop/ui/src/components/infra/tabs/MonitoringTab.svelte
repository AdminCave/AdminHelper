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
    TemplateSuggestion,
  } from '$lib/api/types';
  import type { AuthSession } from '$lib/bridge/types';
  import { monitoringApi } from '$lib/api/monitoring';
  import { statusClass, canRunManually, isPushOnlyCheck } from '$lib/models/monitoring';
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
  let suggestions = $state<TemplateSuggestion[]>([]);
  let checkedSlugs = $state<string[]>([]);

  // A Map, not an object literal: a code such as "constructor" must not hit an
  // inherited key. Unknown codes get the general text, never the raw code.
  const REASON_KEYS = new Map<string, string>([
    ['os:linux', 'infra.monTab.reason.linux'],
    ['os:windows', 'infra.monTab.reason.windows'],
    ['subsystem:docker', 'infra.monTab.reason.docker'],
    ['subsystem:zfs', 'infra.monTab.reason.zfs'],
    ['subsystem:proxmox', 'infra.monTab.reason.proxmox'],
  ]);

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
      // Assigning materializes checks — refresh both lists. And the suggestions: a
      // stale one for this template would fail with a 409 when assigned.
      await Promise.all([loadAssignments(), load(), loadSuggestions()]);
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
      // A removed standard template can be suggested again.
      await Promise.all([loadAssignments(), load(), loadSuggestions()]);
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      assignBusy = false;
    }
  }

  async function onRestoreChecks(templateId: string): Promise<void> {
    const s = $session;
    if (!s || assignBusy) return;
    assignBusy = true;
    try {
      await monitoringApi.restoreTemplateChecks(s, templateId, server.id);
      // Restoring creates the checks again and clears the assignment's count.
      await Promise.all([loadAssignments(), load()]);
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      assignBusy = false;
    }
  }

  async function loadSuggestions(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const list = await monitoringApi.fetchTemplateSuggestions(s, server.id);
      suggestions = Array.isArray(list) ? list : [];
    } catch {
      // Only a hint: a failed fetch, or a monitoring service without the route
      // (404), shows none and no error; the rest of the tab stays usable.
      suggestions = [];
    }
    checkedSlugs = suggestions.map((sug) => sug.slug);
  }

  // One call per checked suggestion, one after the other; stops at the first failure.
  async function actOnSuggestions(
    call: (s: AuthSession, sug: TemplateSuggestion) => Promise<unknown>,
  ): Promise<void> {
    const s = $session;
    const chosen = suggestions.filter((sug) => checkedSlugs.includes(sug.slug));
    if (!s || assignBusy || chosen.length === 0) return;
    assignBusy = true;
    try {
      for (const sug of chosen) {
        await call(s, sug);
      }
    } catch (err) {
      reportError(errMsg(err));
    }
    try {
      // Also after a failure: the calls before it went through, and a 409 means the
      // suggestion went stale (assigned meanwhile by a tag or another admin).
      await Promise.all([loadSuggestions(), loadAssignments(), load()]);
    } finally {
      assignBusy = false;
    }
  }

  function onAssignSuggestions(): Promise<void> {
    return actOnSuggestions((s, sug) =>
      monitoringApi.assignTemplate(s, sug.templateId, server.id, server.hostname, server.name),
    );
  }

  function onDismissSuggestions(): Promise<void> {
    return actOnSuggestions((s, sug) =>
      monitoringApi.dismissTemplateSuggestion(s, server.id, sug.slug),
    );
  }

  function reasonLabel(reason: string): string {
    return $t(REASON_KEYS.get(reason) ?? 'infra.monTab.reason.other');
  }

  function restoreLabel(count: number): string {
    return $t(
      count === 1 ? 'infra.monTab.restoreRemovedCheck' : 'infra.monTab.restoreRemovedChecks',
      { count },
    );
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
    void loadSuggestions();
  });
</script>

<div class="mon-tab">
  {#if suggestions.length > 0}
    <div class="tpl-suggest" role="group" aria-label={$t('infra.monTab.suggested')}>
      <span class="tpl-suggest-title">{$t('infra.monTab.suggested')}</span>
      {#each suggestions as sug (sug.slug)}
        <label class="tpl-suggest-item">
          <input type="checkbox" value={sug.slug} bind:group={checkedSlugs} disabled={assignBusy} />
          {sug.templateName}
          <span class="tpl-suggest-reason">{reasonLabel(sug.reason)}</span>
        </label>
      {/each}
      <div class="tpl-suggest-actions">
        <button
          class="btn primary small"
          disabled={assignBusy || checkedSlugs.length === 0}
          onclick={onAssignSuggestions}>{$t('infra.monTab.assign')}</button
        >
        <button
          class="btn small"
          disabled={assignBusy || checkedSlugs.length === 0}
          onclick={onDismissSuggestions}>{$t('infra.monTab.ignore')}</button
        >
      </div>
    </div>
  {/if}

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
            {#if a.removedChecks}
              <button
                class="tpl-restore"
                disabled={assignBusy}
                onclick={() => onRestoreChecks(a.templateId)}
                >{restoreLabel(a.removedChecks)}</button
              >
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
            disabled={running === c.id || !canRunManually(c)}
            title={isPushOnlyCheck(c.checkType)
              ? $t('monitoring.check.runPushOnly')
              : !c.enabled
                ? $t('monitoring.check.runDisabled')
                : undefined}
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
  .tpl-suggest {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--sp-2) var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--accent);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    font-size: var(--text-sm);
  }
  .tpl-suggest-title {
    font-weight: 600;
  }
  .tpl-suggest-item {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .tpl-suggest-reason {
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .tpl-suggest-actions {
    display: flex;
    gap: var(--sp-2);
    margin-left: auto;
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
  .tpl-restore {
    background: none;
    border: none;
    color: var(--accent);
    cursor: pointer;
    padding: 0;
    font: inherit;
    text-decoration: underline;
  }
  .tpl-restore:disabled {
    opacity: 0.5;
    cursor: not-allowed;
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
  /* Same reason as .mon-line-wrapper.disabled in app.css: the row already
     dims, so do not multiply it with the button's own disabled opacity. */
  .mon-row.disabled :global(.btn:disabled) {
    opacity: 1;
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
