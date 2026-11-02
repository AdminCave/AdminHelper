<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import Pill from '../ui/Pill.svelte';
</script>

<!-- Marks what belongs to this workspace among settings that hold for the whole device. -->
<span class="sm-scope"><Pill tone="accent">{$t('settings.group.workspace')}</Pill></span>

<style>
  .sm-scope {
    margin-left: var(--sp-2);
    text-transform: none;
    letter-spacing: normal;
  }
</style>
