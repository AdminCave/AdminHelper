<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts" module>
  import type { Component } from 'svelte';

  export interface MenuItem {
    label?: string;
    icon?: Component<{ size?: number }>;
    onClick?: () => void;
    danger?: boolean;
    separator?: boolean;
    shortcut?: string;
  }

  // Spread onto the page's trigger button: it opens the menu and announces it.
  export interface TriggerProps {
    'aria-haspopup': 'menu';
    'aria-expanded': boolean;
    'aria-controls': string;
    onclick: (e: MouseEvent) => void;
    onkeydown: (e: KeyboardEvent) => void;
  }
</script>

<script lang="ts">
  import { tick, type Snippet } from 'svelte';
  import { nextIndex } from './roving';

  interface Props {
    items: MenuItem[];
    trigger: Snippet<[TriggerProps]>;
    align?: 'start' | 'end';
    width?: number;
  }

  let { items, trigger, align = 'start', width = 200 }: Props = $props();

  const uid = $props.id();
  const menuId = `${uid}-menu`;
  let open = $state(false);
  let root: HTMLElement | undefined = $state();
  let menu: HTMLElement | undefined = $state();
  let returnTo: HTMLElement | null = null;

  function entries(): HTMLButtonElement[] {
    return menu ? [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')] : [];
  }

  async function show(from: HTMLElement, last = false) {
    returnTo = from;
    open = true;
    await tick();
    const list = entries();
    list[last ? list.length - 1 : 0]?.focus();
  }

  function close(refocus: boolean) {
    open = false;
    if (refocus) returnTo?.focus();
  }

  const triggerProps: TriggerProps = {
    'aria-haspopup': 'menu',
    get 'aria-expanded'() {
      return open;
    },
    'aria-controls': menuId,
    onclick: (e) => {
      if (open) close(false);
      else void show(e.currentTarget as HTMLElement);
    },
    onkeydown: (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        void show(e.currentTarget as HTMLElement, e.key === 'ArrowUp');
      }
    },
  };

  function onMenuKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close(true);
      return;
    }
    if (e.key === 'Tab') {
      close(false);
      return;
    }
    const list = entries();
    const to = nextIndex(
      e.key,
      list.indexOf(document.activeElement as HTMLButtonElement),
      list.length,
    );
    if (to === undefined) return;
    e.preventDefault();
    list[to].focus();
  }

  function choose(item: MenuItem) {
    close(true);
    item.onClick?.();
  }

  $effect(() => {
    if (!open) return;
    const outside = (e: MouseEvent) => {
      if (root && !root.contains(e.target as Node)) close(false);
    };
    document.addEventListener('mousedown', outside);
    return () => document.removeEventListener('mousedown', outside);
  });
</script>

<div class="menu-root" bind:this={root}>
  {@render trigger(triggerProps)}
  {#if open}
    <div
      bind:this={menu}
      id={menuId}
      class="menu"
      class:end={align === 'end'}
      role="menu"
      tabindex="-1"
      style:width="{width}px"
      onkeydown={onMenuKey}
    >
      {#each items as it, i (i)}
        {#if it.separator}
          <div class="sep" role="separator"></div>
        {:else}
          <button
            type="button"
            role="menuitem"
            class="item"
            class:danger={it.danger}
            tabindex="-1"
            onclick={() => choose(it)}
          >
            {#if it.icon}<span class="icon"><it.icon size={16} /></span>{/if}
            <span class="label">{it.label}</span>
            {#if it.shortcut}<span class="shortcut">{it.shortcut}</span>{/if}
          </button>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .menu-root {
    position: relative;
    display: inline-flex;
  }
  .menu {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 70;
    box-sizing: border-box;
    padding: 6px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--surface-raised);
    box-shadow: var(--shadow-pop);
  }
  .menu.end {
    left: auto;
    right: 0;
  }
  .sep {
    height: 1px;
    margin: 6px 0;
    background: var(--border);
  }
  .item {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 8px 10px;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: var(--text-base);
    text-align: left;
    cursor: pointer;
  }
  .item:hover,
  .item:focus-visible {
    background: var(--surface-hover);
  }
  .icon {
    display: inline-flex;
    flex: 0 0 auto;
    color: var(--text-muted);
  }
  .danger,
  .danger .icon {
    color: var(--danger);
  }
  .label {
    flex: 1;
  }
  .shortcut {
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
  }
</style>
