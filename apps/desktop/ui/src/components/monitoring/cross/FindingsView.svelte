<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonitorFinding, Server } from '$lib/api/types';

  export interface FindingGroup {
    serverId: string;
    serverName: string;
    findings: MonitorFinding[];
  }

  /**
   * The open findings by server, the servers by name, each server's findings in the
   * order they came. A server the list does not know (yet) shows its id.
   */
  export function findingGroups(findings: MonitorFinding[], servers: Server[]): FindingGroup[] {
    const groups: FindingGroup[] = [];
    for (const f of findings) {
      let group = groups.find((g) => g.serverId === f.serverId);
      if (!group) {
        const name = servers.find((s) => s.id === f.serverId)?.name ?? f.serverId;
        group = { serverId: f.serverId, serverName: name, findings: [] };
        groups.push(group);
      }
      group.findings.push(f);
    }
    return groups.sort(
      (a, b) =>
        a.serverName.localeCompare(b.serverName, undefined, { numeric: true }) ||
        a.serverId.localeCompare(b.serverId),
    );
  }
</script>

<script lang="ts">
  import { TriangleAlert, X } from '@lucide/svelte';
  import { t } from '$lib/i18n';
  import { adoptNoteLines, findingLabel } from '$lib/models/monitoringText';
  import {
    adoptAllFindings,
    adoptFinding,
    dismissFinding,
    monitoringCatalog,
  } from '$lib/stores/monitoring';
  import Callout from '../../ui/Callout.svelte';
  import EmptyState from '../../ui/EmptyState.svelte';
  import IconButton from '../../ui/IconButton.svelte';
  import FindingsInbox from '../card/FindingsInbox.svelte';
  import ServerLink from './ServerLink.svelte';

  interface Props {
    findings: MonitorFinding[];
    /** The last load failed: the list shown is the one before, or none. */
    error: string | null;
    servers: Server[];
    /** Opens the server page of a group's server. */
    onOpen: (serverKey: string) => void;
  }

  let { findings, error, servers, onOpen }: Props = $props();

  const groups = $derived(findingGroups(findings, servers));

  // What adopting left out stays until closed or the next adopt, as on the server page:
  // the finding, and maybe its server's group, is gone from the list by then.
  let note = $state<string[]>([]);

  function label(f: MonitorFinding): string {
    const server = servers.find((s) => s.id === f.serverId)?.name ?? f.serverId;
    return `${server} · ${findingLabel(f)}`;
  }

  async function adopt(f: MonitorFinding): Promise<void> {
    note = [];
    const result = await adoptFinding(f.id);
    if (result) note = adoptNoteLines($t, [result], [], $monitoringCatalog, [], label);
  }
  async function dismiss(f: MonitorFinding): Promise<void> {
    await dismissFinding(f.id);
  }
  async function adoptAll(group: FindingGroup): Promise<void> {
    note = [];
    const before = group.findings;
    const result = await adoptAllFindings(group.serverId);
    if (!result) return;
    note = adoptNoteLines($t, result.adopted, result.failed, $monitoringCatalog, before, label);
  }
</script>

{#if note.length > 0}
  <div class="findings-note" role="status">
    <Callout tone="warning" icon={TriangleAlert} title={$t('monitoring.findings.partial')}>
      <ul class="findings-note-list">
        {#each note as line, i (i)}
          <li>{line}</li>
        {/each}
      </ul>
      {#snippet action()}
        <IconButton icon={X} size="sm" label={$t('action.close')} onclick={() => (note = [])} />
      {/snippet}
    </Callout>
  </div>
{/if}

{#if groups.length === 0}
  <EmptyState
    framed={false}
    message={error ? $t('monitoring.findings.unavailable') : $t('monitoring.findings.empty')}
  />
{:else}
  {#if error}
    <p class="findings-stale" role="status">{$t('monitoring.findings.stale', { error })}</p>
  {/if}
  <div class="findings" role="region" aria-label={$t('monitoring.findings.label')}>
    {#each groups as group (group.serverId)}
      <section class="findings-group" aria-label={group.serverName}>
        <header class="findings-server">
          <ServerLink name={group.serverName} serverKey={group.serverId} {onOpen} />
          <span class="findings-count">{group.findings.length}</span>
        </header>
        <FindingsInbox
          findings={group.findings}
          onAdopt={adopt}
          onDismiss={dismiss}
          onAdoptAll={() => adoptAll(group)}
        />
      </section>
    {/each}
  </div>
{/if}

<style>
  .findings-note {
    margin-bottom: var(--space-4);
  }
  .findings-note-list {
    margin: 0;
    padding-left: var(--space-4);
  }
  .findings-stale {
    margin: 0 0 var(--space-3);
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .findings {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }
  .findings-group {
    min-width: 0;
  }
  .findings-server {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    padding-bottom: var(--space-2);
    border-bottom: 1px solid var(--border-faint);
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .findings-count {
    color: var(--text-muted);
    font-size: var(--text-xs);
    font-weight: 400;
  }
</style>
