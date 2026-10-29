<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { connectionsStore, loadForCurrentMode } from '$lib/stores/connections';
  import { t } from '$lib/i18n';
</script>

{#if $connectionsStore.error}
  <div class="conn-error-banner" role="alert">
    <span class="conn-error-text">
      <span>{$t('connections.loadFailed', { error: $connectionsStore.error })}</span>
      {#if $connectionsStore.items.length > 0}
        <span class="conn-error-kept">{$t('connections.loadFailed.kept')}</span>
      {/if}
    </span>
    <button class="btn small" onclick={() => void loadForCurrentMode()}>{$t('action.retry')}</button
    >
  </div>
{/if}

<style>
  .conn-error-banner {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    margin-bottom: var(--sp-4);
    border: 1px solid var(--danger);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
    font-size: 13px;
  }
  .conn-error-text {
    flex: 1;
    min-width: 0;
  }
  .conn-error-kept {
    display: block;
  }
</style>
