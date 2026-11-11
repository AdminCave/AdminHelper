<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorCheck } from '$lib/api/types';

  // The agent's own rule for a credential ref (apps/agent/internal/credentials/store.go): a
  // ref that passes it holds no shell character, so the command shown runs as it reads.
  const REF_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:@-]*(\/[A-Za-z0-9][A-Za-z0-9_.:@-]*)*$/;
  const REF_MAX = 255;

  /** The credential ref a module check reads, or null when it has none the agent would take. */
  export function credentialRefOf(check: MonitorCheck): string | null {
    const credential = (check.config as { credential?: unknown } | undefined)?.credential;
    if (!credential || typeof credential !== 'object') return null;
    const ref = (credential as { ref?: unknown }).ref;
    if (typeof ref !== 'string' || ref.length > REF_MAX || !REF_PATTERN.test(ref)) return null;
    return ref;
  }
</script>

<script lang="ts">
  import type { Connection } from '$lib/bridge/types';
  import { t } from '$lib/i18n';
  import { connectCredential } from '$lib/stores/connectFlow';
  import Button from '../../ui/Button.svelte';
  import CodeBlock from '../../ui/CodeBlock.svelte';
  import Modal from '../../ui/Modal.svelte';
  import RadioGroup from '../../ui/RadioGroup.svelte';

  interface Props {
    open: boolean;
    checkName: string;
    /** Checked with `credentialRefOf`. */
    credentialRef: string;
    /** The server's SSH connections. */
    connections: Connection[];
    /** A Windows host: no terminal over SSH, the command in its PowerShell form. */
    windows: boolean;
    onClose: () => void;
  }

  let { open, checkName, credentialRef, connections, windows, onClose }: Props = $props();

  const command = $derived(
    windows
      ? `& 'C:\\Program Files\\AdminHelper\\adminhelper-agent.exe' monitor credential set ${credentialRef}`
      : `sudo adminhelper-agent monitor credential set ${credentialRef}`,
  );
  const usable = $derived(windows ? [] : connections);
  let chosen = $state('');
  // The first connection until the admin picks another.
  const connection = $derived(usable.find((c) => c.id === chosen) ?? usable[0]);
  let busy = $state(false);

  async function openTerminal(): Promise<void> {
    if (!connection || busy) return;
    busy = true;
    try {
      await connectCredential(connection, credentialRef);
    } finally {
      busy = false;
    }
    onClose();
  }
</script>

<Modal {open} title={$t('monitoring.credential.action')} width="560px" {onClose}>
  <div class="cred">
    <p class="cred-text">{$t('monitoring.credential.intro', { check: checkName })}</p>
    <div class="cred-ref">
      <span class="cred-label">{$t('monitoring.credential.ref')}</span>
      <code>{credentialRef}</code>
    </div>
    {#if connection}
      {#if usable.length > 1}
        <RadioGroup
          label={$t('monitoring.credential.connection')}
          options={usable.map((c) => ({
            value: c.id,
            label: c.name,
            description: c.host ?? undefined,
          }))}
          value={connection.id}
          onChange={(v) => (chosen = v)}
        />
      {/if}
      <p class="cred-hint">{$t('monitoring.credential.terminalHint')}</p>
    {:else}
      <p class="cred-hint">
        {$t(windows ? 'monitoring.credential.windows' : 'monitoring.credential.noSsh')}
      </p>
    {/if}
    <CodeBlock code={command} />
    <p class="cred-hint">{$t('monitoring.credential.after')}</p>
  </div>
  {#snippet footer()}
    <Button variant="secondary" onclick={onClose}>{$t('action.close')}</Button>
    {#if connection}
      <Button loading={busy} onclick={openTerminal}>{$t('monitoring.credential.open')}</Button>
    {/if}
  {/snippet}
</Modal>

<style>
  .cred {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .cred-text {
    margin: 0;
  }
  .cred-ref {
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
  }
  .cred-label {
    color: var(--text-subtle);
    font-size: var(--text-xs);
  }
  .cred-ref code {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    word-break: break-all;
  }
  .cred-hint {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
</style>
