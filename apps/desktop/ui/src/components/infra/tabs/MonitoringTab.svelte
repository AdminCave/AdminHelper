<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount } from 'svelte';
  import type { MonitorCheck, Server } from '$lib/api/types';
  import { monitoringApi } from '$lib/api/monitoring';
  import { statusClass } from '$lib/models/monitoring';
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import MonitorCheckModal from '../../monitoring/MonitorCheckModal.svelte';
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

  onMount(load);
</script>

<div class="mon-tab">
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
