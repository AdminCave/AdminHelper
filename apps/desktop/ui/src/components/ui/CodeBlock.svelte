<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';

  interface Props {
    code: string;
    // Header label; falls back to lang.
    filename?: string;
    lang?: string;
    copyable?: boolean;
  }

  let { code, filename, lang, copyable = true }: Props = $props();

  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      return;
    }
    copied = true;
    clearTimeout(timer);
    timer = setTimeout(() => (copied = false), 1600);
  }

  $effect(() => () => clearTimeout(timer));
</script>

<div class="code">
  {#if filename || lang || copyable}
    <div class="head">
      <span class="name">{filename ?? lang ?? ''}</span>
      {#if copyable}
        <button type="button" class="copy" class:copied onclick={copy}>
          {copied ? $t('ui.copied') : $t('action.copy')}
        </button>
      {/if}
    </div>
  {/if}
  <pre><code>{code}</code></pre>
  <span class="sr" role="status">{copied ? $t('ui.copied') : ''}</span>
</div>

<style>
  .code {
    position: relative;
    overflow: hidden;
    background: var(--surface-inset);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 10px 8px 14px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  .name {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-muted);
  }
  .copy {
    padding: 4px 8px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
    background: transparent;
    border: none;
    border-radius: var(--radius-pill);
    cursor: pointer;
    transition: color var(--dur-fast);
  }
  .copy:hover {
    color: var(--text);
  }
  .copy.copied {
    color: var(--success);
  }
  pre {
    margin: 0;
    padding: var(--space-4) var(--space-5);
    overflow-x: auto;
  }
  code {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    line-height: 1.5;
    color: var(--text);
    white-space: pre;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
