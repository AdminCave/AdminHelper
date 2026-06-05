<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
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
    activateAnsible,
    selectPlaybook,
    setTargetMode,
    toggleServer,
    toggleTag,
    runPlaybook,
  } from '$lib/stores/ansible';
  import { t } from '$lib/i18n';

  onMount(() => {
    activateAnsible();
  });

  function isServerSelected(id: string, ids: Set<string>): boolean {
    return ids.has(id);
  }

  function isTagAllSelected(tag: string, ids: Set<string>): boolean {
    const list = $ansibleTagGroups[tag] ?? [];
    return list.length > 0 && list.every((s) => ids.has(s.id));
  }
</script>

<section class="ansible-root">
  {#if $ansibleLoading}
    <div class="ansible-empty">{$t('ansible.loading')}</div>
  {:else if $ansibleLoadError}
    <div class="ansible-empty error">{$t('ansible.error', { message: $ansibleLoadError })}</div>
  {:else}
    <!-- Step 1: Playbook -->
    <div class="ansible-step active" data-step="playbook">
      <div class="ansible-step-title">{$t('ansible.step.playbook')}</div>
      {#if $ansiblePlaybooks.length === 0}
        <div class="ansible-empty">{$t('ansible.empty.playbooks')}</div>
      {:else}
        <div class="ansible-playbook-list">
          {#each $ansiblePlaybooks as pb (pb.id)}
            <button
              type="button"
              class="ansible-playbook-card"
              class:selected={$ansibleSelectedPlaybookId === pb.id}
              onclick={() => selectPlaybook(pb.id)}
            >
              <div class="ansible-playbook-name">{pb.name}</div>
              {#if pb.description}
                <div class="ansible-playbook-desc">{pb.description}</div>
              {/if}
              <div class="ansible-playbook-meta">
                <span class="ansible-playbook-file">{pb.filename}</span>
                {#each pb.tags ?? [] as tag (tag)}
                  <span class="ansible-tag">{tag}</span>
                {/each}
              </div>
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- Step 2: Targets -->
    <div class="ansible-step" class:active={!!$ansibleSelectedPlaybookId} data-step="targets">
      <div class="ansible-step-title">{$t('ansible.step.targets')}</div>

      <div class="ansible-target-mode">
        <button
          type="button"
          class="ansible-mode-btn"
          class:active={$ansibleTargetMode === 'servers'}
          onclick={() => setTargetMode('servers')}
        >
          {$t('ansible.mode.servers')}
        </button>
        <button
          type="button"
          class="ansible-mode-btn"
          class:active={$ansibleTargetMode === 'tags'}
          onclick={() => setTargetMode('tags')}
        >
          {$t('ansible.mode.tags')}
        </button>
      </div>

      {#if $ansibleTargetMode === 'servers'}
        {#if $ansibleServers.length === 0}
          <div class="ansible-empty">{$t('ansible.empty.servers')}</div>
        {:else}
          <div class="ansible-server-list">
            {#each $ansibleServers as srv (srv.id)}
              <label class="ansible-server-row">
                <input
                  type="checkbox"
                  checked={isServerSelected(srv.id, $ansibleSelectedServerIds)}
                  onchange={() => toggleServer(srv.id)}
                />
                <div class="ansible-server-info">
                  <span class="ansible-server-name">{srv.name}</span>
                  <span class="ansible-server-host">{srv.hostname}</span>
                  {#each srv.tags ?? [] as tag (tag)}
                    <span class="ansible-tag">{tag}</span>
                  {/each}
                </div>
              </label>
            {/each}
          </div>
        {/if}
      {:else if Object.keys($ansibleTagGroups).length === 0}
        <div class="ansible-empty">{$t('ansible.empty.tags')}</div>
      {:else}
        <div class="ansible-tag-list">
          {#each Object.keys($ansibleTagGroups).sort() as tag (tag)}
            <button
              type="button"
              class="ansible-tag-chip"
              class:active={isTagAllSelected(tag, $ansibleSelectedServerIds)}
              onclick={() => toggleTag(tag)}
            >
              {tag} ({$ansibleTagGroups[tag].length})
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- Step 3: Run -->
    <div class="ansible-step" class:active={$ansibleCanRun || $ansibleRunning} data-step="run">
      <div class="ansible-step-title">{$t('ansible.step.run')}</div>
      <div class="ansible-run-summary">
        {#if $ansibleSelectedPlaybook && $ansibleSelectedServerIds.size > 0}
          <strong>{$ansibleSelectedPlaybook.name}</strong>
          {$t('ansible.run.on')} <strong>{$ansibleSelectedServerIds.size}</strong>
          {$t('ansible.run.servers')}
        {:else}
          <span class="ansible-empty">{$t('ansible.hint.select')}</span>
        {/if}
      </div>
      <button class="btn primary" disabled={!$ansibleCanRun} onclick={() => void runPlaybook()}>
        {$ansibleRunning ? $t('ansible.run.running') : $t('ansible.run.button')}
      </button>
    </div>
  {/if}
</section>

<style>
  .ansible-root {
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-5);
  }
  .ansible-step {
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--sp-4);
    background: var(--bg-panel);
    opacity: 0.55;
    transition: opacity 0.15s;
  }
  .ansible-step.active {
    opacity: 1;
  }
  .ansible-step-title {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: var(--sp-3);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .ansible-empty {
    color: var(--text-muted);
    font-size: 13px;
    padding: var(--sp-3) 0;
  }
  .ansible-empty.error {
    color: var(--danger);
  }

  /* Step 1 */
  .ansible-playbook-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: var(--sp-3);
  }
  .ansible-playbook-card {
    text-align: left;
    background: var(--bg-elev);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--sp-3);
    cursor: pointer;
    color: var(--text);
    font-family: inherit;
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    transition:
      border-color 0.12s,
      background 0.12s;
  }
  .ansible-playbook-card:hover {
    border-color: var(--accent);
  }
  .ansible-playbook-card.selected {
    border-color: var(--accent);
    background: var(--bg-accent, var(--bg-elev));
  }
  .ansible-playbook-name {
    font-weight: 600;
    font-size: 14px;
  }
  .ansible-playbook-desc {
    color: var(--text-muted);
    font-size: 12px;
  }
  .ansible-playbook-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
    align-items: center;
    margin-top: var(--sp-2);
  }
  .ansible-playbook-file {
    font-family: var(--font-mono, monospace);
    font-size: 11px;
    color: var(--text-muted);
  }

  /* Step 2 */
  .ansible-target-mode {
    display: flex;
    gap: var(--sp-2);
    margin-bottom: var(--sp-3);
  }
  .ansible-mode-btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-muted);
    padding: var(--sp-2) var(--sp-3);
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: 13px;
    font-family: inherit;
  }
  .ansible-mode-btn.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }
  .ansible-server-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    max-height: 320px;
    overflow-y: auto;
  }
  .ansible-server-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .ansible-server-info {
    display: flex;
    gap: var(--sp-2);
    align-items: center;
    flex-wrap: wrap;
    flex: 1;
  }
  .ansible-server-name {
    font-weight: 600;
    font-size: 13px;
  }
  .ansible-server-host {
    color: var(--text-muted);
    font-size: 12px;
    font-family: var(--font-mono, monospace);
  }
  .ansible-tag {
    font-size: 11px;
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    background: var(--bg-elev);
    color: var(--text-muted);
    border: 1px solid var(--border);
  }
  .ansible-tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .ansible-tag-chip {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-muted);
    padding: var(--sp-2) var(--sp-3);
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: 13px;
    font-family: inherit;
  }
  .ansible-tag-chip.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }

  /* Step 3 */
  .ansible-run-summary {
    padding: var(--sp-3) 0;
    font-size: 14px;
  }
</style>
