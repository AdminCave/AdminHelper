<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  A session detached into a window of its own (R-1070): only its terminal, with the options of
  the user, and the button that docks it back into the main window. The window's title bar
  names the session.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import * as bridge from '$lib/bridge';
  import { setLanguage, t } from '$lib/i18n';
  import { refreshSettings, settings } from '$lib/stores/session';
  import { adoptTerminal, terminals } from '$lib/stores/terminals';
  import { errMsg } from '$lib/utils/errors';
  import StatusBar from '../StatusBar.svelte';
  import SshTerminal from './SshTerminal.svelte';

  interface Props {
    /** The session in Rust this window shows. */
    id: number;
  }

  let { id }: Props = $props();

  let key = $state<string | null>(null);
  let failure = $state<string | null>(null);
  let session = $derived($terminals.sessions.find((s) => s.key === key) ?? null);

  // Errors of the terminals store go through reportError into the toasts; this window has its own StatusBar for them.
  async function dock(): Promise<void> {
    failure = null;
    try {
      await bridge.terminalDock(id);
    } catch (err) {
      failure = errMsg(err);
    }
  }

  onMount(() => {
    // Without them the terminal shows the default options; that is all they are for here.
    void refreshSettings().then(
      () => {
        const loaded = get(settings);
        if (loaded) setLanguage(loaded.language);
      },
      () => {},
    );
    key = adoptTerminal(id);
  });
</script>

<div class="detached">
  {#if failure}
    <div class="detached-failure" role="alert">{$t('terminal.dockFailed', { error: failure })}</div>
  {/if}
  {#if session}
    <SshTerminal {session} onDock={() => void dock()} />
  {/if}
  <StatusBar />
</div>

<style>
  .detached {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  .detached > :global(.term) {
    flex: 1;
    min-height: 0;
  }
  .detached-failure {
    padding: 6px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    font-size: 12px;
    color: var(--danger);
  }
</style>
