<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Page for the '*' catch-all route; the router passes no props. Every route is admin-only and
  // the routeGuard falls a non-admin back to this route, so a non-admin always lands here.
  import { isAdmin } from '$lib/stores/auth';
  import { t } from '$lib/i18n';
</script>

<div class="page active">
  {#if $isAdmin}
    <div class="page-header">
      <div>
        <div class="page-title">Nicht verfuegbar</div>
        <div class="page-subtitle">Wird in einer spaeteren Phase migriert.</div>
      </div>
    </div>
    <div class="panel" style="padding:24px">
      <p>Diese Seite ist noch nicht auf Svelte portiert.</p>
    </div>
  {:else}
    <div class="page-header">
      <div>
        <div class="page-title">{$t('page.adminOnly.title')}</div>
      </div>
    </div>
    <div class="panel" style="padding:24px">
      <p>{$t('page.adminOnly.text')}</p>
    </div>
  {/if}
</div>
