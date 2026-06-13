<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import type { FrpProvisionToken, Server } from '$lib/api/types';
  import { provisioningApi } from '$lib/api/provisioning';
  import { session, settings } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t, language } from '$lib/i18n';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let tokens = $state<FrpProvisionToken[]>([]);
  let loading = $state(false);
  let command = $state('');

  const locale = $derived($language === 'de' ? 'de-DE' : 'en-GB');

  function errMsg(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

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

  async function createToken(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const result = await provisioningApi.createToken(s, server.id);
      // The agent fetches its API key, optional monitor key and optional FRP
      // bundle from the activate response in this single provision call.
      const insecure = $settings?.allowSelfSignedCerts ? ' \\\n  --insecure' : '';
      command =
        `sudo adminhelper-agent provision \\\n` +
        `  --url ${s.serverUrl} \\\n` +
        `  --token ${result.token} \\\n` +
        `  --server-id ${server.id}${insecure}`;
      showStatus($t('infra.prov.created'));
      await loadTokens();
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function copyCommand(): Promise<void> {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      showStatus($t('infra.prov.commandCopied'));
    } catch {
      reportError($t('infra.prov.copyError'));
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

  function statusOf(tk: FrpProvisionToken): { label: string; cls: string } {
    if (tk.usedAt) return { label: $t('infra.prov.used', { time: fmt(tk.usedAt) }), cls: 'used' };
    if (tk.isValid) return { label: $t('infra.prov.active'), cls: 'active' };
    return { label: $t('infra.prov.expired'), cls: 'expired' };
  }

  onMount(loadTokens);
</script>

<div class="prov">
  <p class="prov-hint">{$t('infra.prov.hint')}</p>
  <div>
    <button class="btn primary small" onclick={createToken}>{$t('infra.prov.createToken')}</button>
  </div>

  {#if command}
    <div class="cmd-box">
      <div class="cmd-head">
        <strong>{$t('infra.prov.runOnTarget')}</strong>
        <button class="btn small" onclick={copyCommand}>{$t('action.copy')}</button>
      </div>
      <pre>{command}</pre>
    </div>
  {/if}

  <div>
    <h4 class="prov-subtitle">{$t('infra.prov.existingTokens')}</h4>
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
              <td><span class="badge {st.cls}">{st.label}</span></td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<style>
  .prov {
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
  }
  .prov-hint {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .cmd-box {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--sp-3);
  }
  .cmd-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--sp-2);
  }
  .cmd-box pre {
    margin: 0;
    font-size: var(--text-xs);
    white-space: pre-wrap;
    overflow-x: auto;
  }
  .prov-subtitle {
    margin: 0 0 var(--sp-2);
    font-size: var(--text-sm);
  }
  .muted {
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
  .badge.used {
    color: var(--green);
  }
  .badge.active {
    color: var(--accent);
  }
  .badge.expired {
    color: var(--danger);
  }
</style>
