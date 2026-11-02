<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import { ensureNotificationPermission } from '$lib/osNotify';

  interface Props {
    osNotifications: boolean;
  }

  let { osNotifications = $bindable() }: Props = $props();

  async function onToggle(checked: boolean): Promise<void> {
    osNotifications = checked;
    // Request OS permission on enable (a user gesture); revert if denied.
    if (checked && !(await ensureNotificationPermission())) {
      osNotifications = false;
    }
  }
</script>

<div class="sm-section">
  <div class="sm-section-title">{$t('settings.section.notifications')}</div>
  <label class="field checkbox">
    <input
      type="checkbox"
      checked={osNotifications}
      onchange={(e) => onToggle(e.currentTarget.checked)}
    />
    <span>{$t('settings.osNotifications')}</span>
  </label>
</div>
