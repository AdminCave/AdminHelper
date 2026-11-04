<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import type { HookRunResult } from '$lib/api/types';

  interface Props {
    open: boolean;
    hookName: string;
    result: HookRunResult | null;
    onClose: () => void;
  }

  let { open, hookName, result, onClose }: Props = $props();
</script>

<Modal {open} title={$t('hook.result.title', { name: hookName })} width="720px" {onClose}>
  <pre>{result ? JSON.stringify(result, null, 2) : ''}</pre>
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
    max-height: 60vh;
  }
</style>
