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
  import { untrack } from 'svelte';
  import Modal from './Modal.svelte';
  import Button from './Button.svelte';
  import { t } from '$lib/i18n';
  import { currentUser } from '$lib/stores/auth';

  // Auto-subscribed derived value (no manual subscribe + no leak): $_pending
  // reads the module store, unsubscribed automatically on destroy.
  const request = $derived($_pending);

  function settle(ok: boolean) {
    request?.resolve(ok);
    _pending.set(null);
  }

  // Escape cancels the question and goes no further. Every open Modal listens on document and the
  // one registered first takes the key (2.136), which would close a modal under the question; a
  // capture listener on window runs before all of them.
  $effect(() => {
    if (!request) return;
    const onKeydown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopImmediatePropagation();
      settle(false);
    };
    window.addEventListener('keydown', onKeydown, true);
    return () => window.removeEventListener('keydown', onKeydown, true);
  });

  // A question belongs to the session it was asked in. This dialog sits outside the login gate, so
  // once the session ends (logout, or expiry through the client's auth-failure handler: the auth
  // store drops the user) the question is cancelled; else a confirm after the next login would act
  // with the new session. Only the user is tracked: this runs when the session ends, not when a
  // question opens.
  $effect(() => {
    if ($currentUser !== null) return;
    untrack(() => {
      if (request) settle(false);
    });
  });
</script>

<Modal
  open={request !== null}
  title={$t('confirm.title')}
  width="420px"
  onClose={() => settle(false)}
>
  <p style="margin:0">{request?.message ?? ''}</p>
  {#snippet footer()}
    <Button variant="ghost" onclick={() => settle(false)}>
      {request?.cancelLabel ?? $t('action.cancel')}
    </Button>
    <Button variant="danger" onclick={() => settle(true)}>
      {request?.confirmLabel ?? $t('action.confirm')}
    </Button>
  {/snippet}
</Modal>
