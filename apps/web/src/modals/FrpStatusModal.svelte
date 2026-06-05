<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';
  import * as api from '$lib/api/frp';
  import type { FrpStatus } from '$lib/api/types';

  interface Props {
    open: boolean;
    onClose: () => void;
  }

  let { open, onClose }: Props = $props();

  let status = $state<FrpStatus | null>(null);
  let loading = $state(false);

  $effect(() => {
    if (open) {
      void refresh();
    } else {
      status = null;
    }
  });

  async function refresh() {
    loading = true;
    try {
      status = await api.status();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      loading = false;
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
    <p style="color:var(--text-muted)">{$t('state.loading')}</p>
  {:else if status.error}
    <p style="color:var(--danger)">
      {$t('frp.status.unreachable', { error: status.error })}
    </p>
  {:else if !status.proxies || status.proxies.length === 0}
    <p style="color:var(--text-muted)">{$t('frp.status.noProxies')}</p>
  {:else}
    <table class="data-table" style="margin:0">
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
              {#if online}
                <span style="color:#22c55e" title="Online">&#x25CF;</span>
              {:else}
                <span style="color:#ef4444" title="Offline">&#x25CF;</span>
              {/if}
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
    <Button variant="primary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
