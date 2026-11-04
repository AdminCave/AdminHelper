<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import IconButton from '$lib/components/ui/IconButton.svelte';
  import Select from '$lib/components/ui/Select.svelte';
  import Copy from '@lucide/svelte/icons/copy';
  import { t } from '$lib/i18n';
  import { mintEnrollToken } from '$lib/api/users';
  import { formatDateTime } from '$lib/utils/datetime';
  import { copyToClipboard } from '$lib/utils/clipboard';
  import type { EnrollmentGrant } from '$lib/api/types';

  interface Props {
    open: boolean;
    username: string;
    onClose: () => void;
  }

  let { open, username, onClose }: Props = $props();

  const TTL_OPTIONS = [
    { minutes: '10', label: 'modal.enrollToken.ttl10m' },
    { minutes: '60', label: 'modal.enrollToken.ttl1h' },
    { minutes: '1440', label: 'modal.enrollToken.ttl24h' },
  ];

  // Select binds a string; the request takes the minutes as a number.
  let ttlMinutes = $state('10');
  let grant = $state<EnrollmentGrant | null>(null);
  let error = $state('');
  let submitting = $state(false);
  let mintGen = 0;

  // Every open, close and change of user starts over: closing drops the token, and a response
  // still in flight must not land in a dialog for another user — handing that token on would
  // enroll the device as the wrong user. The parent can switch `username` while the dialog
  // stays open (the row button of another user), so the effect must track it too.
  $effect(() => {
    void username;
    if (open) ttlMinutes = '10';
    mintGen += 1;
    grant = null;
    error = '';
    submitting = false;
  });

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    const gen = mintGen;
    submitting = true;
    error = '';
    try {
      const result = await mintEnrollToken(username, Number(ttlMinutes));
      if (gen !== mintGen) return;
      grant = result;
    } catch (err) {
      if (gen !== mintGen) return;
      error = err instanceof Error ? err.message : $t('error.generic');
    } finally {
      if (gen === mintGen) submitting = false;
    }
  }

  function copy() {
    if (!grant) return;
    void copyToClipboard(grant.token, 'toast.copied');
  }
</script>

<Modal {open} title={$t('modal.enrollToken.title', { username })} width="520px" {onClose}>
  {#if grant}
    <p class="hint">{$t('modal.enrollToken.hint')}</p>
    <div class="reveal">
      <div class="key-reveal">{grant.token}</div>
      <IconButton icon={Copy} label={$t('action.copy')} variant="secondary" onclick={copy} />
    </div>
    <p class="valid">
      {$t('modal.enrollToken.validUntil', { time: formatDateTime(grant.expiresAt) })}
    </p>
  {:else}
    <form onsubmit={onSubmit} id="enroll-token-form">
      <FormField label={$t('modal.enrollToken.validity')} id="etTtl">
        <Select
          bind:value={ttlMinutes}
          fullWidth
          options={TTL_OPTIONS.map((o) => ({ value: o.minutes, label: $t(o.label) }))}
        />
      </FormField>
    </form>
    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}
  {/if}
  {#snippet footer()}
    {#if grant}
      <Button variant="secondary" onclick={onClose}>{$t('action.close')}</Button>
    {:else}
      <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
      <Button
        variant="primary"
        type="submit"
        loading={submitting}
        disabled={submitting}
        form="enroll-token-form"
      >
        {$t('modal.enrollToken.issue')}
      </Button>
    {/if}
  {/snippet}
</Modal>

<style>
  .hint {
    margin-bottom: var(--space-4);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .valid {
    margin-top: var(--space-3);
    font-size: var(--text-sm);
  }
  .error {
    margin-top: var(--space-3);
    color: var(--danger);
    font-size: var(--text-sm);
  }
</style>
