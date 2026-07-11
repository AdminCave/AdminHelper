<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  // Refcount of open modals sharing the global body-overflow lock (4.76): a per-instance teardown
  // alone would let Modal A's close clear overflow while a stacked Modal B is still open. Only the
  // last close restores scrolling.
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
      // stopImmediatePropagation, not stopPropagation: each mounted modal adds its
      // own document keydown listener, so one Escape must not fire every listener
      // on document (which would close two stacked modals at once) (2.136).
      e.stopImmediatePropagation();
      close();
    }
  }

  function onBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) close();
  }

  // Register the Escape listener only while open (replaces onMount/onDestroy): a closed or
  // background-mounted modal must not keep a document keydown listener around, and only a visible
  // modal should react. Stacking is still handled by stopImmediatePropagation above (2.136) (4.144).
  $effect(() => {
    if (!open) return;
    document.addEventListener('keydown', onKeydown);
    return () => document.removeEventListener('keydown', onKeydown);
  });

  $effect(() => {
    if (!open) return;
    // Lock body scroll while open; the returned teardown runs on close AND on destroy-while-open
    // — the leak that left the whole app unscrollable when a session expiry replaced an open modal
    // with the login page. Refcounted so a stacked modal keeps the lock until the last close.
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
    <div class="modal" role="dialog" aria-modal="true" style:max-width={width}>
      {#if title}
        <div class="modal-header">
          <h3>{title}</h3>
          <button class="modal-close" onclick={close} aria-label="Close">&times;</button>
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
