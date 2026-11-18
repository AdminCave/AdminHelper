<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type {
    ProvisionAction,
    ProvisionPlatform,
    ProvisionPlatformId,
    ProvisionPort,
    Server,
  } from '$lib/api/types';
  import { provisioningApi } from '$lib/api/provisioning';
  import { pinnedCaFingerprint } from '$lib/bridge';
  import { session, settings } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';
  import { errMsg } from '$lib/utils/errors';
  import { buildCommand, TOKEN_FORM } from '$lib/provisioning/command';
  import { Copy, KeyRound } from '@lucide/svelte';
  import Button from '../../ui/Button.svelte';
  import Callout from '../../ui/Callout.svelte';
  import CodeBlock from '../../ui/CodeBlock.svelte';
  import Modal from '../../ui/Modal.svelte';
  import Select from '../../ui/Select.svelte';
  import Switch from '../../ui/Switch.svelte';
  import Tabs from '../../ui/Tabs.svelte';

  interface Props {
    server: Server;
    onClose: () => void;
    // A token now exists on the server: the tab reloads its list.
    onTokenCreated?: () => void;
  }
  let { server, onClose, onTokenCreated }: Props = $props();

  // What this desktop can label; a platform or action the server adds later is left out
  // rather than shown under a raw ID.
  const PLATFORMS: readonly ProvisionPlatformId[] = ['linux', 'windows', 'freebsd', 'opnsense'];
  const ACTIONS: readonly ProvisionAction[] = ['install', 'update', 'reregister', 'remove'];

  let catalog = $state<ProvisionPlatform[] | null>(null);
  let catalogError = $state<string | null>(null);
  let platformId = $state('');
  let action = $state<string>('install');
  let automation = $state(false);
  let token = $state('');
  // The desktop's pinned CA fingerprint, handed to the agent as --ca-fp so its first contact
  // is verified instead of trust-on-first-use. Null while this device is not enrolled.
  let caFp = $state<string | null>(null);

  const platform = $derived(catalog?.find((p) => p.id === platformId) ?? null);
  const actions = $derived(
    platform ? ACTIONS.filter((a) => platform.commands.some((c) => c.action === a)) : [],
  );
  const activeAction = $derived(actions.includes(action as ProvisionAction) ? action : actions[0]);
  const spec = $derived(platform?.commands.find((c) => c.action === activeAction) ?? null);
  const needsToken = $derived(spec?.args.some((a) => a.value === 'token') ?? false);
  const command = $derived(
    spec && $session
      ? buildCommand(
          spec,
          {
            serverUrl: $session.serverUrl,
            serverId: server.id,
            caFp,
            token: token || null,
            allowInsecure: $settings?.allowSelfSignedCerts ?? false,
          },
          automation && needsToken,
        )
      : null,
  );

  // The token is redeemable until it expires, so it does not stay on screen: hidden after a
  // minute, or shortly after it went to the clipboard.
  let hideTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleHide(ms: number): void {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      token = '';
      hideTimer = null;
    }, ms);
  }
  onDestroy(() => {
    if (hideTimer) clearTimeout(hideTimer);
  });

  function preselect(list: ProvisionPlatform[]): string {
    const os = server.osType ?? '';
    if (list.some((p) => p.id === os)) return os;
    return (list.find((p) => p.available) ?? list[0])?.id ?? '';
  }

  async function loadCatalog(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const resp = await provisioningApi.platforms(s);
      const known = resp.platforms.filter((p) => PLATFORMS.includes(p.id as ProvisionPlatformId));
      catalog = known;
      platformId = preselect(known);
    } catch (err) {
      catalogError = errMsg(err);
    }
  }

  async function createToken(): Promise<void> {
    const s = $session;
    if (!s) return;
    try {
      const result = await provisioningApi.createToken(s, server.id);
      // typeof first: test() would read a missing token as the word "undefined".
      if (typeof result.token !== 'string' || !TOKEN_FORM.test(result.token)) {
        token = '';
        reportError($t('infra.prov.badResponse'));
      } else {
        token = result.token;
        showStatus($t('infra.prov.created'));
        scheduleHide(60_000);
      }
      // The token exists on the server either way.
      onTokenCreated?.();
    } catch (err) {
      reportError(errMsg(err));
    }
  }

  async function copyText(text: string, copied: string, secret: boolean): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      showStatus($t(copied));
      // A secret on the clipboard leaves the screen shortly after; a command without the
      // token keeps it there, the command asks for it when it runs.
      if (secret) scheduleHide(10_000);
    } catch {
      reportError($t('infra.prov.copyError'));
    }
  }

  function portLabel(port: ProvisionPort): string {
    const text = `${port.port}: ${$t(`infra.prov.port.${port.purpose}`)}`;
    return port.tunnelOnly ? `${text} (${$t('infra.prov.tunnelOnly')})` : text;
  }

  function platformLabel(p: ProvisionPlatform): string {
    const name = $t(`infra.prov.platform.${p.id}`);
    return p.available ? name : $t('infra.prov.unavailable', { name });
  }

  onMount(() => {
    void loadCatalog();
    pinnedCaFingerprint()
      .then((fp) => (caFp = fp))
      .catch(() => (caFp = null));
  });
</script>

{#snippet copyButton(onclick: () => void)}
  <Button size="sm" variant="secondary" iconLeft={Copy} {onclick}>{$t('action.copy')}</Button>
{/snippet}

<Modal open title={$t('infra.prov.dialogTitle', { name: server.name })} width="720px" {onClose}>
  <div class="prov-dialog">
    {#if catalogError !== null}
      <Callout tone="danger">{$t('infra.prov.catalogError', { message: catalogError })}</Callout>
    {:else if catalog === null}
      <p class="muted">{$t('loading.generic')}</p>
    {:else}
      <div class="row">
        <label for="prov-platform">{$t('infra.prov.platform')}</label>
        <Select
          id="prov-platform"
          size="sm"
          value={platformId}
          options={catalog.map((p) => ({ value: p.id, label: platformLabel(p) }))}
          onChange={(v) => (platformId = v)}
        />
      </div>

      {#if platform}
        {#if !platform.available}
          <div data-testid="prov-unavailable">
            <Callout tone="warning"
              >{$t(`infra.prov.reason.${platform.reason ?? 'noRepo'}`)}</Callout
            >
          </div>
        {:else}
          {#if platform.reason}
            <Callout tone="info">{$t(`infra.prov.reason.${platform.reason}`)}</Callout>
          {/if}

          <div class="prereq" data-testid="prov-prereq">
            <div>
              <strong>{$t('infra.prov.systems')}</strong>
              <ul>
                {#each platform.prerequisites.systems as system (system)}<li>{system}</li>{/each}
              </ul>
            </div>
            <div>
              <strong>{$t('infra.prov.ports')}</strong>
              <ul>
                {#each platform.prerequisites.ports as port (port.port)}
                  <li>{portLabel(port)}</li>
                {/each}
              </ul>
            </div>
          </div>

          {#if caFp}
            <p class="prov-fp" data-testid="ca-fp">
              <span>{$t('infra.prov.caFp')}</span>
              <code>{caFp}</code>
            </p>
          {:else}
            <p class="prov-fp-warn" data-testid="no-ca-fp">{$t('infra.prov.noCaFp')}</p>
          {/if}

          <Tabs
            tabs={actions.map((a) => ({ id: a, label: $t(`infra.prov.action.${a}`) }))}
            value={activeAction}
            label={$t('infra.prov.platform')}
            onChange={(id) => (action = id)}
          />

          {#if needsToken}
            <div class="row">
              <Button size="sm" iconLeft={KeyRound} data-action="prov-mint" onclick={createToken}
                >{$t('infra.prov.createToken')}</Button
              >
              <Switch
                size="sm"
                checked={automation}
                label={$t('infra.prov.automation')}
                onChange={(on) => (automation = on)}
              />
            </div>
            {#if automation}
              <div data-testid="prov-automation-warn">
                <Callout tone="warning">{$t('infra.prov.automationWarn')}</Callout>
              </div>
            {/if}
          {/if}

          {#if command}
            <div class="cmd-box" data-testid="provision-command">
              <div class="cmd-head">
                <strong>{$t('infra.prov.command')}</strong>
                {@render copyButton(() =>
                  copyText(command, 'infra.prov.commandCopied', automation && needsToken),
                )}
              </div>
              <CodeBlock code={command} copyable={false} />
            </div>
          {:else if automation && needsToken && !token}
            <p class="muted" data-testid="prov-need-token">{$t('infra.prov.needToken')}</p>
          {:else}
            <div data-testid="prov-no-command">
              <Callout tone="danger">{$t('infra.prov.noCommand')}</Callout>
            </div>
          {/if}

          {#if token && needsToken && !automation}
            <div class="cmd-box" data-testid="prov-token">
              <div class="cmd-head">
                <span class="prov-token-hint">{$t('infra.prov.tokenPrompt')}</span>
                {@render copyButton(() => copyText(token, 'infra.prov.tokenCopied', true))}
              </div>
              <code class="prov-token">{token}</code>
            </div>
          {/if}
        {/if}
      {/if}
    {/if}
  </div>
  {#snippet footer()}
    <Button variant="secondary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>

<style>
  .prov-dialog {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
  }
  .row label {
    font-size: var(--text-sm);
    color: var(--text-muted);
  }
  .prereq {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-4);
    font-size: var(--text-sm);
  }
  .prereq ul {
    margin: var(--sp-1) 0 0;
    padding-left: var(--sp-4);
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
    gap: var(--sp-2);
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
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
</style>
