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
    title: string;
    content: string;
    onClose: () => void;
  }

  let { open, title, content, onClose }: Props = $props();

  function copyContent() {
    void copyToClipboard(content, 'toast.copied');
  }
</script>

<Modal {open} {title} width="820px" {onClose}>
  <div class="preview">
    <pre>{content}</pre>
    <IconButton
      icon={Copy}
      label={$t('action.copy')}
      variant="secondary"
      class="copy"
      onclick={copyContent}
    />
  </div>
  {#snippet footer()}
    <Button variant="secondary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>

<style>
  pre {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg-subtle);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
  }
  pre {
    white-space: pre-wrap;
  }
  .preview {
    position: relative;
  }
  .preview :global(.copy) {
    position: absolute;
    top: var(--space-2);
    right: var(--space-2);
  }
</style>
