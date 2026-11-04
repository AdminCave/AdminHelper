<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import IconButton from '$lib/components/ui/IconButton.svelte';
  import Copy from '@lucide/svelte/icons/copy';
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
  <p class="hint">
    {$t('modal.apikey.revealHint')}
  </p>
  <div class="reveal">
    <div class="key-reveal">{value}</div>
    <IconButton icon={Copy} label={$t('action.copy')} variant="secondary" onclick={copy} />
  </div>
  {#snippet footer()}
    <Button variant="secondary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>

<style>
  .hint {
    margin-bottom: var(--space-4);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
</style>
