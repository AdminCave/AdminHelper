<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';

  interface Props {
    name: string;
    serverKey: string;
    onOpen: (serverKey: string) => void;
  }

  let { name, serverKey, onOpen }: Props = $props();
</script>

<button
  type="button"
  class="server-link"
  title={$t('monitoring.cross.openServer', { name })}
  onclick={() => onOpen(serverKey)}>{name}</button
>

<style>
  .server-link {
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .server-link:hover {
    text-decoration: underline;
  }
  .server-link:focus-visible {
    outline: var(--ring-width) solid var(--accent);
    outline-offset: 2px;
  }
</style>
