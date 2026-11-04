<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import Select from '$lib/components/ui/Select.svelte';
  import { t } from '$lib/i18n';
  import { apikeys } from '$lib/stores/apikeys';
  import { showError } from '$lib/stores/notifications';
  import type { ApiKeyPermission } from '$lib/api/types';

  interface Props {
    open: boolean;
    onClose: () => void;
    onReveal: (key: string) => void;
  }

  let { open, onClose, onReveal }: Props = $props();

  let name = $state('');
  // Select binds a string; the two options are exactly the ApiKeyPermission values.
  let permission = $state<string>('read');
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
      const created = await apikeys.create({
        name: name.trim(),
        permission: permission as ApiKeyPermission,
      });
      onReveal(created.key);
    } catch (err) {
      showError(err);
    } finally {
      submitting = false;
    }
  }
</script>

<Modal {open} title={$t('modal.apikey.titleNew')} width="420px" {onClose}>
  <form class="form" onsubmit={onSubmit} id="apikey-form">
    <FormField label={$t('label.name')} id="akName" required>
      <Input required placeholder="Client-Sync" bind:value={name} />
    </FormField>
    <FormField label={$t('page.apikeys.permission')} id="akPermission">
      <Select
        bind:value={permission}
        fullWidth
        options={[
          { value: 'read', label: $t('page.apikeys.readOnly') },
          { value: 'read_write', label: $t('page.apikeys.readWrite') },
        ]}
      />
    </FormField>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      loading={submitting}
      disabled={submitting}
      form="apikey-form"
    >
      {$t('action.create')}
    </Button>
  {/snippet}
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
</style>
