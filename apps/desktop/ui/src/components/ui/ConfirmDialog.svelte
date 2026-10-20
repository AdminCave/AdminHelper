<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts" module>
  import { writable, get } from 'svelte/store';

  interface ConfirmRequest {
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    resolve: (ok: boolean) => void;
  }

  const _pending = writable<ConfirmRequest | null>(null);

  export function confirmDialog(
    message: string,
    opts: { confirmLabel?: string; cancelLabel?: string } = {},
  ): Promise<boolean> {
    // Resolve any still-open dialog as cancelled before replacing it; otherwise
    // its awaiter would hang forever (the dropped Promise never resolves).
    const prev = get(_pending);
    if (prev) prev.resolve(false);
    return new Promise((resolve) => {
      _pending.set({
        message,
        confirmLabel: opts.confirmLabel,
        cancelLabel: opts.cancelLabel,
        resolve,
      });
    });
  }
</script>

<script lang="ts">
  import Modal from './Modal.svelte';
  import { t } from '$lib/i18n';
  import { context } from '$lib/stores/workspace';

  // Auto-subscribed derived value — unsubscribes automatically on destroy.
  const request = $derived($_pending);
  // In the window of a workspace a question names it (R-0431): with several windows open, it
  // says which workspace it acts on. The launcher has none.
  const workspace = $derived($context?.workspace ?? null);

  function settle(ok: boolean) {
    request?.resolve(ok);
    _pending.set(null);
  }
</script>

<Modal
  open={request !== null}
  title={$t('confirm.title')}
  width="420px"
  onClose={() => settle(false)}
>
  {#if workspace}
    <p class="confirm-workspace">
      <span class="confirm-workspace-dot" style:background={workspace.color}></span>
      <span>{workspace.name}</span>
    </p>
  {/if}
  <p class="confirm-message">{request?.message ?? ''}</p>
  {#snippet footer()}
    <button class="btn" onclick={() => settle(false)}>
      {request?.cancelLabel ?? $t('action.cancel')}
    </button>
    <button class="btn danger" onclick={() => settle(true)}>
      {request?.confirmLabel ?? $t('action.confirm')}
    </button>
  {/snippet}
</Modal>

<style>
  .confirm-workspace {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin: 0 0 var(--sp-3);
    font-weight: 600;
  }
  .confirm-workspace-dot {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }
  .confirm-message {
    margin: 0;
  }
</style>
