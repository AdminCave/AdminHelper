<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount } from 'svelte';
  import type { FrpProvisionToken, Server } from '$lib/api/types';
  import { provisioningApi } from '$lib/api/provisioning';
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import { t, language } from '$lib/i18n';
  import { KeyRound } from '@lucide/svelte';
  import Button from '../../ui/Button.svelte';
  import Panel from '../../ui/Panel.svelte';
  import Pill from '../../ui/Pill.svelte';
  import ProvisioningDialog from '../provisioning/ProvisioningDialog.svelte';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let tokens = $state<FrpProvisionToken[]>([]);
  let loading = $state(false);
  let dialogOpen = $state(false);

  const locale = $derived($language === 'de' ? 'de-DE' : 'en-GB');

  async function loadTokens(): Promise<void> {
    const s = $session;
    if (!s) return;
    loading = true;
    try {
      tokens = await provisioningApi.listTokens(s, server.id);
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      loading = false;
    }
  }

  function fmt(iso?: string | null): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString(locale);
    } catch {
      return '';
    }
  }

  function statusOf(tk: FrpProvisionToken): { label: string; tone: 'ok' | 'accent' | 'crit' } {
    if (tk.usedAt) return { label: $t('infra.prov.used', { time: fmt(tk.usedAt) }), tone: 'ok' };
    if (tk.isValid) return { label: $t('infra.prov.active'), tone: 'accent' };
    return { label: $t('infra.prov.expired'), tone: 'crit' };
  }

  onMount(() => {
    void loadTokens();
  });
</script>

<div class="prov">
  <Panel title={$t('infra.prov.agent')}>
    <div class="prov-body">
      <p class="prov-hint">{$t('infra.prov.hint')}</p>
      <div>
        <Button
          size="sm"
          iconLeft={KeyRound}
          data-action="prov-open"
          onclick={() => (dialogOpen = true)}>{$t('infra.prov.open')}</Button
        >
      </div>
    </div>
  </Panel>

  <Panel title={$t('infra.prov.existingTokens')} pad={6}>
    {#if loading}
      <p class="muted">{$t('loading.generic')}</p>
    {:else if tokens.length === 0}
      <p class="muted">{$t('infra.prov.noTokens')}</p>
    {:else}
      <table class="prov-table">
        <thead>
          <tr>
            <th>{$t('infra.prov.colCreated')}</th>
            <th>{$t('infra.prov.colExpiry')}</th>
            <th>{$t('infra.prov.colStatus')}</th>
          </tr>
        </thead>
        <tbody>
          {#each tokens as tk (tk.id)}
            {@const st = statusOf(tk)}
            <tr>
              <td>{fmt(tk.createdAt)}</td>
              <td>{fmt(tk.expiresAt)}</td>
              <td><Pill tone={st.tone}>{st.label}</Pill></td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </Panel>
</div>

{#if dialogOpen}
  <ProvisioningDialog
    {server}
    onClose={() => (dialogOpen = false)}
    onTokenCreated={() => void loadTokens()}
  />
{/if}

<style>
  .prov {
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
  }
  .prov-body {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .prov-hint {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .muted {
    margin: 0;
    padding: 10px;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .prov-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  .prov-table th {
    text-align: left;
    color: var(--text-muted);
    font-weight: 500;
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 1px solid var(--border);
  }
  .prov-table td {
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 1px solid var(--border);
  }
</style>
