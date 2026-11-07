<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  The files of an SSH session (R-1072) in the panel of a terminal: a folder of the host over the
  SFTP channel of the session, opened at the login directory. A click on a folder goes into it, on
  a file downloads it; uploads come from the file dialog or from files dropped on the window, into
  the folder shown, and a file that exists there is replaced only after a question. The local
  paths never pass through here: Rust holds them under a number (sftp.rs).
-->
<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import {
    CornerLeftUp,
    File,
    FileSymlink,
    Folder,
    FolderPlus,
    RefreshCw,
    Upload,
  } from '@lucide/svelte';
  import { sftpDownload, sftpList, sftpMkdir, sftpUpload, sftpUploadDropped } from '$lib/bridge';
  import type { SftpDrop, SftpEntry, SftpTransfer, SftpUploaded } from '$lib/bridge/types';
  import { currentLocale, t, tNow } from '$lib/i18n';
  import { errCode, errMsg } from '$lib/utils/errors';
  import Button from '../ui/Button.svelte';
  import { confirmDialog } from '../ui/ConfirmDialog.svelte';
  import FormField from '../ui/FormField.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Input from '../ui/Input.svelte';
  import Pill from '../ui/Pill.svelte';

  interface Props {
    /** The session in Rust; null until it started. */
    session: number | null;
    /** Whether its program runs: the SFTP channel goes over its connection. */
    running: boolean;
    /** Whether the session is the tab shown: files dropped on the window go to that one only. */
    shown: boolean;
  }

  let { session, running, shown }: Props = $props();

  // Without a ControlMaster (Windows) the channel logs in on its own, with a key or the agent
  // only: a refused login there needs a word on why.
  function onWindows(): boolean {
    return (
      typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('windows')
    );
  }
  const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];
  // Control characters and the bidi controls a host could put into a name to make it read as
  // another one; shown as a replacement character, sent to the host as they are.
  const HIDDEN = /[\p{Cc}\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/gu;

  let path = $state('.');
  let entries = $state<SftpEntry[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let keyHint = $state(false);
  // Whether an action of this session got through: the channel logged in. Rust reports what the
  // host refuses later (a folder, a name) with the same code as a refused login.
  let reached = false;
  let progress = $state<SftpTransfer | null>(null);
  let naming = $state(false);
  let folder = $state('');
  let ready = $derived(running && session !== null);
  let folderValid = $derived.by(() => {
    const name = folder.trim();
    return name !== '' && name !== '.' && name !== '..' && !name.includes('/');
  });

  function child(dir: string, name: string): string {
    return dir.endsWith('/') ? `${dir}${name}` : `${dir}/${name}`;
  }

  function shownName(name: string): string {
    return name.replace(HIDDEN, '\ufffd');
  }

  function size(bytes: number): string {
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < UNITS.length - 1) {
      value /= 1024;
      unit += 1;
    }
    const digits = unit === 0 ? 0 : 1;
    return `${value.toLocaleString(currentLocale(), { maximumFractionDigits: digits })} ${UNITS[unit]}`;
  }

  function onProgress(step: SftpTransfer): void {
    progress = step;
  }

  // One action at a time: the panel shows its progress and its error.
  async function act(work: (id: number) => Promise<void>): Promise<void> {
    if (session === null || !running) return;
    if (busy) {
      error = tNow('terminal.files.busy');
      return;
    }
    const id = session;
    busy = true;
    error = null;
    keyHint = false;
    try {
      await work(id);
      reached = true;
    } catch (err) {
      error = errMsg(err);
      keyHint = !reached && onWindows() && errCode(err) === 'ERR_CONNECTION';
    } finally {
      busy = false;
      progress = null;
    }
  }

  async function show(id: number, to: string): Promise<void> {
    const listing = await sftpList(id, to);
    path = listing.path;
    entries = listing.entries;
  }

  function load(to: string): Promise<void> {
    return act((id) => show(id, to));
  }

  // What an upload left as it was: replaced after one question, with the same number.
  async function settle(id: number, dir: string, result: SftpUploaded): Promise<void> {
    if (result.existing.length > 0) {
      const ok = await confirmDialog(
        tNow('terminal.files.confirmOverwrite', { names: result.existing.join(', ') }),
        { confirmLabel: tNow('terminal.files.overwrite') },
      );
      if (ok) await sftpUploadDropped(id, dir, result.drop, true, onProgress);
    }
    await show(id, dir);
  }

  function upload(): Promise<void> {
    return act(async (id) => {
      const dir = path;
      const result = await sftpUpload(id, dir, onProgress);
      if (result) await settle(id, dir, result);
    });
  }

  function uploadDropped(drop: number): Promise<void> {
    return act(async (id) => {
      const dir = path;
      await settle(id, dir, await sftpUploadDropped(id, dir, drop, false, onProgress));
    });
  }

  // A folder is gone into, anything else downloaded: a link as the file it points to.
  function open(entry: SftpEntry): Promise<void> {
    const target = child(path, entry.name);
    if (entry.kind === 'dir') return load(target);
    return act(async (id) => {
      await sftpDownload(id, target, onProgress);
    });
  }

  function startFolder(): void {
    folder = '';
    naming = true;
  }

  function createFolder(e: SubmitEvent): Promise<void> {
    e.preventDefault();
    if (!folderValid) return Promise.resolve();
    const name = folder.trim();
    return act(async (id) => {
      const dir = path;
      await sftpMkdir(id, child(dir, name));
      naming = false;
      await show(id, dir);
    });
  }

  // Read when the session (re)starts: a reconnect brings a new session in Rust.
  $effect(() => {
    const id = session;
    if (!running || id === null) return;
    reached = false;
    untrack(() => void load(path));
  });

  onMount(() => {
    let unlisten: UnlistenFn | null = null;
    let gone = false;
    void listen<SftpDrop>('sftp-drop', (event) => {
      if (shown && ready) void uploadDropped(event.payload.drop);
    }).then((un) => {
      if (gone) un();
      else unlisten = un;
    });
    return () => {
      gone = true;
      unlisten?.();
    };
  });
</script>

<div class="files">
  <div class="files-head">
    <span class="eyebrow">{$t('terminal.files')}</span>
    <div class="files-tools">
      <IconButton
        size="sm"
        icon={Upload}
        label={$t('terminal.files.upload')}
        disabled={!ready || busy}
        onclick={() => void upload()}
      />
      <IconButton
        size="sm"
        icon={FolderPlus}
        label={$t('terminal.files.newFolder')}
        disabled={!ready || busy || naming}
        onclick={startFolder}
      />
      <IconButton
        size="sm"
        icon={RefreshCw}
        label={$t('terminal.files.refresh')}
        disabled={!ready || busy}
        onclick={() => void load(path)}
      />
    </div>
  </div>

  <div class="files-path">
    <Pill title={path}><span class="files-name">{shownName(path)}</span></Pill>
  </div>

  {#if !ready}
    <p class="files-note">{$t('terminal.files.notRunning')}</p>
  {/if}

  {#if naming}
    <form class="files-form" onsubmit={(e) => void createFolder(e)}>
      <FormField label={$t('terminal.files.folderName')}>
        <Input size="sm" bind:value={folder} fullWidth />
      </FormField>
      <div class="files-actions">
        <Button size="sm" variant="ghost" disabled={busy} onclick={() => (naming = false)}>
          {$t('action.cancel')}
        </Button>
        <Button size="sm" type="submit" disabled={!folderValid || busy || !ready}>
          {$t('terminal.files.create')}
        </Button>
      </div>
    </form>
  {/if}

  {#if progress}
    <p class="files-progress" role="status">
      {$t('terminal.files.progress', {
        name: shownName(progress.name),
        done: size(progress.done),
        total: size(progress.total),
      })}
    </p>
  {/if}

  {#if error}
    <p class="files-error" role="alert">{error}</p>
    {#if keyHint}
      <p class="files-note">{$t('terminal.files.windowsKey')}</p>
    {/if}
  {/if}

  <ul class="files-list" aria-label={$t('terminal.files.list')}>
    {#each entries as entry (entry.name)}
      <li>
        <button
          type="button"
          class="file"
          disabled={!ready || busy}
          title={entry.kind === 'dir'
            ? $t('terminal.files.open', { name: shownName(entry.name) })
            : $t('terminal.files.download', { name: shownName(entry.name) })}
          onclick={() => void open(entry)}
        >
          {#if entry.name === '..'}
            <CornerLeftUp size={14} />
          {:else if entry.kind === 'dir'}
            <Folder size={14} />
          {:else if entry.kind === 'link'}
            <FileSymlink size={14} />
          {:else}
            <File size={14} />
          {/if}
          <span class="files-name">{shownName(entry.name)}</span>
          {#if entry.kind === 'file'}
            <span class="file-size">{size(entry.size)}</span>
          {/if}
        </button>
      </li>
    {/each}
  </ul>

  <div class="files-drop">{$t('terminal.files.dropHint')}</div>
</div>

<style>
  .files {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .files-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .files-tools {
    display: flex;
    gap: 2px;
  }
  .files-path {
    min-width: 0;
    overflow: hidden;
    font-family: var(--font-mono);
  }
  .files-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    unicode-bidi: isolate;
  }
  .files-note,
  .files-progress,
  .files-error {
    margin: 0;
    font-size: 12px;
    color: var(--text-muted);
    overflow-wrap: anywhere;
  }
  .files-error {
    color: var(--danger);
  }
  .files-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg);
  }
  .files-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .files-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .file {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 6px;
    border: 0;
    border-radius: var(--radius-sm);
    background: none;
    color: var(--text-strong);
    font: inherit;
    font-size: 12.5px;
    text-align: left;
    cursor: pointer;
  }
  .file:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .file:not(:disabled):hover {
    background: var(--bg-subtle);
  }
  .file-size {
    margin-left: auto;
    flex: 0 0 auto;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
  }
  .files-drop {
    padding: 14px 10px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-md);
    font-size: 12px;
    color: var(--text-muted);
    text-align: center;
  }
</style>
