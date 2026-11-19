<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type { ProvisionProgress } from '$lib/api/types';
  import { provisioningApi } from '$lib/api/provisioning';
  import { session } from '$lib/stores/session';
  import { t } from '$lib/i18n';
  import { Activity } from '@lucide/svelte';
  import Button from '../../ui/Button.svelte';
  import Callout from '../../ui/Callout.svelte';
  import Pill from '../../ui/Pill.svelte';

  interface Props {
    serverId: string;
    // Leaves the dialog for the server's monitoring tab, where the template suggestions are.
    onShowMonitoring?: () => void;
  }
  let { serverId, onShowMonitoring }: Props = $props();

  const POLL_MS = 5_000;
  const REPORT_GRACE_MS = 5 * 60_000;

  type StageState = 'done' | 'waiting' | 'unknown';
  interface Stage {
    id: 'token' | 'certificate' | 'report' | 'tunnel';
    state: StageState;
  }

  let progress = $state<ProvisionProgress | null>(null);
  let failed = $state(false);
  let now = $state(Date.now());
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  function ms(iso: string | null | undefined): number | null {
    if (!iso) return null;
    const v = Date.parse(iso);
    return Number.isNaN(v) ? null : v;
  }

  // Every stage belongs to the newest token: on a server that is already registered, the
  // certificate and reports of the earlier run must not count for a fresh token. Only when
  // the token is gone (the cleanup deletes redeemed tokens) does the certificate stand in.
  const anchor = $derived(ms(progress?.token?.createdAt));
  const certAt = $derived(ms(progress?.certificate?.issuedAt));
  const certified = $derived(certAt !== null && (anchor === null || certAt >= anchor));
  const redeemed = $derived(progress?.token ? !!progress.token.usedAt || certified : certified);
  const reported = $derived.by(() => {
    const last = ms(progress?.report?.lastReportAt);
    if (last === null) return false;
    return anchor === null || (certified && last >= (certAt as number));
  });
  const stages = $derived.by((): Stage[] => {
    const p = progress;
    if (!p) return [];
    const list: Stage[] = [
      { id: 'token', state: redeemed ? 'done' : 'waiting' },
      { id: 'certificate', state: certified ? 'done' : 'waiting' },
      {
        id: 'report',
        state: reported ? 'done' : p.monitoringReachable ? 'waiting' : 'unknown',
      },
    ];
    if (p.tunnel.configured) {
      const c = p.tunnel.connected;
      list.push({ id: 'tunnel', state: c === true ? 'done' : c === null ? 'unknown' : 'waiting' });
    }
    return list;
  });
  const complete = $derived(stages.length > 0 && stages.every((s) => s.state === 'done'));

  const tokenExpired = $derived.by(() => {
    const exp = ms(progress?.token?.expiresAt);
    return !redeemed && exp !== null && exp < now;
  });
  // From the redemption on, the first report is due within minutes; the anchor is the
  // certificate when the redeemed token is already gone.
  const reportOverdue = $derived.by(() => {
    if (!progress || reported || !progress.monitoringReachable) return false;
    const since = ms(progress.token?.usedAt) ?? (certified ? certAt : null);
    return since !== null && now - since > REPORT_GRACE_MS;
  });
  const tunnelMissing = $derived(
    !!progress?.tunnel.configured && progress.tunnel.connected === false && reported,
  );

  async function poll(): Promise<void> {
    const s = $session;
    if (!s || stopped) return;
    try {
      progress = await provisioningApi.progress(s, serverId);
      failed = false;
    } catch {
      failed = true;
    }
    now = Date.now();
    if (stopped || complete) return;
    timer = setTimeout(() => void poll(), POLL_MS);
  }

  onMount(() => {
    void poll();
  });
  onDestroy(() => {
    stopped = true;
    if (timer) clearTimeout(timer);
  });

  const TONE: Record<StageState, 'ok' | 'muted' | 'warn'> = {
    done: 'ok',
    waiting: 'muted',
    unknown: 'warn',
  };
</script>

<div class="prov-progress" data-testid="prov-progress">
  <strong>{$t('infra.prov.progress')}</strong>
  {#if failed && !progress}
    <p class="muted" data-testid="prov-progress-error">{$t('infra.prov.progressError')}</p>
  {/if}
  {#if progress}
    <ol>
      {#each stages as stage (stage.id)}
        <li data-stage={stage.id} data-state={stage.state}>
          <span>{$t(`infra.prov.stage.${stage.id}`)}</span>
          <Pill tone={TONE[stage.state]}>{$t(`infra.prov.stageState.${stage.state}`)}</Pill>
        </li>
      {/each}
    </ol>

    {#if tokenExpired}
      <div data-testid="prov-hint-expired">
        <Callout tone="warning">{$t('infra.prov.hint.expired')}</Callout>
      </div>
    {/if}
    {#if reportOverdue}
      <div data-testid="prov-hint-report">
        <Callout tone="warning">{$t('infra.prov.hint.noReport')}</Callout>
      </div>
    {/if}
    {#if tunnelMissing}
      <div data-testid="prov-hint-tunnel">
        <Callout tone="warning">{$t('infra.prov.hint.tunnel')}</Callout>
      </div>
    {/if}
    {#if progress.platformMismatch}
      <div data-testid="prov-hint-platform">
        <Callout tone="warning"
          >{$t('infra.prov.hint.platform', {
            reported: $t(`infra.prov.platform.${progress.reportedPlatform ?? 'other'}`),
          })}</Callout
        >
      </div>
    {/if}

    {#if complete && onShowMonitoring}
      <div>
        <Button
          size="sm"
          variant="secondary"
          iconLeft={Activity}
          data-action="prov-show-monitoring"
          onclick={onShowMonitoring}>{$t('infra.prov.showMonitoring')}</Button
        >
      </div>
    {/if}
  {/if}
</div>

<style>
  .prov-progress {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    font-size: var(--text-sm);
  }
  ol {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    margin: 0;
    padding-left: var(--sp-4);
  }
  li span {
    margin-right: var(--sp-2);
  }
  .muted {
    margin: 0;
    color: var(--text-muted);
  }
</style>
