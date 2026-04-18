<script lang="ts">
  import { session, settings, logout } from '$lib/stores/session';
</script>

<div class="app-shell">
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="sidebar-logo">
        <img src="/logo.svg" alt="AdminHelper" width="36" height="36" />
      </div>
      <div class="sidebar-brand-text">
        <div class="sidebar-title">Admin</div>
        <div class="sidebar-subtitle">Helper</div>
      </div>
    </div>

    <nav class="sidebar-nav">
      <button class="sidebar-item active">
        <span class="sidebar-label">Dashboard</span>
      </button>
      <button class="sidebar-item">
        <span class="sidebar-label">Verbindungen</span>
      </button>
      <button class="sidebar-item">
        <span class="sidebar-label">Monitoring</span>
      </button>
      <button class="sidebar-item">
        <span class="sidebar-label">Ansible</span>
      </button>
    </nav>

    <div class="sidebar-spacer"></div>

    <div class="sidebar-bottom">
      <div class="sidebar-version">v0.18.0-dev</div>
    </div>
  </aside>

  <header class="content-header">
    <div class="content-header-left">
      <h1 class="page-title">Dashboard</h1>
    </div>
    <div class="content-header-right">
      {#if $session}
        <span style="color: var(--text-muted); margin-right: var(--sp-3);">
          {$session.username}
        </span>
        <button class="btn ghost small" onclick={() => logout()}>Abmelden</button>
      {:else if $settings}
        <span style="color: var(--text-muted);">Modus: {$settings.mode}</span>
      {/if}
    </div>
  </header>

  <main class="content-main">
    <section class="content-section">
      <div style="padding: var(--sp-6); color: var(--text-muted);">
        <h2 style="margin-top: 0;">Phase 5 erreicht</h2>
        <p>Auth-Flow und Session-Store sind aktiv.</p>
        <p>Dashboard-Cards, Connection-Liste, Monitoring etc. folgen in Phase 6+.</p>
      </div>
    </section>
  </main>
</div>
