<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { apikeys } from '$lib/stores/apikeys';
  import { showToast } from '$lib/stores/notifications';
  import type { ApiKeyPermission } from '$lib/api/types';

  interface Props {
    open: boolean;
    onClose: () => void;
    onReveal: (key: string) => void;
  }

  let { open, onClose, onReveal }: Props = $props();

  let name = $state('');
  let permission = $state<ApiKeyPermission>('read');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = '';
      permission = 'read';
    }
  });

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const created = await apikeys.create({ name: name.trim(), permission });
      onReveal(created.key);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      submitting = false;
    }
  }
</script>

<Modal {open} title={$t('modal.apikey.titleNew')} width="420px" {onClose}>
  <form class="modal-form" onsubmit={onSubmit} id="apikey-form">
    <div class="field">
      <label for="akName">{$t('label.name')} *</label>
      <input id="akName" required placeholder="Client-Sync" bind:value={name} />
    </div>
    <div class="field">
      <label for="akPermission">{$t('page.apikeys.permission')}</label>
      <select id="akPermission" bind:value={permission}>
        <option value="read">{$t('page.apikeys.readOnly')}</option>
        <option value="read_write">{$t('page.apikeys.readWrite')}</option>
      </select>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('apikey-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.create')}
    </Button>
  {/snippet}
</Modal>
