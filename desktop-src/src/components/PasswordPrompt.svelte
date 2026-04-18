<script lang="ts">
  import { passwordPromptState, resolvePrompt } from '$lib/stores/passwordPrompt';

  let username = $state('');
  let domain = $state('');
  let password = $state('');
  let remember = $state(false);
  let passwordInput: HTMLInputElement | null = $state(null);

  $effect(() => {
    const st = $passwordPromptState;
    if (!st.open) return;
    username = st.connection?.username ?? '';
    domain = st.connection?.domain ?? '';
    password = '';
    remember = false;
    queueMicrotask(() => passwordInput?.focus());
  });

  function onCancel(): void {
    resolvePrompt({ cancelled: true });
  }

  function onConfirm(): void {
    const st = $passwordPromptState;
    if (!st.connection) return;
    if (!username || !password) return;
    const updated = {
      ...st.connection,
      username: username.trim(),
      domain: domain.trim() || null,
    };
    resolvePrompt({
      cancelled: false,
      updated,
      password,
      remember: st.allowRemember && remember,
    });
  }

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      onConfirm();
    } else if (e.key === 'Escape') {
      onCancel();
    }
  }
</script>

{#if $passwordPromptState.open}
  <div
    class="pw-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) onCancel();
    }}
    onkeydown={onKeydown}
    tabindex="-1"
  >
    <div class="pw-panel">
      <div class="panel-header">
        <h2 class="panel-title">RDP-Anmeldung</h2>
      </div>
      <p class="pw-hint">
        {$passwordPromptState.allowRemember
          ? 'Bitte Benutzername und Passwort eingeben. Optional im System-Keyring speichern.'
          : 'Bitte Benutzername und Passwort eingeben.'}
      </p>

      <label class="field">
        <span class="field-label">Benutzername</span>
        <input type="text" bind:value={username} required />
      </label>

      <label class="field">
        <span class="field-label">Domain (optional)</span>
        <input type="text" bind:value={domain} />
      </label>

      <label class="field">
        <span class="field-label">Passwort</span>
        <input type="password" bind:value={password} bind:this={passwordInput} required />
      </label>

      {#if $passwordPromptState.allowRemember}
        <label class="field checkbox">
          <input type="checkbox" bind:checked={remember} />
          <span>Im System-Keyring speichern</span>
        </label>
      {/if}

      <div class="panel-actions">
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onCancel}>Abbrechen</button>
        <button class="btn primary" onclick={onConfirm}>Verbinden</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .pw-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 60;
    padding: var(--sp-4);
  }
  .pw-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 420px;
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .panel-header { margin-bottom: var(--sp-1); }
  .panel-title { margin: 0; font-size: 16px; font-weight: 600; }
  .pw-hint { color: var(--text-muted); margin: 0 0 var(--sp-2); font-size: 13px; }
  .field { display: flex; flex-direction: column; gap: var(--sp-2); }
  .field.checkbox { flex-direction: row; align-items: center; }
  .field-label { font-size: 12px; color: var(--text-muted); }
  .field input {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus { outline: 1px solid var(--accent); }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
