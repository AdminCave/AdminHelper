<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Frame of the monitoring re-design mockup (R-1558): navigation over the views, theme switch,
  // the drawer that every view opens the same way, and the exceptions, findings and profiles the
  // dialogs change. Every change is applied again to the reported objects, as the server would.
  // The server view keeps today's server list on the left (Kevin 2026-11-18); on a phone the list
  // slides in from the left. "Datenmenge" swaps in a fleet of about 300 servers to show how the
  // views hold up at scale (Kevin 2026-11-19).
  import { prefersReducedMotion } from 'svelte/motion';
  import { MediaQuery } from 'svelte/reactivity';
  import { fade } from 'svelte/transition';
  import Segmented from '../../components/ui/Segmented.svelte';
  import Tabs from '../../components/ui/Tabs.svelte';
  import ObjectDrawer from './ObjectDrawer.svelte';
  import { BASE_OBJECTS } from './fixtures';
  import { SCALE_OBJECTS } from './fixtures/scale';
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
  import AllServers from './views/AllServers.svelte';
  import HiddenView from './views/HiddenView.svelte';
  import KindsView from './views/KindsView.svelte';
  import ObjectsView from './views/ObjectsView.svelte';
  import ServerNav from './views/ServerNav.svelte';
  import ServerView from './views/ServerView.svelte';
  import { serverSummaries } from './views/servers';
  import type { Kind } from './model';

  const VIEWS = [
    { id: 'server', label: 'Server' },
    { id: 'objects', label: 'Objekte' },
    { id: 'cross', label: 'Querschnitte' },
    { id: 'kinds', label: 'Objektarten' },
    { id: 'hidden', label: 'Ausgeblendet' },
    { id: 'coverage', label: 'Abdeckung' },
  ];
  const ME = 'admin';
  const BIG_SERVERS = new Set(SCALE_OBJECTS.map((o) => o.server)).size;
  /** The phone layout: the server list becomes a drawer from the left. */
  const mobile = new MediaQuery('max-width: 760px');

  let data = $state('normal');
  let navOpen = $state(false);
  let view = $state('server');
  /** The server in the server view; empty for "Alle Server". */
  let server = $state('');
  let selected = $state<string | undefined>(undefined);
  let theme = $state(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');

  let exceptions = $state<Exception[]>(EXCEPTIONS.map((e) => ({ ...e })));
  let findings = $state<Finding[]>(FINDINGS.map((f) => ({ ...f })));
  let profiles = $state<Profile[]>(PROFILES.map((p) => ({ ...p })));
  let made = 0;
  /** The open exception dialog: the object it starts from and the exception it changes. */
  let dialog = $state<{ anchor: string; id?: string } | undefined>(undefined);

  const base = $derived(data === 'big' ? SCALE_OBJECTS : BASE_OBJECTS);
  const objects = $derived(applyExceptions(base, exceptions, NOW, TOPOLOGY));
  const object = $derived(objects.find((o) => o.key === selected));
  const summaries = $derived(serverSummaries(objects));
  const troubledServers = $derived(summaries.filter((s) => s.problems > 0).length);
  const anchor = $derived(base.find((o) => o.key === dialog?.anchor));
  const editing = $derived(exceptions.find((e) => e.id === dialog?.id));

  function editException(id: string): void {
    const e = exceptions.find((x) => x.id === id);
    const first = e && affected(e, base, TOPOLOGY)[0];
    if (first) dialog = { anchor: first.key, id };
  }

  function setData(value: string): void {
    data = value;
    server = '';
    selected = undefined;
    focusKind = '';
    dialog = undefined;
    navOpen = false;
    main?.scrollTo({ top: 0 });
  }

  function pick(name: string): void {
    showServer(name);
    navOpen = false;
  }

  function escape(e: KeyboardEvent): void {
    if (e.key === 'Escape' && navOpen) navOpen = false;
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

  /** The kind the server view opens and highlights, from a Lagekarte cell. */
  let focusKind = $state<Kind | ''>('');

  function showServer(name: string, kind: Kind | '' = ''): void {
    server = name;
    focusKind = kind;
    view = 'server';
    main?.scrollTo({ top: 0 });
  }

  let main = $state<HTMLElement | undefined>(undefined);

  function setTheme(value: string): void {
    theme = value;
    document.documentElement.dataset.theme = value;
  }
</script>

<svelte:window onkeydown={escape} />

<div class="app">
  <header class="top">
    <h1>Monitoring <span class="h1-sub">— Entwurf</span></h1>
    <div class="tabs-slot">
      <Tabs
        tabs={VIEWS}
        value={view}
        label="Ansicht"
        onChange={(id) => {
          view = id;
          navOpen = false;
          main?.scrollTo({ top: 0 });
        }}
      />
    </div>
    <div class="controls">
      <Segmented
        options={[
          { value: 'normal', label: 'Normal' },
          { value: 'big', label: `Groß · ${BIG_SERVERS} Server` },
        ]}
        value={data}
        size="sm"
        label="Datenmenge"
        onChange={setData}
      />
      <Segmented
        options={[
          { value: 'dark', label: 'Dunkel' },
          { value: 'light', label: 'Hell' },
        ]}
        value={theme}
        size="sm"
        label="Farbschema"
        onChange={setTheme}
      />
    </div>
  </header>
  <p class="notice">
    <strong>Mockup, fiktive Daten.</strong> Entwurf der Monitoring-Neuordnung (ADR 0004), mit keinem Server
    verbunden; Kennzahlen mit „neue Agent-Daten“ liefert der Agent heute noch nicht.
  </p>
  <div class="body" class:with-nav={view === 'server'}>
    {#if view === 'server'}
      <div class="nav-slot" class:open={navOpen} id="server-nav" inert={mobile.current && !navOpen}>
        <ServerNav {summaries} {server} onSelect={pick} />
      </div>
      {#if navOpen}
        <button
          type="button"
          class="scrim"
          aria-label="Serverliste schließen"
          onclick={() => (navOpen = false)}
          transition:fade={{ duration: prefersReducedMotion.current ? 0 : 180 }}
        ></button>
      {/if}
    {/if}
    <main class="content" bind:this={main}>
      {#if view === 'server'}
        <div class="m-bar">
          <button
            type="button"
            class="m-pick"
            aria-expanded={navOpen}
            aria-controls="server-nav"
            onclick={() => (navOpen = true)}
          >
            <span class="m-icon" aria-hidden="true">☰</span>
            <span class="m-label">{server || 'Alle Server'}</span>
            <span class="m-hint">{troubledServers} von {summaries.length} mit Problemen</span>
          </button>
        </div>
      {/if}
      <div class="inner">
        {#key `${data}|${view}|${server}`}
          <div class="view-in">
            {#if view === 'server' && server === ''}
              <AllServers {objects} now={NOW} {selected} onOpen={open} onServer={showServer} />
            {:else if view === 'server'}
              <ServerView {objects} now={NOW} {selected} {server} {focusKind} onOpen={open} />
            {:else if view === 'objects'}
              <ObjectsView {objects} now={NOW} {selected} onOpen={open} />
            {:else if view === 'cross'}
              <CrossView {objects} now={NOW} {selected} onOpen={open} />
            {:else if view === 'kinds'}
              <KindsView {objects} now={NOW} {selected} onOpen={open} />
            {:else if view === 'hidden'}
              <HiddenView
                {exceptions}
                objects={base}
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
          </div>
        {/key}
      </div>
    </main>
  </div>
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
      objects={base}
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
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
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
  .h1-sub {
    font-weight: 400;
    color: var(--text-muted);
  }
  .tabs-slot {
    min-width: 0;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-left: auto;
  }
  .notice {
    margin: 0;
    padding: var(--space-1) var(--space-5);
    border-bottom: 1px solid var(--border-faint);
    background: var(--info-bg);
    font-size: var(--text-xs);
    color: var(--text-muted);
  }
  .notice strong {
    color: var(--info);
  }
  .body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }
  .body.with-nav {
    grid-template-columns: 280px minmax(0, 1fr);
  }
  .nav-slot {
    min-height: 0;
  }
  .scrim,
  .m-bar {
    display: none;
  }
  .content {
    min-height: 0;
    overflow-y: auto;
  }
  .inner {
    max-width: 1280px;
    padding: var(--space-5) var(--space-6) var(--space-8);
  }
  .view-in {
    animation: view-in 280ms var(--ease-out) backwards;
  }
  @keyframes view-in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }

  /* Phone: the tabs scroll sideways under the title, the server list slides in from the left. */
  @media (max-width: 760px) {
    .top {
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-3);
      padding: var(--space-2) var(--space-3) 0;
    }
    h1 {
      font-size: var(--text-base);
    }
    .h1-sub {
      display: none;
    }
    .controls {
      gap: var(--space-2);
    }
    .tabs-slot {
      order: 3;
      flex: 1 0 100%;
      margin: 0 calc(-1 * var(--space-3));
      padding: 0 var(--space-3);
      overflow-x: auto;
      scrollbar-width: none;
    }
    .notice {
      padding: var(--space-1) var(--space-3);
    }
    .body.with-nav {
      grid-template-columns: minmax(0, 1fr);
    }
    .nav-slot {
      position: fixed;
      inset: 0 auto 0 0;
      z-index: 30;
      width: min(320px, 86vw);
      box-shadow: var(--shadow-lg);
      transform: translateX(-105%);
      transition: transform 280ms var(--ease-out);
    }
    .nav-slot.open {
      transform: none;
    }
    .scrim {
      display: block;
      position: fixed;
      inset: 0;
      z-index: 29;
      padding: 0;
      border: 0;
      background: color-mix(in srgb, var(--bg) 60%, transparent);
      backdrop-filter: blur(2px);
    }
    .m-bar {
      display: block;
      position: sticky;
      top: 0;
      z-index: 5;
      padding: var(--space-2) var(--space-3);
      border-bottom: 1px solid var(--border-faint);
      background: color-mix(in srgb, var(--bg) 92%, transparent);
      backdrop-filter: blur(6px);
    }
    .m-pick {
      display: grid;
      grid-template-columns: 20px minmax(0, 1fr) auto;
      align-items: center;
      gap: var(--space-2);
      width: 100%;
      min-height: 40px;
      padding: var(--space-1) var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    .m-pick:focus-visible {
      outline: none;
      box-shadow: var(--ring-shadow);
    }
    .m-icon {
      color: var(--text-muted);
    }
    .m-label {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 600;
      color: var(--text-strong);
    }
    .m-hint {
      font-size: var(--text-xs);
      color: var(--text-subtle);
    }
    .inner {
      padding: var(--space-4) var(--space-3) var(--space-6);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .view-in {
      animation: none;
    }
    .nav-slot {
      transition: none;
    }
  }
</style>
