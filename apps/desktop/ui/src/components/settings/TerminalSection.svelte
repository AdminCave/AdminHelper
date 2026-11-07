<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import type { SshConsole, TerminalPrefs } from '$lib/bridge/types';
  import TerminalOptions from '../terminal/TerminalOptions.svelte';

  interface Props {
    sshConsole: SshConsole;
    terminal: TerminalPrefs;
    restoreSessions: boolean;
  }

  let {
    sshConsole = $bindable(),
    terminal = $bindable(),
    restoreSessions = $bindable(),
  }: Props = $props();
</script>

<div class="sm-section">
  <div class="sm-section-title">{$t('settings.section.terminal')}</div>
  <label class="field">
    <span class="field-label">{$t('settings.terminal.sshConsole')}</span>
    <select data-field="ssh-console" bind:value={sshConsole}>
      <option value="embedded">{$t('settings.terminal.sshConsole.embedded')}</option>
      <option value="external">{$t('settings.terminal.sshConsole.external')}</option>
    </select>
  </label>
  <label class="field checkbox">
    <input type="checkbox" data-field="restore-sessions" bind:checked={restoreSessions} />
    <span>{$t('settings.terminal.restoreSessions')}</span>
  </label>
</div>
<div class="sm-section">
  <TerminalOptions bind:prefs={terminal} />
</div>
