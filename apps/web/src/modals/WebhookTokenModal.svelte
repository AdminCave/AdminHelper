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
    title?: string;
    token: string;
    onClose: () => void;
  }

  let { open, title, token, onClose }: Props = $props();

  const curlExample = $derived.by(() => {
    if (!token) return '';
    // Prefer the header variant: a token in the URL path leaks into access logs, proxy
    // logs and browser history. The server accepts both /trigger (header) and
    // /trigger/{token} (path) (3.101).
    return `curl -X POST -H "X-Hook-Token: ${token}" ${window.location.origin}/api/hooks/trigger`;
  });

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      showToast($t('toast.hook.tokenCopied'));
    } catch {
      showToast('Clipboard error', 'error');
    }
  }
</script>

<Modal {open} title={title ?? $t('hook.webhookToken.title')} width="560px" {onClose}>
  <p style="color:var(--text-muted);font-size:13px;margin-bottom:14px">
    {$t('hook.webhookToken.hint')}
  </p>
  <div class="key-reveal">{token}</div>
  <div style="margin-top:14px">
    <div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">
      {$t('hook.webhookToken.triggerCmd')}
    </div>
    <code
      style="display:block;padding:8px 10px;background:var(--bg-elevated);border-radius:6px;font-size:12px;word-break:break-all"
    >
      {curlExample}
    </code>
  </div>
  {#snippet footer()}
    <Button variant="primary" onclick={copy}>{$t('action.copy')}</Button>
    <Button variant="ghost" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
