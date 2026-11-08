<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  The connect button of a connection (R-1069). For SSH and RDP a split button: the main part opens
  where the settings choose, the arrow a menu that picks for this start only: in AdminHelper or
  in the program of the system (R-1098). Web keeps the single button.
-->
<script lang="ts">
  import { ArrowUpRight, ChevronDown, ExternalLink, PanelTop } from '@lucide/svelte';
  import type { Connection, SshConsole } from '$lib/bridge/types';
  import { t } from '$lib/i18n';
  import Button from '../ui/Button.svelte';
  import Menu, { type MenuItem } from '../ui/Menu.svelte';

  interface Props {
    conn: Connection;
    /** Without a client the start takes the one of the settings. */
    onConnect: (c: Connection, client?: SshConsole) => void;
  }

  let { conn, onConnect }: Props = $props();

  let items = $derived<MenuItem[]>([
    {
      label: $t(
        conn.kind === 'rdp' ? 'connections.connect.rdpEmbedded' : 'connections.connect.embedded',
      ),
      icon: PanelTop,
      onClick: () => onConnect(conn, 'embedded'),
    },
    {
      label: $t(
        conn.kind === 'rdp' ? 'connections.connect.rdpExternal' : 'connections.connect.external',
      ),
      icon: ExternalLink,
      onClick: () => onConnect(conn, 'external'),
    },
  ]);
</script>

{#if conn.kind === 'ssh' || conn.kind === 'rdp'}
  <div class="split">
    <Button variant="primary" class="split-main" onclick={() => onConnect(conn)}
      >{$t('action.connect')}</Button
    >
    <Menu {items} align="end" width={230}>
      {#snippet trigger(p)}
        <Button
          {...p}
          variant="primary"
          class="split-more"
          iconLeft={ChevronDown}
          aria-label={$t(
            conn.kind === 'rdp' ? 'connections.connect.rdpChoose' : 'connections.connect.choose',
          )}
        />
      {/snippet}
    </Menu>
  </div>
{:else}
  <Button
    variant="primary"
    fullWidth
    iconRight={conn.kind === 'web' ? ArrowUpRight : undefined}
    onclick={() => onConnect(conn)}
    >{$t(conn.kind === 'web' ? 'connections.open' : 'action.connect')}</Button
  >
{/if}

<style>
  .split {
    display: flex;
    width: 100%;
  }
  .split :global(.split-main) {
    flex: 1;
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
  }
  .split :global(.split-more) {
    padding: 0 10px 0 8px;
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-left: 1px solid color-mix(in srgb, var(--fill-solid-text) 25%, transparent);
  }
</style>
