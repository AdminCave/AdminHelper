<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { sessionStore } from '$lib/stores/session';
  import { monitoringApi } from '$lib/api/monitoring';

  interface Props {
    checkId: string;
    status?: string;
    width?: number;
    height?: number;
    period?: '1h' | '6h' | '24h' | '7d';
  }
  let { checkId, status = 'ok', width = 120, height = 40, period = '1h' }: Props = $props();

  let host: HTMLDivElement | null = $state(null);
  let points = $state<number[]>([]);
  let loaded = $state(false);
  let observer: IntersectionObserver | null = null;

  const STROKE: Record<string, string> = {
    ok: 'var(--success)',
    warning: 'var(--warning)',
    critical: 'var(--danger)',
    unknown: 'var(--text-muted)',
    pending: 'var(--text-muted)',
  };

  async function load(): Promise<void> {
    if (loaded) return;
    const { session } = $sessionStore;
    if (!session) return;
    loaded = true;
    try {
      const res = await monitoringApi.fetchMetrics(session, checkId, period);
      const series = (res.data ?? []).filter((s) => !(s.metric?.__name__ || '').includes('status'));
      if (series.length === 0) return;
      const vals = series[0].values.map((v) => parseFloat(v[1])).filter((n) => !Number.isNaN(n));
      if (vals.length < 2) return;
      points = vals;
    } catch {
      // Sparkline is allowed to fail — stays empty
    }
  }

  $effect(() => {
    if (!host) return;
    if (!('IntersectionObserver' in window)) {
      void load();
      return;
    }
    observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            void load();
            observer?.disconnect();
            observer = null;
            break;
          }
        }
      },
      { rootMargin: '120px' },
    );
    observer.observe(host);
  });

  onDestroy(() => {
    observer?.disconnect();
    observer = null;
  });

  let path = $derived.by(() => {
    if (points.length < 2) return { line: '', area: '', min: 0, max: 0 };
    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = max - min || 1;
    const n = points.length;
    const dx = width / (n - 1);
    const pad = 2;
    const h = height - pad * 2;
    const coords: string[] = [];
    for (let i = 0; i < n; i++) {
      const x = i * dx;
      const y = pad + h - ((points[i] - min) / range) * h;
      coords.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    const line = `M ${coords.join(' L ')}`;
    const area = `${line} L ${width},${height} L 0,${height} Z`;
    return { line, area, min, max };
  });

  let stroke = $derived(STROKE[status] ?? STROKE.ok);
  let gradId = $derived(`spark-grad-${checkId}`);
</script>

<div class="mon-spark" bind:this={host} style="width:{width}px;height:{height}px">
  {#if points.length >= 2}
    <svg viewBox="0 0 {width} {height}" {width} {height} preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color={stroke} stop-opacity="0.28" />
          <stop offset="100%" stop-color={stroke} stop-opacity="0" />
        </linearGradient>
      </defs>
      <path d={path.area} fill="url(#{gradId})" />
      <path
        d={path.line}
        fill="none"
        {stroke}
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  {:else if loaded}
    <span class="mon-spark-empty"></span>
  {/if}
</div>
