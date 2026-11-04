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
  import { shellQuote } from '$lib/utils/shell';
  import { Copy, KeyRound } from '@lucide/svelte';
  import Button from '../../ui/Button.svelte';
  import CodeBlock from '../../ui/CodeBlock.svelte';
  import Panel from '../../ui/Panel.svelte';
  import Pill from '../../ui/Pill.svelte';

  // The forms the server issues: `adminhelper_prov_` + token_urlsafe, and a uuid4. Only the
  // character class for the token, so another prefix on the server would not break the tab.
  // No leading `-`: the token must never be a value a shell or the script reads as an option.
  const TOKEN_FORM = /^[A-Za-z0-9_][A-Za-z0-9_-]*$/;
  const UUID_FORM = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  interface Props {
    server: Server;
  }
  let { server }: Props = $props();

  let tokens = $state<FrpProvisionToken[]>([]);
  let loading = $state(false);
  let scriptCommand = $state('');
  let command = $state('');
  // Shown beside the one-liner, which carries no token: agent-install.sh asks
  // for it on /dev/tty, so it stays out of shell history and the process list.
  let token = $state('');
  // The desktop's pinned CA fingerprint (root of the internal CA): handed to the
  // agent as --ca-fp so its first contact is VERIFIED instead of TOFU. The
  // desktop is the trusted courier here — it talks to the server over its own
  // pinned channel, so embedding the value in the command closes the
  // trust-on-first-use gap. Null while this device is not enrolled.
  let caFp = $state<string | null>(null);

  // The token is redeemable until it expires, so don't leave it on screen indefinitely — auto-hide (3.64).
  let hideTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleHide(ms: number): void {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      scriptCommand = '';
      command = '';
      token = '';
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
      // Both commands run as root on the target host: a value in another form
      // yields no command. The token exists on the server anyway, so the list
      // is reloaded all the same. typeof first: test() would read a missing
      // token as the word "undefined".
      if (
        typeof result.token !== 'string' ||
        !TOKEN_FORM.test(result.token) ||
        !UUID_FORM.test(server.id)
      ) {
        scriptCommand = '';
        command = '';
        token = '';
        reportError($t('infra.prov.badResponse'));
        await loadTokens();
        return;
      }
      // The agent fetches its API key, optional monitor key and optional FRP
      // bundle from the activate response in this single provision call.
      const fpArg = caFp ? ` \\\n  --ca-fp ${shellQuote(caFp)}` : '';
      // Recommended path: the install script sets up the signed package repo,
      // installs the agent and provisions it in one go.
      scriptCommand =
        `curl -fsSL https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install.sh \\\n` +
        `  | sudo bash -s -- \\\n` +
        `  --server ${shellQuote(s.serverUrl)} \\\n` +
        `  --server-id ${shellQuote(server.id)}${fpArg}`;
      token = result.token;
      // Provision-only variant for hosts that already carry the package. The
      // token is read from stdin, never an argument (process list, shell history).
      // --ca-fp supersedes --insecure; without an enrolled identity fall back
      // to the previous TOFU behaviour (only when the user opted in).
      const trust = caFp ? fpArg : $settings?.allowSelfSignedCerts ? ' \\\n  --insecure' : '';
      command =
        `sudo adminhelper-agent provision \\\n` +
        `  --url ${shellQuote(s.serverUrl)} \\\n` +
        `  --token-stdin \\\n` +
        `  --server-id ${shellQuote(server.id)}${trust}`;
      showStatus($t('infra.prov.created'));
      scheduleHide(60_000); // auto-hide the token after a minute if left untouched
      await loadTokens();
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function copyText(
    text: string,
    copied = 'infra.prov.commandCopied',
    secret = true,
  ): Promise<void> {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showStatus($t(copied));
      // Neither command carries the secret, and both ask for the token only once
      // they run: copying one must leave the token on screen.
      if (secret) scheduleHide(10_000); // it's on the clipboard now — clear the screen shortly
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

  function statusOf(tk: FrpProvisionToken): { label: string; tone: 'ok' | 'accent' | 'crit' } {
    if (tk.usedAt) return { label: $t('infra.prov.used', { time: fmt(tk.usedAt) }), tone: 'ok' };
    if (tk.isValid) return { label: $t('infra.prov.active'), tone: 'accent' };
    return { label: $t('infra.prov.expired'), tone: 'crit' };
  }

  onMount(() => {
    void loadTokens();
    pinnedCaFingerprint()
      .then((fp) => (caFp = fp))
      .catch(() => (caFp = null));
  });
</script>

{#snippet copyButton(onclick: () => void)}
  <Button size="sm" variant="secondary" iconLeft={Copy} {onclick}>{$t('action.copy')}</Button>
{/snippet}

<div class="prov">
  <Panel title={$t('infra.prov.agent')}>
    <div class="prov-body">
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
        <Button size="sm" iconLeft={KeyRound} data-action="prov-mint" onclick={createToken}
          >{$t('infra.prov.createToken')}</Button
        >
      </div>

      {#if scriptCommand}
        <div class="cmd-box" data-testid="script-command">
          <div class="cmd-head">
            <strong>{$t('infra.prov.installScript')}</strong>
            {@render copyButton(() => copyText(scriptCommand, 'infra.prov.commandCopied', false))}
          </div>
          <CodeBlock code={scriptCommand} copyable={false} />
        </div>
      {/if}

      {#if token}
        <div class="cmd-box" data-testid="prov-token">
          <div class="cmd-head">
            <span class="prov-token-hint">{$t('infra.prov.tokenPrompt')}</span>
            {@render copyButton(() => copyText(token, 'infra.prov.tokenCopied'))}
          </div>
          <code class="prov-token">{token}</code>
        </div>
      {/if}

      {#if command}
        <div class="cmd-box" data-testid="provision-command">
          <div class="cmd-head">
            <strong>{$t('infra.prov.runOnTarget')}</strong>
            {@render copyButton(() => copyText(command, 'infra.prov.commandCopied', false))}
          </div>
          <CodeBlock code={command} copyable={false} />
        </div>
      {/if}
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
  .prov-token-hint {
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .prov-token {
    font-size: var(--text-xs);
    word-break: break-all;
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
