<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { MonStatus } from '$lib/api/types';

  /** Concept §3.14: what is green is one line; a problem opens its card. */
  export function opensByDefault(status: MonStatus): boolean {
    return status !== 'ok' && status !== 'pending';
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '$lib/i18n';
  import Dot from '../../ui/Dot.svelte';
  import MonSectionIcon from '../section/MonSectionIcon.svelte';

  interface Props {
    title: string;
    /** null: a card without a status of its own (the findings inbox), no dot. */
    status: MonStatus | null;
    /** One line under the title, read while the card is closed. */
    summary?: string | null;
    /** Why the card's notifications are held back (`mutedReasonText`); shown open or closed. */
    note?: string | null;
    /** Buttons beside the toggle, e.g. "Store credentials". */
    actions?: Snippet;
    /** Open or closed before the admin chooses, in place of the status rule. */
    defaultOpen?: boolean;
    children: Snippet;
  }

  let {
    title,
    status,
    summary = null,
    note = null,
    actions,
    defaultOpen,
    children,
  }: Props = $props();

  const uid = $props.id();
  const bodyId = `${uid}-body`;
  // The admin's choice holds for the status it was made at: a card closed on a
  // warning opens again when it turns critical.
  let choice = $state<{ status: MonStatus | null; open: boolean } | null>(null);
  const open = $derived(
    choice && choice.status === status
      ? choice.open
      : (defaultOpen ?? (status !== null && opensByDefault(status))),
  );

  const statusLabel = $derived(
    status &&
      {
        ok: $t('monitoring.status.ok'),
        warning: $t('monitoring.status.warning'),
        critical: $t('monitoring.status.critical'),
        unknown: $t('monitoring.status.unknown'),
        pending: $t('monitoring.status.pending'),
      }[status],
  );

  function toggle(): void {
    choice = { status, open: !open };
  }
</script>

<section class="mon-card" data-status={status ?? undefined}>
  <div class="mon-card-head">
    <button
      type="button"
      class="mon-card-toggle"
      aria-expanded={open}
      aria-controls={open ? bodyId : undefined}
      onclick={toggle}
    >
      {#if status}
        <Dot st={status} label={statusLabel ?? undefined} />
      {/if}
      <span class="mon-card-titles">
        <span class="mon-card-title">{title}</span>
        {#if summary}
          <span class="mon-card-summary">{summary}</span>
        {/if}
      </span>
      <span class="mon-card-chevron" class:open aria-hidden="true">
        <MonSectionIcon name="chevron" />
      </span>
    </button>
    {#if actions}
      <div class="mon-card-actions">{@render actions()}</div>
    {/if}
  </div>
  {#if note}
    <p class="mon-card-note">{note}</p>
  {/if}
  {#if open}
    <div class="mon-card-body" id={bodyId}>{@render children()}</div>
  {/if}
</section>

<style>
  .mon-card {
    display: flex;
    flex-direction: column;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .mon-card[data-status='critical'] {
    border-color: var(--danger-border);
  }
  .mon-card[data-status='warning'] {
    border-color: var(--warning-border);
  }
  .mon-card-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding-right: var(--space-3);
  }
  .mon-card-toggle {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    padding: var(--space-3) var(--space-4);
    border: 0;
    border-radius: var(--radius-lg);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .mon-card-toggle:hover {
    background: var(--surface-hover);
  }
  .mon-card-toggle:focus-visible {
    outline: var(--ring-width) solid var(--accent);
    outline-offset: -2px;
  }
  .mon-card-titles {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .mon-card-title {
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 600;
  }
  .mon-card-summary {
    overflow: hidden;
    color: var(--text-muted);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-card-chevron {
    display: inline-flex;
    color: var(--text-subtle);
    transform: rotate(-90deg);
    transition: transform var(--dur-fast) var(--ease-standard);
  }
  .mon-card-chevron.open {
    transform: none;
  }
  .mon-card-actions {
    display: inline-flex;
    flex-shrink: 0;
    gap: var(--space-2);
  }
  .mon-card-note {
    margin: 0;
    padding: 0 var(--space-4) var(--space-3);
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .mon-card-body {
    min-width: 0;
    border-top: 1px solid var(--border-faint);
  }
</style>
