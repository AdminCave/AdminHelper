<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorFinding, MonitorFindingKind } from '$lib/api/types';
  import { t } from '$lib/i18n';
  import { ageText, findingDetail } from '$lib/models/monitoringText';
  import Badge from '../../ui/Badge.svelte';
  import Button from '../../ui/Button.svelte';
  import EmptyState from '../../ui/EmptyState.svelte';

  interface Props {
    findings: MonitorFinding[];
    /** The inbox of all servers names each finding's server; a server page leaves it out. */
    serverName?: (serverId: string) => string;
    onAdopt: (finding: MonitorFinding) => Promise<unknown>;
    onDismiss: (finding: MonitorFinding) => Promise<unknown>;
    /** Adopts every finding listed: one server's (`adopt-all?server_id`). */
    onAdoptAll?: () => Promise<unknown>;
  }

  let { findings, serverName, onAdopt, onDismiss, onAdoptAll }: Props = $props();

  // One action at a time: adopting reloads checks and findings underneath the list.
  let busy = $state<string | null>(null);

  async function run(key: string, action: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = key;
    try {
      await action();
    } finally {
      busy = null;
    }
  }

  const KIND_TONE: Record<MonitorFindingKind, 'info' | 'warning' | 'neutral'> = {
    new: 'info',
    changed: 'warning',
    gone: 'neutral',
  };
  const KIND_LABEL: Record<MonitorFindingKind, string> = {
    new: 'monitoring.findings.kind.new',
    changed: 'monitoring.findings.kind.changed',
    gone: 'monitoring.findings.kind.gone',
  };
  const KIND_HINT: Record<MonitorFindingKind, string> = {
    new: 'monitoring.findings.hint.new',
    changed: 'monitoring.findings.hint.changed',
    gone: 'monitoring.findings.hint.gone',
  };
</script>

{#if findings.length === 0}
  <EmptyState framed={false} message={$t('monitoring.findings.empty')} />
{:else}
  <div class="inbox">
    {#if onAdoptAll && findings.length > 1}
      <div class="inbox-tools">
        <Button
          variant="secondary"
          size="sm"
          loading={busy === 'all'}
          disabled={busy !== null}
          onclick={() => onAdoptAll && run('all', onAdoptAll)}
        >
          {$t('monitoring.findings.adoptAll', { count: findings.length })}
        </Button>
      </div>
    {/if}
    <ul class="inbox-list">
      {#each findings as finding (finding.id)}
        {@const detail = findingDetail(finding.summary)}
        <li class="inbox-item" data-kind={finding.kind}>
          <div class="inbox-main">
            <div class="inbox-title">
              <Badge tone={KIND_TONE[finding.kind]}>{$t(KIND_LABEL[finding.kind])}</Badge>
              <span class="inbox-name">{finding.moduleName ?? finding.moduleId}</span>
              {#if finding.instanceKey !== finding.moduleId}
                <span class="inbox-instance">{finding.instanceKey}</span>
              {/if}
              {#if serverName}
                <span class="inbox-server">{serverName(finding.serverId)}</span>
              {/if}
            </div>
            <p class="inbox-hint">
              {$t(KIND_HINT[finding.kind])}
              {#if finding.silentChecks.length > 0}
                {$t('monitoring.findings.silent', { count: finding.silentChecks.length })}
              {/if}
              {#if finding.droppedChecks.length > 0}
                {$t('monitoring.findings.dropped', { count: finding.droppedChecks.length })}
              {/if}
            </p>
            <p class="inbox-meta">
              {#if detail}<span class="inbox-detail">{detail}</span> ·{/if}
              {$t('monitoring.findings.seen', { age: ageText($t, finding.lastSeen) })}
            </p>
          </div>
          <div class="inbox-actions">
            <Button
              variant="primary"
              size="sm"
              loading={busy === finding.id}
              disabled={busy !== null}
              onclick={() => run(finding.id, () => onAdopt(finding))}
            >
              {$t('monitoring.findings.adopt')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onclick={() => run(`dismiss:${finding.id}`, () => onDismiss(finding))}
            >
              {$t('monitoring.findings.dismiss')}
            </Button>
          </div>
        </li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .inbox {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
  }
  .inbox-tools {
    display: flex;
    justify-content: flex-end;
  }
  .inbox-list {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .inbox-item {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--border-faint);
  }
  .inbox-item:last-child {
    border-bottom: 0;
  }
  .inbox-main {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .inbox-title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .inbox-name {
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .inbox-instance,
  .inbox-detail {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
  }
  .inbox-server {
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .inbox-hint,
  .inbox-meta {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .inbox-meta {
    color: var(--text-subtle);
  }
  .inbox-actions {
    display: inline-flex;
    flex-shrink: 0;
    gap: var(--space-2);
  }
</style>
