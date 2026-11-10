<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  One session of the embedded terminal (R-1069): xterm.js on the output of its program, above it
  what the session is connected to, search and options, below it the size and the status. The
  snippets (R-1071) and the files of the host (R-1072) open in the panel of the options. In a
  detached window (R-1070) the header has the search and Dock only: that window may not save the
  options, start a program or end one, and its title bar names the session.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Terminal } from '@xterm/xterm';
  import { FitAddon } from '@xterm/addon-fit';
  import { SearchAddon } from '@xterm/addon-search';
  import '@xterm/xterm/css/xterm.css';
  import {
    AArrowDown,
    AArrowUp,
    Cable,
    FolderOpen,
    RotateCw,
    SlidersHorizontal,
    SquareArrowDownLeft,
    SquareCode,
    X,
  } from '@lucide/svelte';
  import type { TerminalPrefs } from '$lib/bridge/types';
  import { currentLocale, t } from '$lib/i18n';
  import { TERMINAL_FONT_SIZE } from '$lib/models/settings';
  import {
    attachTerminal,
    reconnectTerminal,
    resizeTerminal,
    snippetBroadcast,
    terminals,
    writeTerminal,
    type TerminalSession,
  } from '$lib/stores/terminals';
  import { saveTerminalPrefs, terminalPrefs } from '$lib/stores/terminalPrefs';
  import { tunnelMappings } from '$lib/stores/tunnel';
  import { sanitizePaste } from '$lib/terminal/paste';
  import { terminalTheme } from '$lib/terminal/themes';
  import Button from '../ui/Button.svelte';
  import Dot from '../ui/Dot.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Pill from '../ui/Pill.svelte';
  import SearchField from '../ui/SearchField.svelte';
  import FilesPanel from './FilesPanel.svelte';
  import SnippetsPanel from './SnippetsPanel.svelte';
  import TerminalOptions from './TerminalOptions.svelte';

  interface Props {
    session: TerminalSession;
    /** "End session": the tab closes, after asking when the options say so. */
    onClose?: () => void;
    /** Given in a detached window: "Dock" takes the session back into the main window. */
    onDock?: () => void;
  }

  let { session, onClose, onDock }: Props = $props();

  const PASTE_HINT_MS = 6000;
  const encoder = new TextEncoder();

  let host: HTMLDivElement;
  let term: Terminal | null = null;
  let fit: FitAddon | null = null;
  let search: SearchAddon | null = null;
  // The options the terminal has, to change only what changed.
  let applied: TerminalPrefs | null = null;

  let cols = $state(80);
  let rows = $state(24);
  let query = $state('');
  // The side panel shown: one at a time.
  let panel = $state<'options' | 'snippets' | 'files' | null>(null);
  let pasteHint = $state(false);
  // A paste of several lines held back until confirmed (option confirmMultilinePaste).
  let pendingPaste = $state<string | null>(null);
  let hintTimer: ReturnType<typeof setTimeout> | undefined;

  let target = $derived.by(() => {
    const c = session.connection;
    // A playbook run (R-1073) has no host of its own: it names the playbook.
    if (session.ansible) return session.ansible.check ? `${c.name} --check` : c.name;
    const user = c.username ? `${c.username}@` : '';
    const port = c.port && c.port !== 22 ? `:${c.port}` : '';
    return `${user}${c.host ?? ''}${port}`;
  });
  // As the connection list shows it: the last enabled mapping for the connection.
  let tunnel = $derived(
    $tunnelMappings.filter((m) => m.enabled && m.connectionId === session.connection.id).at(-1)
      ?.name ?? null,
  );
  let statusText = $derived.by(() => {
    if (session.status === 'connecting') return $t('terminal.status.connecting');
    if (session.status === 'connected') {
      // A detached window does not know since when.
      if (session.connectedAt === null) return $t('terminal.status.connected');
      return $t('terminal.status.connectedSince', { time: clock(session.connectedAt) });
    }
    return session.exitCode === null
      ? $t('terminal.status.disconnected')
      : $t('terminal.status.exited', { code: session.exitCode });
  });
  let background = $derived(terminalTheme($terminalPrefs.theme).background);

  function clock(ms: number | null): string {
    if (ms === null) return '';
    return new Date(ms).toLocaleTimeString(currentLocale(), {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  // fonts.ready alone may resolve before anything asked for the face: xterm would measure its
  // cells with a fallback font and keep that width.
  function fontLoaded(family: string, size: number): Promise<unknown> {
    if (!('fonts' in document)) return Promise.resolve();
    return document.fonts.load(`${size}px ${family}`).then(
      () => document.fonts.ready,
      () => undefined,
    );
  }

  // A pane in the background has no size: the terminal keeps its last one until it shows again.
  function refit(): void {
    if (!fit || host.clientWidth === 0 || host.clientHeight === 0) return;
    fit.fit();
  }

  function apply(prefs: TerminalPrefs): void {
    if (!term || !applied) return;
    const options = term.options;
    if (prefs.theme !== applied.theme) options.theme = terminalTheme(prefs.theme);
    if (prefs.cursor !== applied.cursor) options.cursorStyle = prefs.cursor;
    if (prefs.scrollback !== applied.scrollback) options.scrollback = prefs.scrollback;
    const resized = prefs.fontSize !== applied.fontSize;
    if (resized) options.fontSize = prefs.fontSize;
    applied = prefs;
    if (resized) refit();
  }

  $effect(() => {
    apply($terminalPrefs);
  });

  function copy(text: string): void {
    if (!text) return;
    // Nothing to tell when the webview refuses: the selection stays and Ctrl+Shift+C tries again.
    navigator.clipboard?.writeText(text).catch(() => {});
  }

  // Once the mouse is released, wherever: a selection made with it ends there. A selection the
  // search makes is not copied.
  function copySelection(): void {
    if (term && $terminalPrefs.copyOnSelect && term.hasSelection()) copy(term.getSelection());
  }

  function onMouseDown(e: MouseEvent): void {
    if (e.button === 0) window.addEventListener('mouseup', copySelection, { once: true });
  }

  function showPasteHint(): void {
    pasteHint = true;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => (pasteHint = false), PASTE_HINT_MS);
  }

  function paste(text: string): void {
    const clean = sanitizePaste(text);
    // Without bracketed paste on the other side, every line but the last runs at once.
    if (clean && $terminalPrefs.confirmMultilinePaste && /[\r\n]/.test(clean)) {
      pendingPaste = clean;
      return;
    }
    if (clean) term?.paste(clean);
    term?.focus();
  }

  function settlePaste(confirmed: boolean): void {
    if (confirmed && pendingPaste) term?.paste(pendingPaste);
    pendingPaste = null;
    term?.focus();
  }

  // A final line break ends the last line and starts no new one.
  function lineCount(text: string): number {
    return text.replace(/(\r\n|\r|\n)$/, '').split(/\r\n|\r|\n/).length;
  }

  // xterm keeps Tab for itself, so the bar takes the focus, on Cancel: an Enter typed for the
  // shell then drops the text instead of running it.
  function focusCancel(node: HTMLElement): void {
    node.querySelector<HTMLButtonElement>('button')?.focus();
  }

  function onConfirmKey(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    settlePaste(false);
  }

  async function pasteClipboard(): Promise<void> {
    let text: string;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      // The webview may not let the page read the clipboard; its own paste still works.
      showPasteHint();
      return;
    }
    paste(text);
  }

  // The paste of the webview (Ctrl+Shift+V, its menu) goes the way of a right click: taken here,
  // before xterm's own handler, which would pass the text on as it is.
  function onPaste(e: ClipboardEvent): void {
    e.preventDefault();
    e.stopPropagation();
    paste(e.clipboardData?.getData('text/plain') ?? '');
  }

  function onContextMenu(e: MouseEvent): void {
    if (!$terminalPrefs.rightClickPaste) return;
    e.preventDefault();
    void pasteClipboard();
  }

  // Ctrl+Shift+C and Ctrl+Shift+V stay with the app, every other key goes to the program, Ctrl+C
  // among them. False tells xterm to leave the key alone; for Ctrl+Shift+V the paste of the
  // webview follows (onPaste).
  function onKey(e: KeyboardEvent): boolean {
    if (!e.ctrlKey || !e.shiftKey || e.altKey || e.metaKey) return true;
    const key = e.key.toLowerCase();
    if (key === 'c') {
      if (e.type === 'keydown') {
        e.preventDefault();
        if (term?.hasSelection()) copy(term.getSelection());
      }
      return false;
    }
    return key !== 'v';
  }

  function onSearchKey(e: KeyboardEvent): void {
    if (e.key !== 'Enter' || !search || query === '') return;
    e.preventDefault();
    if (e.shiftKey) search.findPrevious(query);
    else search.findNext(query);
  }

  function changeFont(step: number): void {
    const prefs = $terminalPrefs;
    const fontSize = Math.max(
      TERMINAL_FONT_SIZE.min,
      Math.min(TERMINAL_FONT_SIZE.max, prefs.fontSize + step),
    );
    if (fontSize !== prefs.fontSize) void saveTerminalPrefs({ ...prefs, fontSize });
  }

  function toggle(which: 'options' | 'snippets' | 'files'): void {
    panel = panel === which ? null : which;
  }

  function reconnect(): void {
    // The new program starts on an empty terminal, without the modes the last one left set
    // (alternate screen, mouse reports).
    term?.reset();
    pendingPaste = null;
    void reconnectTerminal(session.key);
    term?.focus();
  }

  onMount(() => {
    let disposed = false;
    let teardown = (): void => {};
    const key = session.key;
    const family =
      getComputedStyle(document.documentElement).getPropertyValue('--font-mono').trim() ||
      'monospace';

    void fontLoaded(family, $terminalPrefs.fontSize).then(() => {
      if (disposed) return;
      const prefs = $terminalPrefs;
      const terminal = new Terminal({
        fontFamily: family,
        fontSize: prefs.fontSize,
        theme: terminalTheme(prefs.theme),
        cursorStyle: prefs.cursor,
        scrollback: prefs.scrollback,
        // Output of a remote host opens nothing: without a handler xterm opens OSC 8 links
        // after a question.
        linkHandler: { activate: () => {} },
      });
      const fitAddon = new FitAddon();
      const searchAddon = new SearchAddon();
      terminal.loadAddon(fitAddon);
      terminal.loadAddon(searchAddon);
      terminal.open(host);
      term = terminal;
      fit = fitAddon;
      search = searchAddon;
      applied = prefs;
      cols = terminal.cols;
      rows = terminal.rows;

      const subscriptions = [
        terminal.onData((data) => writeTerminal(key, encoder.encode(data))),
        // One byte per character: mouse reports of the old encoding.
        terminal.onBinary((data) =>
          writeTerminal(
            key,
            Uint8Array.from(data, (c) => c.charCodeAt(0) & 0xff),
          ),
        ),
        terminal.onResize((size) => {
          cols = size.cols;
          rows = size.rows;
          resizeTerminal(key, size.cols, size.rows);
        }),
      ];
      terminal.attachCustomKeyEventHandler(onKey);
      const detach = attachTerminal(key, (data, parsed) => terminal.write(data, parsed));
      const observer =
        typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => refit());
      observer?.observe(host);
      refit();
      apply($terminalPrefs);
      // A start from a dialog (Connect in the connection editor) leaves the dialog open: the
      // keys stay with it, not with the terminal behind it.
      if (!document.querySelector('[aria-modal="true"]')) terminal.focus();

      teardown = () => {
        observer?.disconnect();
        detach();
        for (const s of subscriptions) s.dispose();
        terminal.dispose();
        term = null;
        fit = null;
        search = null;
        applied = null;
      };
    });

    return () => {
      disposed = true;
      clearTimeout(hintTimer);
      teardown();
    };
  });
</script>

<div class="term">
  <header class="term-head">
    <Dot st={session.status} ring label={statusText} />
    {#if !onDock}
      <span class="term-target">{target}</span>
    {/if}
    {#if tunnel}
      <Pill tone="accent" title={$t('terminal.tunnel')}><Cable size={11} />{tunnel}</Pill>
    {/if}
    <span class="term-spacer"></span>
    <div class="term-search">
      <SearchField
        size="sm"
        bind:value={query}
        placeholder={$t('terminal.search')}
        label={$t('terminal.search')}
        onkeydown={onSearchKey}
        onClear={() => term?.clearSelection()}
      />
    </div>
    {#if onDock}
      <span class="term-sep" aria-hidden="true"></span>
      <Button size="sm" variant="secondary" iconLeft={SquareArrowDownLeft} onclick={onDock}>
        {$t('terminal.dock')}
      </Button>
    {:else}
      <IconButton
        size="sm"
        icon={AArrowDown}
        label={$t('terminal.fontSmaller')}
        disabled={$terminalPrefs.fontSize <= TERMINAL_FONT_SIZE.min}
        onclick={() => changeFont(-1)}
      />
      <IconButton
        size="sm"
        icon={AArrowUp}
        label={$t('terminal.fontLarger')}
        disabled={$terminalPrefs.fontSize >= TERMINAL_FONT_SIZE.max}
        onclick={() => changeFont(1)}
      />
      {#if !session.ansible}
        <IconButton
          size="sm"
          icon={SquareCode}
          label={$t('terminal.snippets')}
          aria-pressed={panel === 'snippets'}
          onclick={() => toggle('snippets')}
        />
        <IconButton
          size="sm"
          icon={FolderOpen}
          label={$t('terminal.files')}
          aria-pressed={panel === 'files'}
          onclick={() => toggle('files')}
        />
      {/if}
      <IconButton
        size="sm"
        icon={SlidersHorizontal}
        label={$t('terminal.options')}
        aria-pressed={panel === 'options'}
        onclick={() => toggle('options')}
      />
      <span class="term-sep" aria-hidden="true"></span>
      {#if !session.ansible}
        <IconButton
          size="sm"
          icon={RotateCw}
          label={$t('terminal.reconnect')}
          onclick={reconnect}
        />
      {/if}
      <IconButton size="sm" icon={X} label={$t('terminal.close')} onclick={onClose} />
    {/if}
  </header>

  <div class="term-main">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="term-body"
      style:background
      onmousedown={onMouseDown}
      oncontextmenu={onContextMenu}
      onpastecapture={onPaste}
    >
      <div class="term-host" bind:this={host}></div>
      {#if session.status === 'disconnected'}
        <div class="term-ended">
          {#if onDock}
            <Button size="sm" variant="secondary" iconLeft={SquareArrowDownLeft} onclick={onDock}>
              {$t('terminal.dock')}
            </Button>
          {:else if !session.ansible}
            <Button size="sm" variant="secondary" iconLeft={RotateCw} onclick={reconnect}>
              {$t('terminal.reconnect')}
            </Button>
          {/if}
          <span>{$t('terminal.ended')}</span>
        </div>
      {/if}
    </div>
    {#if panel === 'options'}
      <aside class="term-panel" aria-label={$t('terminal.options')}>
        <TerminalOptions prefs={$terminalPrefs} onChange={(p) => void saveTerminalPrefs(p)} />
      </aside>
    {:else if panel === 'snippets' && !onDock && !session.ansible}
      <aside class="term-panel" aria-label={$t('terminal.snippets')}>
        <SnippetsPanel
          sessionKey={session.key}
          running={session.status === 'connected'}
          onRun={() => term?.focus()}
        />
      </aside>
    {:else if panel === 'files' && !onDock && !session.ansible}
      <aside class="term-panel" aria-label={$t('terminal.files')}>
        <FilesPanel
          session={session.backendId}
          running={session.status === 'connected'}
          shown={$terminals.active === session.key}
        />
      </aside>
    {/if}
  </div>

  {#if pendingPaste !== null}
    {@const confirmText = $t('terminal.pasteConfirm', { n: lineCount(pendingPaste) })}
    <div
      class="term-confirm"
      role="alertdialog"
      tabindex="-1"
      aria-label={confirmText}
      use:focusCancel
      onkeydown={onConfirmKey}
    >
      <span>{confirmText}</span>
      <span class="term-spacer"></span>
      <Button size="sm" variant="secondary" onclick={() => settlePaste(false)}>
        {$t('terminal.pasteConfirm.cancel')}
      </Button>
      <Button size="sm" onclick={() => settlePaste(true)}>
        {$t('terminal.pasteConfirm.paste')}
      </Button>
    </div>
  {/if}

  <footer class="term-foot">
    <span>{cols}×{rows}</span>
    {#if pasteHint}
      <span class="term-hint" role="status">{$t('terminal.pasteHint')}</span>
    {/if}
    {#if $snippetBroadcast && !session.ansible}
      <span class="term-broadcast">{$t('terminal.snippets.broadcastActive')}</span>
    {/if}
    <span class="term-spacer"></span>
    <span>{statusText}</span>
  </footer>
</div>

<style>
  .term {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--bg);
  }
  .term-head {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 46px;
    padding: 0 10px 0 16px;
    border-bottom: 1px solid var(--border);
    flex: 0 0 auto;
    overflow: hidden;
  }
  .term-target {
    font-family: var(--font-mono);
    font-size: 12.5px;
    color: var(--text-strong);
    white-space: nowrap;
  }
  .term-spacer {
    flex: 1;
  }
  .term-search {
    width: 190px;
  }
  .term-sep {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 4px;
  }
  .term-main {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  /* The padding sits here: the fit addon measures the host without it. */
  .term-body {
    position: relative;
    flex: 1;
    min-width: 0;
    padding: 10px 14px;
  }
  .term-host {
    width: 100%;
    height: 100%;
  }
  .term-ended {
    position: absolute;
    left: 14px;
    bottom: 14px;
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
    font-size: 12px;
    color: var(--text-muted);
  }
  .term-panel {
    width: 290px;
    flex: 0 0 auto;
    border-left: 1px solid var(--border);
    background: var(--surface);
    overflow-y: auto;
    padding: 16px;
  }
  .term-foot {
    display: flex;
    gap: 16px;
    align-items: center;
    height: 26px;
    padding: 0 16px;
    border-top: 1px solid var(--border);
    background: var(--bg-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
    flex: 0 0 auto;
    overflow: hidden;
    white-space: nowrap;
  }
  .term-confirm {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-top: 1px solid var(--border);
    background: var(--bg-subtle);
    font-size: 12px;
    color: var(--warning);
    flex: 0 0 auto;
  }
  .term-hint,
  .term-broadcast {
    color: var(--warning);
  }
</style>
