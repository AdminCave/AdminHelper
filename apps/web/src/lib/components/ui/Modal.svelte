<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount, onDestroy, type Snippet } from 'svelte';

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
      e.stopPropagation();
      close();
    }
  }

  function onBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) close();
  }

  onMount(() => {
    document.addEventListener('keydown', onKeydown);
  });
  onDestroy(() => {
    document.removeEventListener('keydown', onKeydown);
  });

  $effect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
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
