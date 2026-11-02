<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!-- A page with a menu, a tooltip and something outside both, for the overlay tests. -->
<script lang="ts">
  import Menu, { type MenuItem } from '../Menu.svelte';
  import Tooltip from '../Tooltip.svelte';

  interface Props {
    items: MenuItem[];
  }

  let { items }: Props = $props();
</script>

<Menu {items} align="end">
  {#snippet trigger(p)}
    <button type="button" {...p}>Mehr</button>
  {/snippet}
</Menu>
<Tooltip content="Verbindung trennen">
  {#snippet children(p)}
    <button type="button" {...p}>Trennen</button>
  {/snippet}
</Tooltip>
<button type="button">Draußen</button>
