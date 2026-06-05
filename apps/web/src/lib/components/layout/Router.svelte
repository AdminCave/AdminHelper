<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component } from 'svelte';
  import { path } from '$lib/router';

  interface Props {
    routes: Record<string, Component>;
    fallback?: Component;
  }

  let { routes, fallback }: Props = $props();

  const matched = $derived.by(() => {
    const current = $path;
    if (routes[current]) return routes[current];
    const base = '/' + current.split('/').filter(Boolean)[0];
    if (routes[base]) return routes[base];
    return fallback ?? routes['*'];
  });
</script>

{#if matched}
  {@const C = matched}
  <C />
{/if}
