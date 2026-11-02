<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    content: string;
    side?: 'top' | 'bottom' | 'left' | 'right';
    // The trigger; spread the props onto it so it is described by the tip.
    children: Snippet<[{ 'aria-describedby': string }]>;
  }

  let { content, side = 'top', children }: Props = $props();

  const uid = $props.id();
  const tipId = `${uid}-tip`;
  let show = $state(false);

  // Escape dismisses without moving focus or pointer (WCAG 1.4.13).
  $effect(() => {
    if (!show) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') show = false;
    };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  });
</script>

<span
  class="tip-root"
  role="presentation"
  onmouseenter={() => (show = true)}
  onmouseleave={() => (show = false)}
  onfocusin={() => (show = true)}
  onfocusout={() => (show = false)}
>
  {@render children({ 'aria-describedby': tipId })}
  <!-- Always in the DOM: aria-describedby reads hidden content, so the
       description is there before the tip is shown. -->
  <span id={tipId} class="tip tip-{side}" role="tooltip" hidden={!show}>{content}</span>
</span>

<style>
  .tip-root {
    position: relative;
    display: inline-flex;
  }
  .tip {
    position: absolute;
    z-index: 60;
    padding: 6px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    background: var(--surface-raised);
    box-shadow: var(--shadow-pop);
    color: var(--text-strong);
    font-size: var(--text-sm);
    font-weight: 500;
    white-space: nowrap;
    pointer-events: none;
  }
  .tip[hidden] {
    display: none;
  }
  .tip-top {
    bottom: 100%;
    left: 50%;
    margin-bottom: 8px;
    transform: translateX(-50%);
  }
  .tip-bottom {
    top: 100%;
    left: 50%;
    margin-top: 8px;
    transform: translateX(-50%);
  }
  .tip-left {
    right: 100%;
    top: 50%;
    margin-right: 8px;
    transform: translateY(-50%);
  }
  .tip-right {
    left: 100%;
    top: 50%;
    margin-left: 8px;
    transform: translateY(-50%);
  }
</style>
