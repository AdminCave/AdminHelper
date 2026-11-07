<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import AppWindow from '@lucide/svelte/icons/app-window';
  import LayoutGrid from '@lucide/svelte/icons/layout-grid';
  import SquareArrowOutUpRight from '@lucide/svelte/icons/square-arrow-out-up-right';
  import SquareTerminal from '@lucide/svelte/icons/square-terminal';
  import X from '@lucide/svelte/icons/x';
  import { t } from '$lib/i18n';
  import { PAGE_TAB, type TerminalSession, type TerminalStatus } from '$lib/stores/terminals';
  import Dot from '../ui/Dot.svelte';
  import { nextIndex } from '../ui/roving';

  interface Props {
    sessions: TerminalSession[];
    /** PAGE_TAB or the key of a session. */
    active: string;
    /** The name of the page the sidebar shows. */
    pageLabel: string;
    onSelect: (tab: string) => void;
    onClose: (session: TerminalSession) => void;
    /** Moves a running session into a window of its own, or brings that window to the front. */
    onDetach: (session: TerminalSession) => void;
  }

  let { sessions, active, pageLabel, onSelect, onClose, onDetach }: Props = $props();

  // As in the mockup (chrome.jsx): a tab pulled this far down leaves the bar.
  const DETACH_DRAG = 46;

  const ids = $derived([PAGE_TAB, ...sessions.map((s) => s.key)]);
  let buttons: HTMLButtonElement[] = $state([]);

  function statusLabel(status: TerminalStatus): string {
    if (status === 'connecting') return $t('terminal.status.connecting');
    if (status === 'connected') return $t('terminal.status.connected');
    return $t('terminal.status.disconnected');
  }

  // Only a program that runs has something to show in a window of its own.
  const canDetach = (s: TerminalSession) => s.status !== 'disconnected' && s.backendId !== null;

  // A click on a detached tab brings its window to the front; the tab itself never is.
  function select(s: TerminalSession): void {
    if (s.detached) onDetach(s);
    else onSelect(s.key);
  }

  // Pulling a tab down detaches it. The click that ends the pull is not a selection.
  let drag: { key: string; pointer: number; y: number } | null = null;
  let pulled = false;

  function onpointerdown(e: PointerEvent, s: TerminalSession): void {
    pulled = false;
    if (e.button !== 0 || s.detached || !canDetach(s)) return;
    drag = { key: s.key, pointer: e.pointerId, y: e.clientY };
    // Below the bar the pointer leaves the tab; its moves still come here.
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  function onpointermove(e: PointerEvent, s: TerminalSession): void {
    if (drag?.key !== s.key || drag.pointer !== e.pointerId) return;
    if (e.clientY - drag.y < DETACH_DRAG) return;
    drag = null;
    pulled = true;
    onDetach(s);
  }

  function onclick(s: TerminalSession): void {
    if (pulled) {
      pulled = false;
      return;
    }
    select(s);
  }

  // As the other tab bars of the app: the arrow keys move focus and selection together. The
  // close buttons stay out of the tab order; Delete closes the session in front of the keyboard.
  function onkeydown(e: KeyboardEvent, i: number): void {
    const session = sessions[i - 1];
    if (e.key === 'Delete' && session) {
      e.preventDefault();
      onClose(session);
      return;
    }
    const to = nextIndex(e.key, i, ids.length);
    if (to === undefined) return;
    e.preventDefault();
    // Moving the focus over a detached tab does not pull its window over this one.
    if (!sessions[to - 1]?.detached) onSelect(ids[to]);
    buttons[to]?.focus();
  }
</script>

{#if sessions.length > 0}
  <div class="session-tabs" role="tablist" aria-label={$t('terminal.tabs')}>
    <button
      bind:this={buttons[0]}
      type="button"
      role="tab"
      class="session-tab"
      data-tab={PAGE_TAB}
      aria-selected={active === PAGE_TAB}
      tabindex={active === PAGE_TAB ? 0 : -1}
      onclick={() => onSelect(PAGE_TAB)}
      onkeydown={(e) => onkeydown(e, 0)}
    >
      <LayoutGrid size={14} />
      <span class="session-tab-name">{pageLabel}</span>
    </button>
    <span class="session-tabs-sep" aria-hidden="true"></span>
    {#each sessions as s, i (s.key)}
      <div
        class="session-tab-wrap"
        role="presentation"
        class:active={active === s.key}
        class:detached={s.detached}
      >
        <button
          bind:this={buttons[i + 1]}
          type="button"
          role="tab"
          class="session-tab"
          data-tab={s.key}
          aria-selected={active === s.key}
          aria-keyshortcuts="Delete"
          tabindex={active === s.key ? 0 : -1}
          title={s.detached ? $t('terminal.tabs.detached') : undefined}
          onclick={() => onclick(s)}
          ondblclick={() => {
            if (!s.detached && canDetach(s)) onDetach(s);
          }}
          onpointerdown={(e) => onpointerdown(e, s)}
          onpointermove={(e) => onpointermove(e, s)}
          onpointerup={() => (drag = null)}
          onpointercancel={() => (drag = null)}
          onkeydown={(e) => onkeydown(e, i + 1)}
        >
          {#if s.detached}
            <AppWindow size={14} />
          {:else}
            <SquareTerminal size={14} />
          {/if}
          <span class="session-tab-name">{s.connection.name}</span>
          <Dot st={s.status} size={7} label={statusLabel(s.status)} />
        </button>
        {#if !s.detached && canDetach(s)}
          <button
            type="button"
            class="session-tab-close"
            tabindex="-1"
            aria-label={$t('terminal.tabs.detach', { name: s.connection.name })}
            title={$t('terminal.tabs.detach', { name: s.connection.name })}
            onclick={() => onDetach(s)}
          >
            <SquareArrowOutUpRight size={13} />
          </button>
        {/if}
        <button
          type="button"
          class="session-tab-close"
          tabindex="-1"
          aria-label={$t('terminal.tabs.close', { name: s.connection.name })}
          title={$t('terminal.tabs.close', { name: s.connection.name })}
          onclick={() => onClose(s)}
        >
          <X size={13} />
        </button>
      </div>
    {/each}
  </div>
{/if}

<style>
  .session-tabs {
    display: flex;
    flex: 0 0 auto;
    align-items: flex-end;
    gap: 2px;
    padding: 8px 16px 0;
    border-bottom: 1px solid var(--border);
    background: var(--bg-subtle);
    overflow-x: auto;
  }
  .session-tab,
  .session-tab-wrap {
    display: flex;
    align-items: center;
    height: 34px;
    margin-bottom: -1px;
    border: 1px solid transparent;
    border-bottom: none;
    border-radius: var(--radius-md) var(--radius-md) 0 0;
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    user-select: none;
  }
  .session-tab {
    gap: 8px;
    padding: 0 12px;
    cursor: pointer;
  }
  .session-tab-wrap {
    padding-right: 8px;
  }
  .session-tab-wrap .session-tab {
    height: 100%;
    margin: 0;
    border: 0;
    padding-right: 6px;
    color: inherit;
    font-weight: inherit;
  }
  .session-tab:hover,
  .session-tab-wrap:hover {
    color: var(--text);
  }
  .session-tab[aria-selected='true'],
  .session-tab-wrap.active {
    border-color: var(--border);
    background: var(--bg);
    color: var(--text-strong);
    font-weight: 600;
  }
  .session-tab-wrap .session-tab[aria-selected='true'] {
    background: transparent;
  }
  .session-tab-wrap.detached .session-tab-name {
    font-style: italic;
  }
  .session-tabs-sep {
    flex: none;
    width: 1px;
    height: 18px;
    margin: 0 6px 8px;
    background: var(--border);
  }
  .session-tab-close {
    display: inline-flex;
    padding: 2px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--text-subtle);
    cursor: pointer;
  }
  .session-tab-close:hover {
    background: var(--surface-hover);
    color: var(--text);
  }
</style>
