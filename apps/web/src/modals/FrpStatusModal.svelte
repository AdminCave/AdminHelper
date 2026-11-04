<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import Dot from '$lib/components/ui/Dot.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { t } from '$lib/i18n';
  import { showError } from '$lib/stores/notifications';
  import * as api from '$lib/api/frp';
  import type { FrpStatus } from '$lib/api/types';

  interface Props {
    open: boolean;
    onClose: () => void;
  }

  let { open, onClose }: Props = $props();

  let status = $state<FrpStatus | null>(null);
  let loading = $state(false);

  // Sequence guard: repeatedly opening/refreshing can leave several status
  // requests in flight; a stale response must not overwrite a newer one.
  let refreshGen = 0;

  $effect(() => {
    if (open) {
      void refresh();
    } else {
      status = null;
    }
  });

  async function refresh() {
    const gen = ++refreshGen;
    loading = true;
    try {
      const result = await api.status();
      if (gen !== refreshGen) return;
      status = result;
    } catch (err) {
      if (gen !== refreshGen) return;
      showError(err);
    } finally {
      if (gen === refreshGen) loading = false;
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }
</script>

<Modal {open} title={$t('frp.status.title')} width="820px" {onClose}>
  {#if loading || !status}
    <p class="muted">{$t('state.loading')}</p>
  {:else if status.error}
    <p class="failed" role="alert">
      {$t('frp.status.unreachable', { error: status.error })}
    </p>
  {:else if !status.proxies || status.proxies.length === 0}
    <EmptyState message={$t('frp.status.noProxies')} framed={false} />
  {:else}
    <table class="data-table">
      <thead>
        <tr>
          <th></th>
          <th>{$t('label.name')}</th>
          <th>{$t('label.type')}</th>
          <th>{$t('frp.status.connections')}</th>
          <th>Traffic In</th>
          <th>Traffic Out</th>
        </tr>
      </thead>
      <tbody>
        {#each status.proxies as p (p.name)}
          {@const online = p.status === 'online'}
          <tr>
            <td>
              <Dot st={online ? 'ok' : 'crit'} label={online ? 'Online' : 'Offline'} />
            </td>
            <td>{p.name}</td>
            <td>{p.type || '-'}</td>
            <td>{p.curConns ?? 0}</td>
            <td>{formatBytes(p.todayTrafficIn ?? 0)}</td>
            <td>{formatBytes(p.todayTrafficOut ?? 0)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {#snippet footer()}
    <Button variant="ghost" onclick={refresh}>{$t('action.refresh')}</Button>
    <Button variant="secondary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>

<style>
  .muted {
    color: var(--text-muted);
  }
  .failed {
    color: var(--danger);
  }
</style>
