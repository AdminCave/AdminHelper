<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The list "Ausgeblendet" (Konzept §2, §8.1): every exception with what it does, where, why, who
  // and how long; first the ones up for review (migrated, old, matching nothing), then those in
  // force, resting and ended. An ended exception hides nothing any more: its objects report again.
  import Badge from '../../../components/ui/Badge.svelte';
  import Button from '../../../components/ui/Button.svelte';
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import type { MonObject } from '../model';
  import { EFFECT_LABEL, dateText } from '../grammar';
  import {
    MIGRATED_BY,
    affected,
    conditionText,
    durationText,
    exceptionState,
    reviewReason,
    scopeText,
    type Exception,
    type ExceptionState,
    type Topology,
  } from '../exceptions';

  interface Props {
    exceptions: readonly Exception[];
    /** The objects as the checks report them, before any exception. */
    objects: readonly MonObject[];
    topology: Topology;
    now: Date;
    onEdit: (id: string) => void;
    onRemove: (id: string) => void;
    onReview: (id: string) => void;
  }

  let { exceptions, objects, topology, now, onEdit, onRemove, onReview }: Props = $props();

  interface Entry {
    e: Exception;
    state: ExceptionState;
    count: number;
    review?: string;
  }

  const entries = $derived(
    exceptions.map((e): Entry => {
      const count = affected(e, objects, topology).length;
      return {
        e,
        state: exceptionState(e, objects, now),
        count,
        review: reviewReason(e, count, now),
      };
    }),
  );

  const SECTIONS = [
    {
      id: 'review',
      title: 'Zur Prüfung',
      hint: 'Migriert, alt oder ohne Objekt: bestätigen, ändern oder aufheben.',
      take: (x: Entry) => !!x.review,
    },
    {
      id: 'active',
      title: 'Aktiv',
      hint: 'Gilt jetzt.',
      take: (x: Entry) => x.state.state === 'active',
    },
    {
      id: 'resting',
      title: 'Ruht',
      hint: 'Außerhalb des Fensters oder die Bedingung ist nicht erfüllt; die Objekte werden normal bewertet.',
      take: (x: Entry) => x.state.state === 'resting',
    },
    {
      id: 'ended',
      title: 'Erloschen',
      hint: 'Blendet nichts mehr aus: die Objekte melden wieder, mit dem Grund am Objekt.',
      take: (x: Entry) => x.state.state === 'ended',
    },
  ];

  // An exception up for review shows only there, not a second time under its state.
  const sections = $derived(
    SECTIONS.map((s) => ({
      ...s,
      entries: entries.filter((x) => (s.id === 'review' ? s.take(x) : !x.review && s.take(x))),
    })),
  );

  function whoText(e: Exception): string {
    return `von ${e.by ?? MIGRATED_BY}${e.at ? `, ${dateText(e.at)}` : ''}`;
  }

  function objectsText(n: number): string {
    return `betrifft ${n} ${n === 1 ? 'Objekt' : 'Objekte'}`;
  }
</script>

<div class="hidden-view">
  {#if exceptions.length === 0}
    <EmptyState title="Keine Ausnahmen" description="Alles, was gemeldet wird, wird bewertet." />
  {/if}
  {#each sections as s (s.id)}
    {#if s.entries.length}
      <section aria-label={s.title} data-section={s.id}>
        <h2>{s.title} <span class="count">{s.entries.length}</span></h2>
        <p class="hint">{s.hint}</p>
        <ul>
          {#each s.entries as x (x.e.id)}
            <li data-id={x.e.id}>
              <div class="head">
                <Badge tone={x.state.state === 'ended' ? 'warning' : 'neutral'}>
                  {EFFECT_LABEL[x.e.effect]}
                </Badge>
                <strong>{scopeText(x.e.scope, objects)}</strong>
              </div>
              <p class="line">
                {x.e.reason ? `Grund: ${x.e.reason}` : 'kein Grund angegeben'} · {whoText(x.e)} ·
                {durationText(x.e.duration)}
              </p>
              {#if x.e.bound}<p class="line">gilt nur bei {x.e.bound.text}</p>{/if}
              {#if x.e.condition}<p class="line">{conditionText(x.e.condition, objects)}</p>{/if}
              <p class="line muted">
                {objectsText(x.count)}{#if x.state.state !== 'active'}
                  · {x.state.state === 'ended' ? 'erloschen' : 'ruht'}: {x.state.text}{/if}
              </p>
              {#if x.review}<p class="line review">Zur Prüfung: {x.review}</p>{/if}
              <div class="actions">
                {#if x.review}
                  <Button size="sm" variant="secondary" onclick={() => onReview(x.e.id)}>
                    Bestätigen
                  </Button>
                {/if}
                {#if x.count > 0}
                  <Button size="sm" variant="ghost" onclick={() => onEdit(x.e.id)}>Ändern …</Button>
                {/if}
                <Button size="sm" variant="ghost" onclick={() => onRemove(x.e.id)}>Aufheben</Button>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {/each}
</div>

<style>
  .hidden-view {
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
  }
  h2 {
    margin: 0;
    font-size: var(--text-base);
    color: var(--text-strong);
  }
  .count {
    color: var(--text-subtle);
    font-weight: normal;
  }
  .hint {
    margin: var(--space-1) 0 var(--space-3);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  li {
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--border-faint);
  }
  li:first-child {
    border-top: none;
  }
  .head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .line {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
  }
  .muted {
    color: var(--text-muted);
  }
  .review {
    color: var(--warning);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
</style>
