<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { status, clearStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';
</script>

{#if $status}
  <div class="status-bar" class:error={$status.isError} role={$status.isError ? 'alert' : 'status'}>
    <span class="status-text">{$status.text}</span>
    <button class="status-close" onclick={() => clearStatus()} aria-label={$t('action.close')}
      >×</button
    >
  </div>
{/if}

<style>
  .status-bar {
    position: fixed;
    bottom: var(--sp-4);
    left: 50%;
    transform: translateX(-50%);
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--sp-2) var(--sp-4);
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    max-width: 560px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
    z-index: 80;
  }
  .status-bar.error {
    border-color: var(--error, #e05555);
    color: var(--error, #e05555);
  }
  .status-text {
    font-size: 13px;
  }
  .status-close {
    background: transparent;
    border: 0;
    color: inherit;
    cursor: pointer;
    font-size: 18px;
    line-height: 1;
    padding: 0;
  }
</style>
