<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t, language } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';
  import * as api from '$lib/api/provisioning';
  import type { ProvisionToken, Server } from '$lib/api/types';

  interface Props {
    open: boolean;
    server: Server | null;
    onClose: () => void;
  }

  let { open, server, onClose }: Props = $props();

  let tokens = $state<ProvisionToken[]>([]);
  let command = $state<string>('');
  let loading = $state(false);

  const locale = $derived($language === 'de' ? 'de-DE' : 'en-GB');

  $effect(() => {
    if (open && server) {
      command = '';
      void loadTokens();
    } else {
      tokens = [];
    }
  });

  async function loadTokens() {
    if (!server) return;
    loading = true;
    try {
      tokens = await api.listProvisionTokens(server.id);
    } catch {
      showToast($t('frp.provision.loadError'), 'error');
    } finally {
      loading = false;
    }
  }

  async function createToken() {
    if (!server) return;
    try {
      const result = await api.createProvisionToken(server.id);
      const srmUrl = window.location.origin;
      // A single provision call — the agent fetches the server API key,
      // optionally a monitor key, optionally an FRP bundle from the activate response.
      command = `sudo adminhelper-agent provision \\\n  --url ${srmUrl} \\\n  --token ${result.token} \\\n  --server-id ${server.id} \\\n  --insecure`;
      showToast($t('toast.provision.created'));
      await loadTokens();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function copyCommand() {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      showToast($t('toast.provision.commandCopied'));
    } catch {
      showToast('Fehler', 'error');
    }
  }

  function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString(locale);
    } catch {
      return '';
    }
  }

  function tokenStatus(tk: ProvisionToken): { label: string; color: string } {
    if (tk.usedAt) {
      return {
        label: $t('frp.provision.used', { time: formatDateTime(tk.usedAt) }),
        color: '#22c55e',
      };
    }
    if (tk.isValid) return { label: $t('frp.provision.active'), color: 'var(--accent)' };
    return { label: $t('frp.provision.expired'), color: '#ef4444' };
  }
</script>

<Modal
  {open}
  title={$t('frp.provision.title', { name: server?.name ?? '' })}
  width="820px"
  {onClose}
>
  <div style="display:flex;flex-direction:column;gap:16px">
    <p style="margin:0;color:var(--text-muted);font-size:13px">
      {$t('frp.provision.hint')}
    </p>
    <div>
      <Button variant="primary" onclick={createToken}>
        {$t('frp.provision.createToken')}
      </Button>
    </div>
    {#if command}
      <div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">
        <div
          style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"
        >
          <strong>{$t('frp.provision.runOnTarget')}</strong>
          <button class="btn small" onclick={copyCommand}>{$t('action.copy')}</button>
        </div>
        <pre style="margin:0;font-size:12px;white-space:pre-wrap;overflow-x:auto">{command}</pre>
      </div>
    {/if}
    <div>
      <h4 style="margin:0 0 8px">{$t('frp.provision.existingTokens')}</h4>
      {#if loading}
        <p style="color:var(--text-muted)">{$t('state.loading')}</p>
      {:else if tokens.length === 0}
        <p style="color:var(--text-muted)">{$t('frp.provision.noTokens')}</p>
      {:else}
        <table class="data-table" style="margin:0;font-size:13px">
          <thead>
            <tr>
              <th>{$t('label.created')}</th>
              <th>{$t('frp.pki.expiry')}</th>
              <th>{$t('label.status')}</th>
            </tr>
          </thead>
          <tbody>
            {#each tokens as tk (tk.id)}
              {@const st = tokenStatus(tk)}
              <tr>
                <td>{formatDateTime(tk.createdAt)}</td>
                <td>{formatDateTime(tk.expiresAt)}</td>
                <td><span style="color:{st.color}">{st.label}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  </div>
  {#snippet footer()}
    <Button variant="primary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
