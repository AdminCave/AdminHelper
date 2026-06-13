<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { monitoringTemplates, loadTemplates } from '$lib/stores/monitoring';
  import type { MonitoringTemplateFull } from '$lib/api/types';
  import MonitoringTemplateModal from './MonitoringTemplateModal.svelte';
  import { t } from '$lib/i18n';

  let modalOpen = $state(false);
  let editing = $state<MonitoringTemplateFull | null>(null);

  onMount(() => {
    void loadTemplates();
  });

  function openNew(): void {
    editing = null;
    modalOpen = true;
  }
  function openEdit(tpl: MonitoringTemplateFull): void {
    editing = tpl;
    modalOpen = true;
  }
</script>

<div class="mon-tpl-toolbar">
  <button class="btn primary small" onclick={openNew}>+ {$t('monitoring.tplEdit.add')}</button>
</div>

<div class="mon-tpl-list">
  {#if $monitoringTemplates.length === 0}
    <div class="mon-empty">{$t('monitoring.tplEdit.empty')}</div>
  {:else}
    {#each $monitoringTemplates as tpl (tpl.id)}
      <div class="mon-tpl-card">
        <div class="mon-tpl-info">
          <div class="mon-tpl-name">{tpl.name}</div>
          <div class="mon-tpl-meta">
            {$t('monitoring.tplEdit.checkDefs')}: {tpl.checkDefinitions?.length ?? 0}
            · {$t('monitoring.tplEdit.alertDefs')}: {tpl.alertDefinitions?.length ?? 0}
            · {$t('monitoring.tplEdit.assignments')}: {tpl.assignments?.length ?? 0}
          </div>
        </div>
        <div class="mon-tpl-actions">
          <button class="btn small" onclick={() => openEdit(tpl)}>{$t('action.edit')}</button>
        </div>
      </div>
    {/each}
  {/if}
</div>

<MonitoringTemplateModal open={modalOpen} {editing} onClose={() => (modalOpen = false)} />

<style>
  .mon-tpl-toolbar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: var(--sp-3);
  }
  .mon-tpl-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .mon-tpl-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md, var(--radius-sm));
    padding: var(--sp-3) var(--sp-4);
  }
  .mon-tpl-name {
    font-weight: 600;
    font-size: 14px;
  }
  .mon-tpl-meta {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: var(--sp-1, 2px);
  }
</style>
