<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';

  interface Props {
    open: boolean;
    title: string;
    content: string;
    onClose: () => void;
  }

  let { open, title, content, onClose }: Props = $props();

  async function copyContent() {
    try {
      await navigator.clipboard.writeText(content);
      showToast($t('toast.frp.copied'));
    } catch {
      showToast('Fehler', 'error');
    }
  }
</script>

<Modal {open} {title} width="820px" {onClose}>
  <pre
    style="margin:0;padding:12px;font-size:13px;overflow:auto;background:var(--bg-elevated);border-radius:6px;white-space:pre-wrap">{content}</pre>
  {#snippet footer()}
    <Button variant="ghost" onclick={copyContent}>{$t('action.copy')}</Button>
    <Button variant="primary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
