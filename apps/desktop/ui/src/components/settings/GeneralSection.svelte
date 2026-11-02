<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t, type Language } from '$lib/i18n';

  interface Props {
    language: Language;
    storePasswords: boolean;
  }

  let { language = $bindable(), storePasswords = $bindable() }: Props = $props();
</script>

<div class="sm-section">
  <div class="sm-section-title">{$t('settings.section.language')}</div>
  <label class="field">
    <select bind:value={language}>
      <option value="de">Deutsch</option>
      <option value="en">English</option>
    </select>
  </label>
</div>

<div class="sm-section">
  <div class="sm-section-title">{$t('settings.section.passwords')}</div>
  <label class="field checkbox">
    <input type="checkbox" bind:checked={storePasswords} />
    <span>{$t('settings.storePasswords')}</span>
  </label>
</div>
