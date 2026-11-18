<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Frame of the monitoring re-design mockup (R-1558): navigation over the views, theme switch,
  // the drawer that every view opens the same way, and the exceptions, findings and profiles the
  // dialogs change. Every change is applied again to the reported objects, as the server would.
  import Callout from '../../components/ui/Callout.svelte';
  import Segmented from '../../components/ui/Segmented.svelte';
  import Tabs from '../../components/ui/Tabs.svelte';
  import ObjectDrawer from './ObjectDrawer.svelte';
  import { BASE_OBJECTS } from './fixtures';
  import { EXCEPTIONS, FINDINGS, PROFILES, TOPOLOGY } from './fixtures/exceptions';
  import { NOW } from './fixtures/time';
  import {
    affected,
    applyExceptions,
    type Exception,
    type Finding,
    type Policy,
    type Profile,
  } from './exceptions';
  import CoverageView from './views/CoverageView.svelte';
  import CrossView from './views/CrossView.svelte';
  import ExceptionDialog from './views/ExceptionDialog.svelte';
  import HiddenView from './views/HiddenView.svelte';
  import KindsView from './views/KindsView.svelte';
  import Lage from './views/Lage.svelte';
  import ObjectsView from './views/ObjectsView.svelte';
  import ServerView from './views/ServerView.svelte';

  const VIEWS = [
    { id: 'lage', label: 'Lage' },
    { id: 'server', label: 'Server' },
    { id: 'objects', label: 'Objekte' },
    { id: 'cross', label: 'Querschnitte' },
    { id: 'kinds', label: 'Objektarten' },
    { id: 'hidden', label: 'Ausgeblendet' },
    { id: 'coverage', label: 'Abdeckung' },
  ];
  const ME = 'admin';

  let view = $state('lage');
  let selected = $state<string | undefined>(undefined);
  let theme = $state(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');

  let exceptions = $state<Exception[]>(EXCEPTIONS.map((e) => ({ ...e })));
  let findings = $state<Finding[]>(FINDINGS.map((f) => ({ ...f })));
  let profiles = $state<Profile[]>(PROFILES.map((p) => ({ ...p })));
  let made = 0;
  /** The open exception dialog: the object it starts from and the exception it changes. */
  let dialog = $state<{ anchor: string; id?: string } | undefined>(undefined);

  const objects = $derived(applyExceptions(BASE_OBJECTS, exceptions, NOW, TOPOLOGY));
  const object = $derived(objects.find((o) => o.key === selected));
  const anchor = $derived(BASE_OBJECTS.find((o) => o.key === dialog?.anchor));
  const editing = $derived(exceptions.find((e) => e.id === dialog?.id));

  function editException(id: string): void {
    const e = exceptions.find((x) => x.id === id);
    const first = e && affected(e, BASE_OBJECTS, TOPOLOGY)[0];
    if (first) dialog = { anchor: first.key, id };
  }

  // A change records who and when; a migrated exception then has an owner and leaves the review.
  function save(e: Exception): void {
    const saved = { ...e, id: e.id || `n${++made}`, by: ME, at: NOW.toISOString() };
    const i = exceptions.findIndex((x) => x.id === saved.id);
    if (i >= 0) exceptions[i] = saved;
    else exceptions.push(saved);
    dialog = undefined;
  }

  function remove(id: string): void {
    exceptions = exceptions.filter((e) => e.id !== id);
    dialog = undefined;
  }

  function review(id: string): void {
    const e = exceptions.find((x) => x.id === id);
    if (e) e.reviewed = true;
  }

  function decide(id: string, decision: 'taken' | 'declined'): void {
    const f = findings.find((x) => x.id === id);
    if (f) f.decision = decision;
  }

  function setPolicy(name: string, policy: Policy): void {
    const p = profiles.find((x) => x.name === name);
    if (p) p.policy = policy;
  }

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
    {#if view === 'lage'}
      <Lage {objects} now={NOW} {selected} onOpen={open} />
    {:else if view === 'server'}
      <ServerView {objects} now={NOW} {selected} onOpen={open} />
    {:else if view === 'objects'}
      <ObjectsView {objects} now={NOW} {selected} onOpen={open} />
    {:else if view === 'cross'}
      <CrossView {objects} now={NOW} {selected} onOpen={open} />
    {:else if view === 'kinds'}
      <KindsView {objects} now={NOW} {selected} onOpen={open} />
    {:else if view === 'hidden'}
      <HiddenView
        {exceptions}
        objects={BASE_OBJECTS}
        topology={TOPOLOGY}
        now={NOW}
        onEdit={editException}
        onRemove={remove}
        onReview={review}
      />
    {:else}
      <CoverageView
        {objects}
        {findings}
        {profiles}
        topology={TOPOLOGY}
        now={NOW}
        onDecide={decide}
        onPolicy={setPolicy}
      />
    {/if}
  </main>
  {#if object}
    <ObjectDrawer
      {object}
      now={NOW}
      onClose={() => (selected = undefined)}
      onException={(key, edit) =>
        (dialog = { anchor: key, id: edit ? object?.exception?.id : undefined })}
    />
  {/if}
  {#if dialog && anchor}
    <ExceptionDialog
      {anchor}
      objects={BASE_OBJECTS}
      topology={TOPOLOGY}
      now={NOW}
      existing={editing}
      onSave={save}
      onRemove={remove}
      onClose={() => (dialog = undefined)}
    />
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
