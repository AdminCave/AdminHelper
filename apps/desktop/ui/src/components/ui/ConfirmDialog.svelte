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

  // Auto-subscribed derived value — unsubscribes automatically on destroy.
  const request = $derived($_pending);

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
  .confirm-message {
    margin: 0;
  }
</style>
