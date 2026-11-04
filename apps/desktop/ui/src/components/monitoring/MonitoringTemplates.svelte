<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { monitoringTemplates, loadTemplates } from '$lib/stores/monitoring';
  import type { MonitoringTemplateFull } from '$lib/api/types';
  import MonitoringTemplateModal from './MonitoringTemplateModal.svelte';
  import BuiltinUpdateModal from './BuiltinUpdateModal.svelte';
  import { Pencil, Plus } from '@lucide/svelte';
  import Button from '../ui/Button.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Pill from '../ui/Pill.svelte';
  import { t } from '$lib/i18n';

  let modalOpen = $state(false);
  let editing = $state<MonitoringTemplateFull | null>(null);
  let updating = $state<MonitoringTemplateFull | null>(null);

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
  <Button size="sm" iconLeft={Plus} data-action="template-new" onclick={openNew}
    >{$t('monitoring.tplEdit.add')}</Button
  >
</div>

{#if $monitoringTemplates.length === 0}
  <div class="mon-empty">{$t('monitoring.tplEdit.empty')}</div>
{:else}
  <div class="mon-tpl-grid">
    {#each $monitoringTemplates as tpl (tpl.id)}
      <div class="mon-tpl-card">
        <div class="mon-tpl-head">
          <span class="mon-tpl-name">{tpl.name}</span>
          {#if tpl.builtinSlug}
            <Pill>{$t('monitoring.tplEdit.builtin')}</Pill>
          {:else}
            <Pill tone="accent">{$t('monitoring.tplEdit.custom')}</Pill>
          {/if}
        </div>
        {#if tpl.description}
          <p class="mon-tpl-desc">{tpl.description}</p>
        {/if}
        {#if tpl.builtinUpdateAvailable}
          <button type="button" class="mon-tpl-update" onclick={() => (updating = tpl)}
            >{$t('monitoring.builtinUpdate.badge')}</button
          >
        {/if}
        <div class="mon-tpl-foot">
          <span class="mon-tpl-meta">
            {$t('monitoring.tplEdit.checkDefs')}: {tpl.checkDefinitions?.length ?? 0}
            · {$t('monitoring.tplEdit.alertDefs')}: {tpl.alertDefinitions?.length ?? 0}
            · {$t('monitoring.tplEdit.assignments')}: {tpl.assignments?.length ?? 0}
          </span>
          <IconButton
            size="sm"
            variant="ghost"
            icon={Pencil}
            label={$t('action.edit')}
            onclick={() => openEdit(tpl)}
          />
        </div>
      </div>
    {/each}
  </div>
{/if}

<MonitoringTemplateModal open={modalOpen} {editing} onClose={() => (modalOpen = false)} />
<BuiltinUpdateModal template={updating} onClose={() => (updating = null)} />

<style>
  .mon-tpl-toolbar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 14px;
  }
  .mon-tpl-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
  }
  .mon-tpl-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .mon-tpl-head,
  .mon-tpl-foot {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mon-tpl-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    color: var(--text-strong);
    font-size: 14.5px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-tpl-desc {
    flex: 1;
    margin: 0;
    color: var(--text-muted);
    font-size: 12.5px;
    line-height: 1.5;
  }
  .mon-tpl-update {
    align-self: flex-start;
    height: 20px;
    padding: 0 7px;
    border: 1px solid var(--warning-border);
    border-radius: var(--radius-pill);
    background: var(--warning-bg);
    color: var(--warning);
    font-family: var(--font-mono);
    font-size: 11px;
    cursor: pointer;
  }
  .mon-tpl-update:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .mon-tpl-meta {
    flex: 1;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11.5px;
  }
</style>
