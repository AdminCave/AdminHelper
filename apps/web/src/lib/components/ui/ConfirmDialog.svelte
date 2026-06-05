<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts" module>
  import { writable } from 'svelte/store';

  interface ConfirmRequest {
    message: string;
    confirmLabel: string;
    cancelLabel: string;
    resolve: (ok: boolean) => void;
  }

  const _pending = writable<ConfirmRequest | null>(null);

  export function confirmDialog(
    message: string,
    opts: { confirmLabel?: string; cancelLabel?: string } = {},
  ): Promise<boolean> {
    return new Promise((resolve) => {
      _pending.set({
        message,
        confirmLabel: opts.confirmLabel ?? 'OK',
        cancelLabel: opts.cancelLabel ?? 'Abbrechen',
        resolve,
      });
    });
  }
</script>

<script lang="ts">
  import Modal from './Modal.svelte';
  import Button from './Button.svelte';
  import { t } from '$lib/i18n';

  let request = $state<ConfirmRequest | null>(null);

  _pending.subscribe((v) => (request = v));

  function settle(ok: boolean) {
    request?.resolve(ok);
    _pending.set(null);
  }
</script>

<Modal
  open={request !== null}
  title={$t('label.status')}
  width="420px"
  onClose={() => settle(false)}
>
  <p style="margin:0">{request?.message ?? ''}</p>
  {#snippet footer()}
    <Button variant="ghost" onclick={() => settle(false)}>{request?.cancelLabel}</Button>
    <Button variant="danger" onclick={() => settle(true)}>{request?.confirmLabel}</Button>
  {/snippet}
</Modal>
