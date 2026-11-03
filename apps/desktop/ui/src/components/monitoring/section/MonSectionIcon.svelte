<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component } from 'svelte';
  import Activity from '@lucide/svelte/icons/activity';
  import Archive from '@lucide/svelte/icons/archive';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import Container from '@lucide/svelte/icons/container';
  import Database from '@lucide/svelte/icons/database';
  import Globe from '@lucide/svelte/icons/globe';
  import HardDrive from '@lucide/svelte/icons/hard-drive';
  import Pencil from '@lucide/svelte/icons/pencil';
  import Play from '@lucide/svelte/icons/play';
  import Power from '@lucide/svelte/icons/power';
  import Settings from '@lucide/svelte/icons/settings';
  import Undo2 from '@lucide/svelte/icons/undo-2';
  import Zap from '@lucide/svelte/icons/zap';

  interface Props {
    name: string;
  }
  let { name }: Props = $props();

  // Section heads take 18 px, the check-line actions 14 px.
  const ICONS: Record<string, [Component<{ size?: number; strokeWidth?: number }>, number]> = {
    live: [Zap, 18],
    network: [Globe, 18],
    services: [Settings, 18],
    docker: [Container, 18],
    backups: [Archive, 18],
    storage: [Database, 18],
    smart: [HardDrive, 18],
    heartbeat: [Activity, 18],
    chevron: [ChevronDown, 14],
    edit: [Pencil, 14],
    play: [Play, 14],
    power: [Power, 14],
    reset: [Undo2, 14],
  };

  const entry = $derived(ICONS[name]);
</script>

{#if entry}
  {@const [Icon, size] = entry}
  <Icon {size} strokeWidth={name === 'chevron' ? 2.2 : 2} />
{/if}
