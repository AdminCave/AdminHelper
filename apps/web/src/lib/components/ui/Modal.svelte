<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  // Refcount of open modals sharing the global body-overflow lock: a
  // per-instance teardown alone would let Modal A's close clear overflow while
  // a stacked Modal B is still open. Only the last close restores scrolling.
  let openModalCount = 0;
  // Stack of open modal instances: Escape must only close the TOP modal.
  // Document keydown listeners fire in registration order (bottom modal
  // first) — without this check, Escape under a stacked ConfirmDialog would
  // close the editor modal underneath and leave the dialog orphaned.
  const modalStack: symbol[] = [];

  const FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
    'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
</script>

<script lang="ts">
  import { type Snippet } from 'svelte';
  import X from '@lucide/svelte/icons/x';
  import { t } from '$lib/i18n';
  import IconButton from './IconButton.svelte';

  interface Props {
    open: boolean;
    title?: string;
    description?: string;
    width?: string;
    onClose?: () => void;
    children: Snippet;
    footer?: Snippet;
  }

  let {
    open,
    title = '',
    description,
    width = '520px',
    onClose,
    children,
    footer,
  }: Props = $props();

  const instance = Symbol();
  const uid = $props.id();
  let panel: HTMLElement | undefined = $state();
  let returnTo: Element | null = null;

  function focusables(): HTMLElement[] {
    return panel ? [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)] : [];
  }

  // Tab and Shift+Tab stay inside the top-most dialog; the page behind it is inert.
  function trapTab(e: KeyboardEvent) {
    if (!panel) return;
    const all = focusables();
    if (all.length === 0) {
      e.preventDefault();
      panel.focus();
      return;
    }
    const first = all[0];
    const last = all[all.length - 1];
    const at = document.activeElement;
    const inside = at instanceof Node && panel.contains(at);
    if (e.shiftKey && (!inside || at === first || at === panel)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (!inside || at === last)) {
      e.preventDefault();
      first.focus();
    }
  }

  function close() {
    onClose?.();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Tab' && open) {
      if (modalStack[modalStack.length - 1] === instance) trapTab(e);
      return;
    }
    if (e.key === 'Escape' && open) {
      // Only the top-most open modal reacts (see modalStack above).
      if (modalStack[modalStack.length - 1] !== instance) return;
      // stopImmediatePropagation, not stopPropagation: each mounted modal adds
      // its own document keydown listener, so one Escape must not close two
      // stacked modals at once (2.136).
      e.stopImmediatePropagation();
      close();
    }
  }

  function onBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) close();
  }

  // Escape listener only while open — a closed modal must not keep a document
  // listener around (4.144).
  $effect(() => {
    if (!open) return;
    modalStack.push(instance);
    document.addEventListener('keydown', onKeydown);
    return () => {
      document.removeEventListener('keydown', onKeydown);
      const i = modalStack.indexOf(instance);
      if (i >= 0) modalStack.splice(i, 1);
    };
  });

  // Remember who had focus before the dialog took it; runs before the panel mounts.
  $effect.pre(() => {
    if (open) returnTo = document.activeElement;
  });

  // Initial focus: the first control of body, then footer, then the header close
  // button, else the panel. A control the content focused itself keeps its focus.
  // On close focus goes back where it came from.
  $effect(() => {
    if (!open || !panel) return;
    const el = panel;
    if (!el.contains(document.activeElement)) {
      const pick = (sel: string) =>
        el.querySelector<HTMLElement>(sel)?.querySelector<HTMLElement>(FOCUSABLE);
      (pick('.modal-body') ?? pick('.modal-footer') ?? focusables()[0] ?? el).focus();
    }
    const back = returnTo;
    return () => {
      if (back instanceof HTMLElement && back.isConnected) back.focus();
    };
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
    <div
      bind:this={panel}
      class="modal-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? `${uid}-title` : undefined}
      aria-describedby={description ? `${uid}-desc` : undefined}
      tabindex="-1"
      style:max-width={width}
    >
      {#if title}
        <div class="modal-header">
          <h3 class="modal-title" id="{uid}-title">{title}</h3>
          <IconButton icon={X} label={$t('action.close')} size="sm" onclick={close} />
        </div>
      {/if}
      <div class="modal-body">
        {#if description}<p class="modal-desc" id="{uid}-desc">{description}</p>{/if}
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
  /* DS dialog (AdminCave/DesignSystem components/feedback/Dialog): blurred scrim,
     raised panel with --radius-2xl, fade in and rise by 8px. */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(6px);
    animation: modal-fade var(--dur-base) var(--ease-out);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: var(--sp-4);
  }
  .modal-panel {
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius-2xl);
    box-shadow: var(--shadow-lg);
    animation: modal-rise var(--dur-base) var(--ease-out);
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
  .modal-panel:focus {
    outline: none;
  }
  .modal-desc {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  @keyframes modal-fade {
    from {
      opacity: 0;
    }
  }
  @keyframes modal-rise {
    from {
      opacity: 0;
      transform: translateY(8px) scale(0.98);
    }
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
