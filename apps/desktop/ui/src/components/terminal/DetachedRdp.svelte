<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  An RDP session detached into a window of its own (R-1101): its picture, logged in at the
  session's WebSocket anew, with what this window may do, and the button that docks it back into
  its tab in the main window. The window's title bar names the session.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import * as bridge from '$lib/bridge';
  import { setLanguage, t } from '$lib/i18n';
  import { refreshSettings, settings } from '$lib/stores/session';
  import { adoptRdp, terminals } from '$lib/stores/terminals';
  import { errMsg } from '$lib/utils/errors';
  import RdpSession from './RdpSession.svelte';

  interface Props {
    /** The session in Rust this window shows. */
    sessionId: string;
  }

  let { sessionId }: Props = $props();

  let key = $state<string | null>(null);
  let failure = $state<string | null>(null);
  let session = $derived($terminals.sessions.find((s) => s.key === key) ?? null);

  // The status bar of the main window is not here: a failure shows in this window.
  async function dock(): Promise<void> {
    failure = null;
    try {
      await bridge.rdpDock(sessionId);
    } catch (err) {
      failure = errMsg(err);
    }
  }

  onMount(() => {
    // The window mode and scaling of the settings, and the language.
    void refreshSettings().then(
      () => {
        const loaded = get(settings);
        if (loaded) setLanguage(loaded.language);
      },
      () => {},
    );
    key = adoptRdp(sessionId);
  });
</script>

<div class="detached">
  {#if failure}
    <div class="detached-failure" role="alert">{$t('terminal.dockFailed', { error: failure })}</div>
  {/if}
  {#if session}
    <RdpSession {session} onDock={() => void dock()} />
  {/if}
</div>

<style>
  .detached {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  .detached > :global(.rdp) {
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
