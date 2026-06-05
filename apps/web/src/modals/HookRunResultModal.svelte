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
  <pre
    style="margin:0;padding:14px;font-size:13px;background:var(--bg-elevated);border-radius:6px;overflow:auto;max-height:60vh">{result
      ? JSON.stringify(result, null, 2)
      : ''}</pre>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
