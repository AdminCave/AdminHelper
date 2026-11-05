<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import LayoutGrid from '@lucide/svelte/icons/layout-grid';
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
  }

  let { sessions, active, pageLabel, onSelect, onClose }: Props = $props();

  const ids = $derived([PAGE_TAB, ...sessions.map((s) => s.key)]);
  let buttons: HTMLButtonElement[] = $state([]);

  function statusLabel(status: TerminalStatus): string {
    if (status === 'connecting') return $t('terminal.status.connecting');
    if (status === 'connected') return $t('terminal.status.connected');
    return $t('terminal.status.disconnected');
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
    onSelect(ids[to]);
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
      <div class="session-tab-wrap" role="presentation" class:active={active === s.key}>
        <button
          bind:this={buttons[i + 1]}
          type="button"
          role="tab"
          class="session-tab"
          data-tab={s.key}
          aria-selected={active === s.key}
          aria-keyshortcuts="Delete"
          tabindex={active === s.key ? 0 : -1}
          onclick={() => onSelect(s.key)}
          onkeydown={(e) => onkeydown(e, i + 1)}
        >
          <SquareTerminal size={14} />
          <span class="session-tab-name">{s.connection.name}</span>
          <Dot st={s.status} size={7} label={statusLabel(s.status)} />
        </button>
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
