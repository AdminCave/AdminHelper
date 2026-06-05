<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t, language } from '$lib/i18n';
  import { apikeys } from '$lib/stores/apikeys';
  import { showToast } from '$lib/stores/notifications';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import ApiKeyModal from '$modals/ApiKeyModal.svelte';
  import KeyRevealModal from '$modals/KeyRevealModal.svelte';
  import type { ApiKey } from '$lib/api/types';

  let modalOpen = $state(false);
  let revealOpen = $state(false);
  let revealValue = $state('');

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await apikeys.refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  function formatDate(iso: string | undefined): string {
    if (!iso) return '–';
    const loc = $language === 'de' ? 'de-DE' : 'en-US';
    try {
      return new Date(iso).toLocaleDateString(loc);
    } catch {
      return '–';
    }
  }

  function openCreate() {
    modalOpen = true;
  }

  function handleReveal(key: string) {
    modalOpen = false;
    revealValue = key;
    revealOpen = true;
  }

  async function handleCloseReveal() {
    revealOpen = false;
    revealValue = '';
  }

  async function removeKey(k: ApiKey) {
    if (!(await confirmDialog($t('confirm.apikey.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await apikeys.remove(k.id);
      showToast($t('toast.apikey.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.apikeys.title')}</div>
      <div class="page-subtitle">{$t('page.apikeys.subtitle')}</div>
    </div>
    <Button variant="primary" onclick={openCreate}>{$t('page.apikeys.add')}</Button>
  </div>

  <div class="panel">
    {#if $apikeys.length === 0}
      <EmptyState message={$t('page.apikeys.empty')} />
    {:else}
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('label.name')}</th>
            <th>{$t('page.apikeys.permission')}</th>
            <th>{$t('label.created')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each $apikeys as k (k.id)}
            <tr>
              <td><strong>{k.name}</strong></td>
              <td>
                <span class="badge badge-{k.permission}">
                  {k.permission === 'read_write'
                    ? $t('page.apikeys.readWrite')
                    : $t('page.apikeys.readOnly')}
                </span>
              </td>
              <td>{formatDate(k.created_at)}</td>
              <td>
                <button class="btn small ghost" onclick={() => removeKey(k)}>
                  {$t('action.delete')}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<ApiKeyModal open={modalOpen} onClose={() => (modalOpen = false)} onReveal={handleReveal} />
<KeyRevealModal open={revealOpen} value={revealValue} onClose={handleCloseReveal} />
