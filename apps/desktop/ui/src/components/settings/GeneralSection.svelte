<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t, type Language } from '$lib/i18n';
  import { theme, type Theme } from '$lib/stores/theme';
  import type { SyncMode } from '$lib/bridge/types';
  import ScopePill from './ScopePill.svelte';

  interface Props {
    mode: SyncMode;
    language: Language;
    storePasswords: boolean;
    allowSelfSignedCerts: boolean;
  }

  let {
    mode,
    language = $bindable(),
    storePasswords = $bindable(),
    allowSelfSignedCerts = $bindable(),
  }: Props = $props();
</script>

<div class="sm-section" data-scope="device">
  <div class="sm-section-title">{$t('settings.section.language')}</div>
  <label class="field">
    <select bind:value={language}>
      <option value="de">Deutsch</option>
      <option value="en">English</option>
    </select>
  </label>
</div>

<!-- The theme is no setting of the workspace (stores/theme.ts): it applies at once, as the
     toggle in the sidebar does, and Cancel does not take it back. -->
<div class="sm-section" data-scope="device">
  <div class="sm-section-title">{$t('settings.section.theme')}</div>
  <label class="field">
    <select
      data-action="settings-theme"
      aria-label={$t('settings.section.theme')}
      value={$theme}
      onchange={(e) => theme.set(e.currentTarget.value as Theme)}
    >
      <option value="dark">{$t('settings.theme.dark')}</option>
      <option value="light">{$t('settings.theme.light')}</option>
    </select>
  </label>
</div>

<div class="sm-section" data-scope="device">
  <div class="sm-section-title">{$t('settings.section.passwords')}</div>
  <label class="field checkbox">
    <input type="checkbox" bind:checked={storePasswords} />
    <span>{$t('settings.storePasswords')}</span>
  </label>
</div>

{#if mode === 'sync' || mode === 'server'}
  <!-- TLS trust applies to BOTH remote modes: server-mode login/enrollment
     reads this setting too, so it must not hide in the sync branch (the
     bootstrap against the standard own-PKI install depends on it). -->
  <div class="sm-section" data-scope="workspace">
    <div class="sm-section-title">{$t('settings.section.trust')} <ScopePill /></div>
    <label class="field checkbox">
      <input type="checkbox" bind:checked={allowSelfSignedCerts} />
      <span>{$t('settings.allowSelfSigned')}</span>
    </label>
  </div>
{/if}
