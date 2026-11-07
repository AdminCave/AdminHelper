<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { FileCode, Pencil, Play, Plus } from '@lucide/svelte';
  import {
    ansiblePlaybooks,
    ansibleServers,
    ansibleSelectedPlaybookId,
    ansibleSelectedServerIds,
    ansibleTargetMode,
    ansibleLoading,
    ansibleRunning,
    ansibleLoadError,
    ansibleTagGroups,
    ansibleSelectedPlaybook,
    ansibleCanRun,
    ansibleCheck,
    activateAnsible,
    reloadPlaybooks,
    selectPlaybook,
    setTargetMode,
    toggleServer,
    toggleTag,
    runPlaybook,
    setCheck,
    type AnsibleTargetMode,
  } from '$lib/stores/ansible';
  import { t } from '$lib/i18n';
  import Button from '../components/ui/Button.svelte';
  import Checkbox from '../components/ui/Checkbox.svelte';
  import Segmented from '../components/ui/Segmented.svelte';
  import Tag from '../components/ui/Tag.svelte';
  import PlaybookModal from '../components/ansible/PlaybookModal.svelte';
  import type { Playbook } from '$lib/api/types';

  onMount(() => {
    activateAnsible();
  });

  let modalOpen = $state(false);
  let modalTarget = $state<Playbook | null>(null);

  function openCreate(): void {
    modalTarget = null;
    modalOpen = true;
  }

  function openEdit(pb: Playbook): void {
    modalTarget = pb;
    modalOpen = true;
  }

  function isTagAllSelected(tag: string, ids: Set<string>): boolean {
    const list = $ansibleTagGroups[tag] ?? [];
    return list.length > 0 && list.every((s) => ids.has(s.id));
  }

  const modes = $derived([
    { value: 'servers', label: $t('ansible.mode.servers') },
    { value: 'tags', label: $t('ansible.mode.tags') },
  ]);
</script>

<div class="ansible-page">
  {#if $ansibleLoading}
    <div class="ansible-empty">{$t('ansible.loading')}</div>
  {:else if $ansibleLoadError}
    <div class="ansible-empty error">{$t('ansible.error', { message: $ansibleLoadError })}</div>
  {:else}
    <div class="ansible">
      <aside class="ansible-rail">
        <div class="ansible-rail-head">
          <span class="eyebrow">{$t('ansible.playbooks')}</span>
          <Button
            size="sm"
            variant="ghost"
            iconLeft={Plus}
            data-action="playbook-new"
            onclick={openCreate}>{$t('ansible.edit.add')}</Button
          >
        </div>
        {#if $ansiblePlaybooks.length === 0}
          <div class="ansible-empty">{$t('ansible.empty.playbooks')}</div>
        {:else}
          {#each $ansiblePlaybooks as pb (pb.id)}
            <button
              type="button"
              class="pb-item"
              class:active={$ansibleSelectedPlaybookId === pb.id}
              aria-current={$ansibleSelectedPlaybookId === pb.id ? 'true' : undefined}
              onclick={() => selectPlaybook(pb.id)}
            >
              <span class="pb-item-head">
                <FileCode size={14} />
                <span class="pb-item-name">{pb.name}</span>
              </span>
              {#if pb.description}
                <span class="pb-item-desc">{pb.description}</span>
              {/if}
              <span class="pb-item-meta">
                <span class="pb-item-file">{pb.filename}</span>
                {#each pb.tags ?? [] as tag (tag)}
                  <Tag size="sm" tone="neutral">{tag}</Tag>
                {/each}
              </span>
            </button>
          {/each}
        {/if}
      </aside>

      <section class="ansible-detail">
        {#if $ansibleSelectedPlaybook}
          {@const pb = $ansibleSelectedPlaybook}
          <header class="pb-head">
            <div class="pb-head-main">
              <h2 class="pb-name">{pb.name}</h2>
              {#if pb.description}<div class="pb-desc">{pb.description}</div>{/if}
            </div>
            <Button
              size="sm"
              variant="ghost"
              iconLeft={Pencil}
              data-action="playbook-edit"
              onclick={() => openEdit(pb)}>{$t('action.edit')}</Button
            >
            <Button
              iconLeft={Play}
              data-action="playbook-run"
              loading={$ansibleRunning}
              disabled={!$ansibleCanRun}
              onclick={() => void runPlaybook()}
              >{$ansibleRunning ? $t('ansible.run.running') : $t('ansible.run.button')}</Button
            >
          </header>

          <div class="pb-targets">
            <div class="pb-targets-head">
              <span class="eyebrow">{$t('ansible.targets')}</span>
              <Segmented
                options={modes}
                value={$ansibleTargetMode}
                label={$t('ansible.targets')}
                onChange={(v) => setTargetMode(v as AnsibleTargetMode)}
              />
            </div>

            {#if $ansibleTargetMode === 'servers'}
              {#if $ansibleServers.length === 0}
                <div class="ansible-empty">{$t('ansible.empty.servers')}</div>
              {:else}
                <div class="pb-server-list">
                  {#each $ansibleServers as srv (srv.id)}
                    <Checkbox
                      checked={$ansibleSelectedServerIds.has(srv.id)}
                      label={srv.name}
                      description={srv.hostname}
                      onChange={() => toggleServer(srv.id)}
                    />
                  {/each}
                </div>
              {/if}
            {:else if Object.keys($ansibleTagGroups).length === 0}
              <div class="ansible-empty">{$t('ansible.empty.tags')}</div>
            {:else}
              <div class="pb-tag-list">
                {#each Object.keys($ansibleTagGroups).sort() as tag (tag)}
                  <button
                    type="button"
                    class="pb-tag-chip"
                    class:active={isTagAllSelected(tag, $ansibleSelectedServerIds)}
                    aria-pressed={isTagAllSelected(tag, $ansibleSelectedServerIds)}
                    onclick={() => toggleTag(tag)}
                  >
                    {tag} ({$ansibleTagGroups[tag].length})
                  </button>
                {/each}
              </div>
            {/if}

            <Checkbox
              checked={$ansibleCheck}
              label={$t('ansible.run.check')}
              description={$t('ansible.run.checkHint')}
              onChange={setCheck}
            />

            <div class="pb-summary">
              {#if $ansibleSelectedServerIds.size > 0}
                <strong>{pb.name}</strong>
                {$t('ansible.run.on')} <strong>{$ansibleSelectedServerIds.size}</strong>
                {$t('ansible.run.servers')}
              {:else}
                {$t('ansible.hint.select')}
              {/if}
            </div>
          </div>
        {:else}
          <div class="ansible-empty">{$t('ansible.selectPrompt')}</div>
        {/if}
      </section>
    </div>
  {/if}
</div>

<PlaybookModal
  open={modalOpen}
  target={modalTarget}
  onClose={() => (modalOpen = false)}
  onSaved={() => void reloadPlaybooks()}
/>

<style>
  .ansible-page {
    container-type: inline-size;
    height: 100%;
    min-height: 0;
  }
  .ansible {
    display: grid;
    grid-template-columns: 250px minmax(0, 1fr);
    height: 100%;
    min-height: 0;
  }
  @container (min-width: 1000px) {
    .ansible {
      grid-template-columns: 320px minmax(0, 1fr);
    }
  }
  .ansible-rail {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-height: 0;
    overflow-y: auto;
    padding: 12px;
    border-right: 1px solid var(--border);
  }
  .ansible-rail-head {
    display: flex;
    align-items: center;
    padding: 4px 6px 10px;
  }
  .ansible-rail-head .eyebrow {
    flex: 1;
  }
  .eyebrow {
    color: var(--text-subtle);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .ansible-empty {
    padding: var(--sp-5) var(--sp-3);
    color: var(--text-muted);
    font-size: var(--text-sm);
    text-align: center;
  }
  .ansible-empty.error {
    color: var(--danger);
  }
  .pb-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    padding: 11px 12px;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .pb-item:hover {
    background: var(--surface-hover);
  }
  .pb-item.active {
    border-color: var(--border-strong);
    background: var(--surface-raised);
  }
  .pb-item-head {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
  }
  .pb-item-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    color: var(--text-strong);
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 500;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pb-item.active .pb-item-name {
    font-weight: 600;
  }
  .pb-item-desc {
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.4;
  }
  .pb-item-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
  }
  .pb-item-file {
    margin-right: 4px;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 10.5px;
  }
  .ansible-detail {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
  }
  .pb-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
  }
  .pb-head-main {
    flex: 1 1 200px;
    min-width: 0;
  }
  .pb-name {
    margin: 0;
    overflow: hidden;
    color: var(--text-strong);
    font-family: var(--font-mono);
    font-size: 18px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pb-desc {
    margin-top: 4px;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .pb-targets {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px 24px;
  }
  .pb-targets-head {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .pb-server-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px 18px;
  }
  .pb-tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .pb-tag-chip {
    padding: 4px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: var(--text-sm);
    cursor: pointer;
  }
  .pb-tag-chip:hover {
    background: var(--surface-hover);
  }
  .pb-tag-chip.active {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--text-strong);
  }
  .pb-summary {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .pb-summary strong {
    color: var(--text-strong);
  }
</style>
