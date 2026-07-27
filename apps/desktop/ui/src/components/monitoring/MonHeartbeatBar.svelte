<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { sessionStore } from '$lib/stores/session';
  import { monitoringApi } from '$lib/api/monitoring';
  import type { MonitoringMetricSeries } from '$lib/api/types';
  import MonStatusTimeline from './MonStatusTimeline.svelte';

  // Availability bar for a server's agent_ping check (Uptime-Kuma-style):
  // lazily loads the status timeline when scrolled into view — same pattern
  // as MonSparkline, one metrics request per visible bar.
  interface Props {
    checkId: string;
    period?: '1h' | '6h' | '24h' | '7d';
  }
  let { checkId, period = '24h' }: Props = $props();

  let host: HTMLDivElement | null = $state(null);
  let history = $state<MonitoringMetricSeries[] | null>(null);
  let loaded = $state(false);
  let observer: IntersectionObserver | null = null;

  async function load(): Promise<void> {
    if (loaded) return;
    const { session } = $sessionStore;
    if (!session) return;
    loaded = true;
    try {
      const res = await monitoringApi.fetchMetrics(session, checkId, period);
      history = res.statusHistory ?? null;
    } catch {
      // The availability bar is allowed to fail — it simply stays empty.
    }
  }

  $effect(() => {
    // Track checkId/period so the bar reloads when either prop changes.
    void checkId;
    void period;
    loaded = false;
    history = null;
    observer?.disconnect();
    observer = null;

    if (!host) return;
    if (!('IntersectionObserver' in window)) {
      // untrack: load() reads `loaded`/$sessionStore — called synchronously
      // inside this effect, those reads would register as dependencies and
      // loop the effect (effect_update_depth_exceeded).
      untrack(() => void load());
      return () => {
        observer?.disconnect();
        observer = null;
      };
    }
    observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            // untrack for the same reason as the fallback path: an observer
            // implementation may fire this callback synchronously.
            untrack(() => void load());
            observer?.disconnect();
            observer = null;
            break;
          }
        }
      },
      { rootMargin: '120px' },
    );
    observer.observe(host);

    return () => {
      observer?.disconnect();
      observer = null;
    };
  });

  onDestroy(() => {
    observer?.disconnect();
    observer = null;
  });
</script>

<div class="mon-heartbeat" bind:this={host}>
  <MonStatusTimeline statusHistory={history} />
</div>

<style>
  .mon-heartbeat {
    min-height: 8px;
  }
</style>
