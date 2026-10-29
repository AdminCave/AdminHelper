<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { copyToClipboard } from '$lib/utils/clipboard';

  interface Props {
    open: boolean;
    value: string;
    onClose: () => void;
  }

  let { open, value, onClose }: Props = $props();

  function copy() {
    void copyToClipboard(value, 'toast.copied');
  }
</script>

<Modal {open} title={$t('modal.apikey.titleReveal')} width="520px" {onClose}>
  <p style="color:var(--text-muted);font-size:13px;margin-bottom:14px">
    {$t('modal.apikey.revealHint')}
  </p>
  <div class="key-reveal">{value}</div>
  {#snippet footer()}
    <Button variant="primary" onclick={copy}>{$t('action.copy')}</Button>
    <Button variant="ghost" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
