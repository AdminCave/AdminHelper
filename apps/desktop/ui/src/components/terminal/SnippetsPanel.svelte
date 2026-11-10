<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  The snippets of the workspace (R-1071) in the panel of a terminal: a click runs one in the
  session, or with the broadcast on in every running SSH session. Until the workspace has a list
  of its own the panel shows the default one in the language of the app; the first change saves
  the whole list, and an empty list stays empty.
-->
<script lang="ts">
  import { Pencil, Plus, Trash2 } from '@lucide/svelte';
  import type { Snippet } from '$lib/bridge/types';
  import { t, tNow } from '$lib/i18n';
  import { setSnippets, settings } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { runSnippet, setSnippetBroadcast, snippetBroadcast } from '$lib/stores/terminals';
  import { errMsg } from '$lib/utils/errors';
  import Button from '../ui/Button.svelte';
  import Checkbox from '../ui/Checkbox.svelte';
  import { confirmDialog } from '../ui/ConfirmDialog.svelte';
  import FormField from '../ui/FormField.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Input from '../ui/Input.svelte';

  interface Props {
    /** The session a click runs a snippet in. */
    sessionKey: string;
    /** Whether that session runs: a snippet goes nowhere else. */
    running: boolean;
    /** After a snippet went out: the terminal takes the keys back. */
    onRun?: () => void;
  }

  let { sessionKey, running, onRun }: Props = $props();

  // Keys written out: the dictionary test looks for each.
  const DEFAULTS: [string, string][] = [
    ['terminal.snippets.default.df', 'df -h'],
    ['terminal.snippets.default.free', 'free -h'],
    ['terminal.snippets.default.uptime', 'uptime'],
    ['terminal.snippets.default.docker', 'docker ps'],
    ['terminal.snippets.default.nginx', 'systemctl status nginx'],
    ['terminal.snippets.default.failed', 'systemctl --failed'],
    ['terminal.snippets.default.last', 'last -n 5'],
  ];

  let snippets: Snippet[] = $derived(
    $settings?.snippets ?? DEFAULTS.map(([key, command]) => ({ name: $t(key), command })),
  );

  // The snippet the form edits as it was when the form opened, 'new', or no form.
  let editing = $state<Snippet | 'new' | null>(null);
  let name = $state('');
  let command = $state('');
  let busy = $state(false);
  let valid = $derived(name.trim() !== '' && command.trim() !== '');

  function same(a: Snippet, b: Snippet): boolean {
    return a.name === b.name && a.command === b.command;
  }

  function edit(snippet: Snippet | 'new'): void {
    name = snippet === 'new' ? '' : snippet.name;
    command = snippet === 'new' ? '' : snippet.command;
    editing = snippet;
  }

  async function save(list: Snippet[]): Promise<boolean> {
    busy = true;
    try {
      await setSnippets(list);
      return true;
    } catch (err) {
      reportError(errMsg(err));
      return false;
    } finally {
      busy = false;
    }
  }

  async function submit(e: SubmitEvent): Promise<void> {
    e.preventDefault();
    if (!valid || editing === null || busy) return;
    const snippet = { name: name.trim(), command: command.trimEnd() };
    // Found in the list as it is now: another tab may have changed it meanwhile. A snippet gone
    // from it keeps the edit at the end.
    const original = editing;
    const at = original === 'new' ? -1 : snippets.findIndex((s) => same(s, original));
    const list =
      at === -1 ? [...snippets, snippet] : snippets.map((s, i) => (i === at ? snippet : s));
    if (await save(list)) editing = null;
  }

  async function remove(snippet: Snippet): Promise<void> {
    const ok = await confirmDialog(
      tNow('terminal.snippets.confirmDelete', { name: snippet.name }),
      {
        confirmLabel: tNow('action.delete'),
      },
    );
    if (!ok) return;
    // The list as it is after the question, not as it was before it.
    const at = snippets.findIndex((s) => same(s, snippet));
    if (at === -1) return;
    if (editing !== null && editing !== 'new' && same(editing, snippet)) editing = null;
    await save(snippets.filter((_, i) => i !== at));
  }

  function run(snippet: Snippet): void {
    if (!running) return;
    void runSnippet(sessionKey, snippet.command).then((reached) => {
      // A broadcast that reached no session would otherwise pass without a trace.
      if (reached === 0) showStatus(tNow('terminal.snippets.broadcastNone'));
    });
    onRun?.();
  }
</script>

<div class="snips">
  <div class="snips-head">
    <span class="eyebrow">{$t('terminal.snippets')}</span>
    <Button
      size="sm"
      variant="secondary"
      iconLeft={Plus}
      disabled={busy || editing !== null}
      onclick={() => edit('new')}
    >
      {$t('terminal.snippets.new')}
    </Button>
  </div>

  {#if editing !== null}
    <form class="snips-form" onsubmit={submit}>
      <FormField label={$t('terminal.snippets.name')}>
        <Input size="sm" bind:value={name} fullWidth />
      </FormField>
      <FormField label={$t('terminal.snippets.command')}>
        <Input size="sm" bind:value={command} multiline rows={3} fullWidth />
      </FormField>
      <div class="snips-actions">
        <Button size="sm" variant="ghost" disabled={busy} onclick={() => (editing = null)}>
          {$t('action.cancel')}
        </Button>
        <Button size="sm" type="submit" disabled={!valid || busy}>{$t('action.save')}</Button>
      </div>
    </form>
  {/if}

  {#if snippets.length === 0}
    <p class="snips-empty">{$t('terminal.snippets.empty')}</p>
  {:else}
    <ul class="snips-list">
      {#each snippets as snippet, i (i)}
        <li class="snip">
          <button type="button" class="snip-run" disabled={!running} onclick={() => run(snippet)}>
            <span class="snip-name">{snippet.name}</span>
            <code class="snip-cmd">$ {snippet.command}</code>
          </button>
          <div class="snip-tools">
            <IconButton
              size="sm"
              icon={Pencil}
              label={$t('terminal.snippets.edit', { name: snippet.name })}
              disabled={busy}
              onclick={() => edit(snippet)}
            />
            <IconButton
              size="sm"
              icon={Trash2}
              label={$t('terminal.snippets.delete', { name: snippet.name })}
              disabled={busy}
              onclick={() => void remove(snippet)}
            />
          </div>
        </li>
      {/each}
    </ul>
  {/if}

  <div class="snips-broadcast">
    <Checkbox
      checked={$snippetBroadcast}
      label={$t('terminal.snippets.broadcast')}
      description={$t('terminal.snippets.broadcastHint')}
      onChange={(on) => void setSnippetBroadcast(on)}
    />
  </div>
</div>

<style>
  .snips {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .snips-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .snips-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg);
  }
  .snips-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .snips-empty {
    margin: 0;
    font-size: 12px;
    color: var(--text-muted);
  }
  .snips-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .snip {
    display: flex;
    align-items: flex-start;
    gap: 4px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg);
  }
  .snip-run {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 10px;
    border: 0;
    background: none;
    text-align: left;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .snip-run:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .snip-run:not(:disabled):hover .snip-name {
    color: var(--accent);
  }
  .snip-name {
    font-size: 12.5px;
    color: var(--text-strong);
  }
  .snip-cmd {
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-muted);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .snip-tools {
    display: flex;
    padding: 4px 4px 0 0;
  }
  .snips-broadcast {
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }
</style>
