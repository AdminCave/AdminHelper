<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { session } from '$lib/stores/session';
  import { logoutAndReload } from '$lib/stores/settings';
  import { t } from '$lib/i18n';
  import type { SyncMode, WorkspaceInfo } from '$lib/bridge/types';
  import ScopePill from './ScopePill.svelte';

  interface Props {
    mode: SyncMode;
    workspace: WorkspaceInfo | null;
    intervalMinutes: number;
  }

  let { mode, workspace, intervalMinutes = $bindable() }: Props = $props();
</script>

<div class="sm-section" data-scope="workspace">
  <div class="sm-section-title">{$t('settings.section.workspace')} <ScopePill /></div>
  {#if workspace}
    <div class="sm-workspace">
      <span class="workspace-dot" style:background={workspace.color} aria-hidden="true"></span>
      <strong data-testid="settings-workspace-name">{workspace.name}</strong>
    </div>
    {#if mode !== 'local'}
      <div class="field">
        <span class="field-label"
          >{$t(mode === 'sync' ? 'settings.syncUrl' : 'settings.serverUrl')}</span
        >
        <span class="sm-workspace-url" data-testid="settings-workspace-url"
          >{workspace.url ?? $t('settings.workspace.noUrl')}</span
        >
      </div>
    {/if}
    <span class="field-label"
      >{$t(mode === 'local' ? 'settings.workspace.fixedLocal' : 'settings.workspace.fixed')}</span
    >
  {/if}

  {#if mode === 'sync'}
    <label class="field">
      <span class="field-label">{$t('settings.interval')}</span>
      <input type="number" min="1" max="1440" bind:value={intervalMinutes} />
    </label>
  {:else if mode === 'server' && $session}
    <div class="sm-session-row">
      <span class="field-label">{$t('settings.loggedInAs')}</span>
      <strong>{$session.username}</strong>
      <button class="btn ghost small" onclick={() => logoutAndReload()}
        >{$t('settings.logout')}</button
      >
    </div>
  {/if}
</div>

<style>
  .sm-workspace {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  /* A value inside .field, whose global rule styles labels: no caps, spacing or
     muted colour — paths and queries are case-sensitive. */
  .sm-workspace-url {
    font-size: 13px;
    text-transform: none;
    letter-spacing: normal;
    color: var(--text);
    word-break: break-all;
  }
  .sm-session-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) 0;
  }
</style>
