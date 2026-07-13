<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount, onDestroy } from 'svelte';
  import type { FrpProvisionToken, Server } from '$lib/api/types';
  import { provisioningApi } from '$lib/api/provisioning';
  import { pinnedCaFingerprint } from '$lib/bridge';
  import { session, settings } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t, language } from '$lib/i18n';

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let tokens = $state<FrpProvisionToken[]>([]);
  let loading = $state(false);
  let scriptCommand = $state('');
  let command = $state('');
  // The desktop's pinned CA fingerprint (access intermediate): handed to the
  // agent as --ca-fp so its first contact is VERIFIED instead of TOFU. The
  // desktop is the trusted courier here — it talks to the server over its own
  // pinned channel, so embedding the value in the command closes the
  // trust-on-first-use gap. Null while this device is not enrolled.
  let caFp = $state<string | null>(null);

  // The commands embed a one-time token that's redeemable until it expires, so
  // don't leave them on screen indefinitely — auto-hide (3.64).
  let hideTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleHide(ms: number): void {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      scriptCommand = '';
      command = '';
      hideTimer = null;
    }, ms);
  }
  onDestroy(() => {
    if (hideTimer) clearTimeout(hideTimer);
  });

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

  async function createToken(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const result = await provisioningApi.createToken(s, server.id);
      // The agent fetches its API key, optional monitor key and optional FRP
      // bundle from the activate response in this single provision call.
      const fpArg = caFp ? ` \\\n  --ca-fp ${caFp}` : '';
      // Recommended path: the install script sets up the signed package repo,
      // installs the agent and provisions it in one go.
      scriptCommand =
        `curl -fsSL https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install.sh \\\n` +
        `  | sudo bash -s -- \\\n` +
        `  --server ${s.serverUrl} \\\n` +
        `  --token ${result.token} \\\n` +
        `  --server-id ${server.id}${fpArg}`;
      // Provision-only variant for hosts that already carry the package.
      // --ca-fp supersedes --insecure; without an enrolled identity fall back
      // to the previous TOFU behaviour (only when the user opted in).
      const trust = caFp ? fpArg : $settings?.allowSelfSignedCerts ? ' \\\n  --insecure' : '';
      command =
        `sudo adminhelper-agent provision \\\n` +
        `  --url ${s.serverUrl} \\\n` +
        `  --token ${result.token} \\\n` +
        `  --server-id ${server.id}${trust}`;
      showStatus($t('infra.prov.created'));
      scheduleHide(60_000); // auto-hide the token after a minute if left untouched
      await loadTokens();
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function copyText(text: string): Promise<void> {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showStatus($t('infra.prov.commandCopied'));
      scheduleHide(10_000); // it's on the clipboard now — clear the screen shortly
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

  onMount(() => {
    void loadTokens();
    pinnedCaFingerprint()
      .then((fp) => (caFp = fp))
      .catch(() => (caFp = null));
  });
</script>

<div class="prov">
  <p class="prov-hint">{$t('infra.prov.hint')}</p>

  {#if caFp}
    <p class="prov-fp" data-testid="ca-fp">
      <span>{$t('infra.prov.caFp')}</span>
      <code>{caFp}</code>
    </p>
  {:else}
    <p class="prov-fp-warn" data-testid="no-ca-fp">{$t('infra.prov.noCaFp')}</p>
  {/if}

  <div>
    <button class="btn primary small" onclick={createToken}>{$t('infra.prov.createToken')}</button>
  </div>

  {#if scriptCommand}
    <div class="cmd-box" data-testid="script-command">
      <div class="cmd-head">
        <strong>{$t('infra.prov.installScript')}</strong>
        <button class="btn small" onclick={() => copyText(scriptCommand)}>
          {$t('action.copy')}
        </button>
      </div>
      <pre>{scriptCommand}</pre>
    </div>
  {/if}

  {#if command}
    <div class="cmd-box" data-testid="provision-command">
      <div class="cmd-head">
        <strong>{$t('infra.prov.runOnTarget')}</strong>
        <button class="btn small" onclick={() => copyText(command)}>{$t('action.copy')}</button>
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
  .prov-fp {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-muted);
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
    align-items: baseline;
  }
  .prov-fp code {
    font-size: var(--text-xs);
    word-break: break-all;
    color: var(--text);
  }
  .prov-fp-warn {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--danger);
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
