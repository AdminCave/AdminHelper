<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Frame of the monitoring re-design mockup (R-1558): navigation over the views, theme switch,
  // and the drawer that every view opens the same way.
  import Callout from '../../components/ui/Callout.svelte';
  import Segmented from '../../components/ui/Segmented.svelte';
  import Tabs from '../../components/ui/Tabs.svelte';
  import ObjectDrawer from './ObjectDrawer.svelte';
  import { ALL_OBJECTS } from './fixtures';
  import { NOW } from './fixtures/time';
  import KindsView from './views/KindsView.svelte';

  const VIEWS = [{ id: 'kinds', label: 'Objektarten' }];

  let view = $state('kinds');
  let selected = $state<string | undefined>(undefined);
  let theme = $state(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');

  const object = $derived(ALL_OBJECTS.find((o) => o.key === selected));

  function open(key: string): void {
    selected = key;
  }

  function setTheme(value: string): void {
    theme = value;
    document.documentElement.dataset.theme = value;
  }
</script>

<div class="app">
  <header class="top">
    <h1>Monitoring — Entwurf</h1>
    <Tabs tabs={VIEWS} value={view} label="Ansicht" onChange={(id) => (view = id)} />
    <Segmented
      options={[
        { value: 'dark', label: 'Dunkel' },
        { value: 'light', label: 'Hell' },
      ]}
      value={theme}
      label="Farbschema"
      onChange={setTheme}
    />
  </header>
  <div class="notice">
    <Callout tone="info" title="Mockup, fiktive Daten">
      Entwurf der Monitoring-Neuordnung (ADR 0004). Nichts hier ist mit einem Server verbunden;
      Kennzahlen mit „neue Agent-Daten“ liefert der Agent heute noch nicht.
    </Callout>
  </div>
  <main class="content">
    {#if view === 'kinds'}
      <KindsView objects={ALL_OBJECTS} now={NOW} {selected} onOpen={open} />
    {/if}
  </main>
  {#if object}
    <ObjectDrawer {object} now={NOW} onClose={() => (selected = undefined)} />
  {/if}
</div>

<style>
  .app {
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
  }
  .top {
    display: flex;
    align-items: center;
    gap: var(--space-5);
    padding: var(--space-3) var(--space-5);
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  h1 {
    margin: 0;
    font-size: var(--text-lg);
    color: var(--text-strong);
    white-space: nowrap;
  }
  .notice {
    padding: var(--space-4) var(--space-5) 0;
  }
  .content {
    padding: var(--space-4) var(--space-5) var(--space-8);
    max-width: 1280px;
  }
</style>
