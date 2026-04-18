<script lang="ts">
  import { login } from '$lib/stores/session';

  let { onBack }: { onBack?: () => void } = $props();

  let serverUrl = $state('');
  let username = $state('');
  let password = $state('');
  let error = $state('');
  let busy = $state(false);

  async function handleSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    busy = true;
    try {
      await login(serverUrl.trim(), username.trim(), password);
      serverUrl = '';
      username = '';
      password = '';
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }
</script>

<div class="login-screen">
  <div class="login-card">
    <div class="login-logo" aria-label="AdminHelper Logo">
      <img src="/logo.svg" alt="AdminHelper" width="48" height="48" />
    </div>
    <h2>AdminHelper</h2>
    <p class="login-subtitle">Mit Server verbinden</p>
    <form autocomplete="off" onsubmit={handleSubmit}>
      <label class="field">
        <span>Server URL</span>
        <input
          type="url"
          placeholder="https://adminhelper.example.com"
          bind:value={serverUrl}
          required
          disabled={busy}
        />
      </label>
      <label class="field">
        <span>Benutzername</span>
        <input type="text" bind:value={username} required disabled={busy} />
      </label>
      <label class="field">
        <span>Passwort</span>
        <input type="password" bind:value={password} required disabled={busy} />
      </label>

      {#if error}
        <div class="login-error">{error}</div>
      {/if}

      <button type="submit" class="btn accent login-btn" disabled={busy}>
        {busy ? 'Anmelden…' : 'Anmelden'}
      </button>
    </form>
    {#if onBack}
      <button type="button" class="btn ghost login-back" onclick={onBack}>
        Zurueck zu Einstellungen
      </button>
    {/if}
  </div>
</div>
