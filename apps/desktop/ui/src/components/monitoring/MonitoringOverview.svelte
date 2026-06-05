<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import MonSummaryCards from './MonSummaryCards.svelte';
  import MonServerList from './MonServerList.svelte';
  import MonServerDashboard from './MonServerDashboard.svelte';
</script>

<MonSummaryCards />

<div class="mon-split">
  <aside class="mon-split-sidebar">
    <MonServerList />
  </aside>
  <section class="mon-split-main">
    <MonServerDashboard />
  </section>
</div>
