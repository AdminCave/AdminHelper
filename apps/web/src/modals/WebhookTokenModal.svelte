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
    title?: string;
    token: string;
    /** Port of the gateway's enrollment plane, which takes triggers without a client
     * certificate (R-1687); without it the page's own origin. */
    triggerPort?: number | null;
    onClose: () => void;
  }

  let { open, title, token, triggerPort, onClose }: Props = $props();

  const curlExample = $derived.by(() => {
    if (!token) return '';
    // Prefer the header variant: a token in the URL path leaks into access logs, proxy
    // logs and browser history. The server accepts both /trigger (header) and
    // /trigger/{token} (path) (3.101).
    const base = triggerPort
      ? `https://${window.location.hostname}:${triggerPort}`
      : window.location.origin;
    return `curl -X POST -H "X-Hook-Token: ${token}" ${base}/api/hooks/trigger`;
  });

  function copy() {
    void copyToClipboard(token, 'toast.hook.tokenCopied');
  }
</script>

<Modal {open} title={title ?? $t('hook.webhookToken.title')} width="560px" {onClose}>
  <p class="hint">
    {$t('hook.webhookToken.hint')}
  </p>
  <div class="reveal">
    <div class="key-reveal">{token}</div>
    <IconButton icon={Copy} label={$t('action.copy')} variant="secondary" onclick={copy} />
  </div>
  <div class="cmd">
    <div class="cmd-label">
      {$t('hook.webhookToken.triggerCmd')}
    </div>
    <code>
      {curlExample}
    </code>
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
  .cmd {
    margin-top: var(--space-4);
  }
  .cmd-label {
    margin-bottom: var(--space-1);
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  code {
    display: block;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--bg-subtle);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    word-break: break-all;
  }
</style>
