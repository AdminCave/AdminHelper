<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  // Refcount of open modals sharing the global body-overflow lock: a
  // per-instance teardown alone would let Modal A's close clear overflow while
  // a stacked Modal B is still open. Only the last close restores scrolling.
  // (Ported from the web panel's Modal, 4.76.)
  let openModalCount = 0;
</script>

<script lang="ts">
  import { type Snippet } from 'svelte';

  interface Props {
    open: boolean;
    title?: string;
    width?: string;
    onClose?: () => void;
    children: Snippet;
    footer?: Snippet;
  }

  let { open, title = '', width = '520px', onClose, children, footer }: Props = $props();

  function close() {
    onClose?.();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && open) {
      // stopImmediatePropagation, not stopPropagation: each mounted modal adds
      // its own document keydown listener, so one Escape must not close two
      // stacked modals at once (web 2.136).
      e.stopImmediatePropagation();
      close();
    }
  }

  function onBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) close();
  }

  // Escape listener only while open — a closed modal must not keep a document
  // listener around (web 4.144).
  $effect(() => {
    if (!open) return;
    document.addEventListener('keydown', onKeydown);
    return () => document.removeEventListener('keydown', onKeydown);
  });

  $effect(() => {
    if (!open) return;
    // Body-scroll lock while open; teardown runs on close AND destroy-while-
    // open. Refcounted for stacked modals (see module script).
    openModalCount += 1;
    document.body.style.overflow = 'hidden';
    return () => {
      openModalCount -= 1;
      if (openModalCount === 0) {
        document.body.style.overflow = '';
      }
    };
  });
</script>

{#if open}
  <div class="modal-backdrop" onclick={onBackdropClick} role="presentation">
    <div class="modal-panel" role="dialog" aria-modal="true" style:max-width={width}>
      {#if title}
        <div class="modal-header">
          <h3 class="modal-title">{title}</h3>
          <button class="btn ghost small" onclick={close} aria-label="Close">&times;</button>
        </div>
      {/if}
      <div class="modal-body">
        {@render children()}
      </div>
      {#if footer}
        <div class="modal-footer">
          {@render footer()}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* Visuals mirror the established .editor-overlay/.editor-panel look so
     migrated modals stay visually seamless (AdminCave design tokens). */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: var(--sp-4);
  }
  .modal-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-4) var(--sp-5);
    border-bottom: 1px solid var(--border);
  }
  .modal-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .modal-body {
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-5);
  }
  .modal-footer {
    display: flex;
    gap: var(--sp-2);
    padding: var(--sp-4) var(--sp-5);
    border-top: 1px solid var(--border);
    align-items: center;
    justify-content: flex-end;
  }
</style>
