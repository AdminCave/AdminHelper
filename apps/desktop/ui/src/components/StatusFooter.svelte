<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import * as bridge from '$lib/bridge';
  import type { DeviceIdentity } from '$lib/bridge/types';
  import { settings, session } from '$lib/stores/session';
  import { tunnel } from '$lib/stores/tunnel';
  import { monitoringChecks, monitoringHasLoaded } from '$lib/stores/monitoring';
  import { lastSyncedAt } from '$lib/stores/connections';
  import { settingsModalOpen } from '$lib/stores/settings';
  import { timeAgo } from '$lib/utils/timeAgo';
  import { t, currentLocale } from '$lib/i18n';

  // Only what the app knows (R-1062): no field here without a store or command behind it.
  let mode = $derived($settings?.mode ?? 'local');
  let serverMode = $derived(mode === 'server' && $session !== null);

  function hostOf(url: string | null | undefined): string | null {
    if (!url) return null;
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  let hub = $derived(
    mode === 'server'
      ? hostOf($session?.serverUrl)
      : mode === 'sync'
        ? hostOf($settings?.url)
        : null,
  );

  let tunnelLabel = $derived.by(() => {
    const ui = $tunnel.ui;
    if (ui === 'connecting') return $t('tunnel.connecting');
    if (ui === 'connected') return $t('tunnel.active');
    if (ui === 'disconnected') return $t('tunnel.disconnected');
    return $t('tunnel.inactive');
  });

  // The count of the last monitoring load; before the first one there is no number to show.
  let problems = $derived(
    $monitoringChecks.filter(
      (c) =>
        c.enabled !== false && (c.state?.status === 'warning' || c.state?.status === 'critical'),
    ).length,
  );

  // "x min ago" ages without a store change; one tick a minute keeps it current.
  let now = $state(Date.now());
  const tick = setInterval(() => (now = Date.now()), 60_000);
  onDestroy(() => clearInterval(tick));
  let syncLabel = $derived.by(() => {
    void now;
    return $t('footer.lastSync', { time: timeAgo($lastSyncedAt, $t) });
  });

  // undefined: not asked yet or unreadable (then the field stays away); null: not enrolled.
  let identity = $state<DeviceIdentity | null | undefined>(undefined);
  let identityGen = 0;
  // Enrolling and resetting happen in the settings dialog: read again each time it closes.
  $effect(() => {
    if (!serverMode) {
      identity = undefined;
      return;
    }
    if ($settingsModalOpen) return;
    const gen = ++identityGen;
    bridge.deviceIdentity().then(
      (id) => {
        if (gen === identityGen) identity = id;
      },
      () => {
        if (gen === identityGen) identity = undefined;
      },
    );
  });

  let certLabel = $derived.by(() => {
    if (identity === undefined) return null;
    if (identity === null) return $t('footer.certNone');
    const notAfter = new Date(identity.notAfter);
    if (Number.isNaN(notAfter.getTime())) return null;
    if (notAfter.getTime() < now) return $t('footer.certExpired');
    const date = notAfter.toLocaleDateString(currentLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
    return $t('footer.certUntil', { date });
  });
</script>

<footer class="status-footer" aria-label={$t('footer.label')}>
  <span class="status-footer-item" data-field="mode">
    {$t(`settings.mode.${mode}`)}{#if hub}&nbsp;· {hub}{/if}
  </span>
  {#if serverMode}
    <span class="status-footer-item" data-field="tunnel" data-status={$tunnel.ui}>
      <span class="status-footer-dot" aria-hidden="true"></span>{tunnelLabel}
    </span>
    {#if $monitoringHasLoaded}
      <span class="status-footer-item" data-field="problems" class:has-problems={problems > 0}>
        {problems > 0 ? $t('footer.problems', { count: problems }) : $t('footer.problemsNone')}
      </span>
    {/if}
    {#if certLabel}
      <span class="status-footer-item" data-field="cert">{certLabel}</span>
    {/if}
  {/if}
  {#if mode === 'sync'}
    <span class="status-footer-item" data-field="sync">{syncLabel}</span>
  {/if}
</footer>
