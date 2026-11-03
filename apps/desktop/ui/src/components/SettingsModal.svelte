<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { settingsModalOpen } from '$lib/stores/settings';
  import SettingsDialog from './settings/SettingsDialog.svelte';
</script>

<!-- The app keeps this mounted (AppShell.svelte); the dialog mounts on each opening and takes
     the stored settings into its form once, so a store change cannot reset what is being typed
     (R-0715). -->
{#if $settingsModalOpen}
  <SettingsDialog />
{/if}
