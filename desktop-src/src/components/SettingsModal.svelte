<script lang="ts">
  import { settings, session } from '$lib/stores/session';
  import { settingsModalOpen, closeSettings, saveSettings, serverLogout } from '$lib/stores/settings';
  import {
    RDP_WINDOW_MODES,
    RDP_PERFORMANCE_PROFILES,
    RDP_SCALING_MODES,
    getSettingsDefaults,
    getIntervalMinutes,
  } from '$lib/models/settings';
  import type { Settings, SyncMode, RdpWindowMode, RdpPerformanceProfile, RdpScalingMode } from '$lib/bridge/types';

  let mode = $state<SyncMode>('local');
  let url = $state('');
  let intervalMinutes = $state(1);
  let language = $state<'de' | 'en'>('de');
  let storePasswords = $state(false);
  let allowSelfSignedCerts = $state(false);
  let rdpScalingMode = $state<RdpScalingMode>('auto');
  let rdpWindowMode = $state<RdpWindowMode>('fit');
  let rdpCustomSize = $state('1920x1080');
  let rdpPerformanceProfile = $state<RdpPerformanceProfile>('auto');
  let serverUrl = $state('');

  $effect(() => {
    if (!$settingsModalOpen) return;
    const s = $settings ?? getSettingsDefaults();
    mode = s.mode;
    url = s.url ?? '';
    intervalMinutes = getIntervalMinutes(s);
    language = (s.language === 'en' ? 'en' : 'de');
    storePasswords = Boolean(s.storePasswords);
    allowSelfSignedCerts = Boolean(s.allowSelfSignedCerts);
    rdpScalingMode = s.rdpScalingMode ?? 'auto';
    rdpWindowMode = s.rdpWindowMode ?? 'fit';
    rdpCustomSize = s.rdpCustomSize ?? '1920x1080';
    rdpPerformanceProfile = s.rdpPerformanceProfile ?? 'auto';
    serverUrl = s.serverUrl ?? '';
  });

  async function onSave(): Promise<void> {
    const next: Settings = {
      mode,
      url: url.trim(),
      intervalMinutes,
      language,
      storePasswords,
      allowSelfSignedCerts,
      rdpScalingMode,
      rdpWindowMode,
      rdpCustomSize: rdpCustomSize.trim(),
      rdpPerformanceProfile,
      serverUrl: serverUrl.trim(),
    };
    await saveSettings(next);
  }

  async function onLogout(): Promise<void> {
    await serverLogout();
  }

  function rdpScalingLabel(m: RdpScalingMode): string {
    return { auto: 'Automatisch', normal: 'Normal', hdpi: 'HiDPI' }[m];
  }
  function rdpWindowLabel(m: RdpWindowMode): string {
    return { fit: 'Eingepasst', fullscreen: 'Vollbild', multimon: 'Mehrfach-Monitor', custom: 'Benutzerdefiniert' }[m];
  }
  function rdpPerfLabel(m: RdpPerformanceProfile): string {
    return { auto: 'Automatisch', lan: 'LAN', broadband: 'Breitband', low: 'Niedrig' }[m];
  }
</script>

{#if $settingsModalOpen}
  <div
    class="sm-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => { if (e.target === e.currentTarget) closeSettings(); }}
    onkeydown={(e) => { if (e.key === 'Escape') closeSettings(); }}
    tabindex="-1"
  >
    <div class="sm-panel">
      <div class="panel-header">
        <h2 class="panel-title">Einstellungen</h2>
        <button class="btn ghost small" onclick={closeSettings}>Schliessen</button>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">Modus</div>
        <div class="sm-radio-group">
          <label class="sm-radio">
            <input type="radio" name="syncMode" value="local" checked={mode === 'local'} onchange={() => (mode = 'local')} />
            <span>Lokal</span>
          </label>
          <label class="sm-radio">
            <input type="radio" name="syncMode" value="sync" checked={mode === 'sync'} onchange={() => (mode = 'sync')} />
            <span>Sync (JSON)</span>
          </label>
          <label class="sm-radio">
            <input type="radio" name="syncMode" value="server" checked={mode === 'server'} onchange={() => (mode = 'server')} />
            <span>Server</span>
          </label>
        </div>
      </div>

      {#if mode === 'sync'}
        <label class="field">
          <span class="field-label">Sync-URL (HTTPS)</span>
          <input type="url" bind:value={url} placeholder="https://…/connections.json" />
        </label>
        <label class="field">
          <span class="field-label">Intervall (Minuten)</span>
          <input type="number" min="1" max="1440" bind:value={intervalMinutes} />
        </label>
        <label class="field checkbox">
          <input type="checkbox" bind:checked={allowSelfSignedCerts} />
          <span>Selbstsignierte Zertifikate erlauben</span>
        </label>
      {:else if mode === 'server'}
        <label class="field">
          <span class="field-label">Server-URL</span>
          <input type="url" bind:value={serverUrl} placeholder="https://adminhelper.example" />
        </label>
        {#if $session}
          <div class="sm-session-row">
            <span class="field-label">Angemeldet als</span>
            <strong>{$session.username}</strong>
            <button class="btn ghost small" onclick={onLogout}>Abmelden</button>
          </div>
        {/if}
      {/if}

      <div class="sm-section">
        <div class="sm-section-title">Sprache</div>
        <label class="field">
          <select bind:value={language}>
            <option value="de">Deutsch</option>
            <option value="en">English</option>
          </select>
        </label>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">Passwoerter</div>
        <label class="field checkbox">
          <input type="checkbox" bind:checked={storePasswords} />
          <span>Passwoerter im System-Keyring speichern</span>
        </label>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">RDP</div>
        <label class="field">
          <span class="field-label">Skalierung</span>
          <select bind:value={rdpScalingMode}>
            {#each RDP_SCALING_MODES as m (m)}
              <option value={m}>{rdpScalingLabel(m)}</option>
            {/each}
          </select>
        </label>
        <label class="field">
          <span class="field-label">Fenstermodus</span>
          <select bind:value={rdpWindowMode}>
            {#each RDP_WINDOW_MODES as m (m)}
              <option value={m}>{rdpWindowLabel(m)}</option>
            {/each}
          </select>
        </label>
        {#if rdpWindowMode === 'custom'}
          <label class="field">
            <span class="field-label">Benutzerdefinierte Groesse (z. B. 1920x1080)</span>
            <input type="text" bind:value={rdpCustomSize} placeholder="1920x1080" />
          </label>
        {/if}
        <label class="field">
          <span class="field-label">Leistungsprofil</span>
          <select bind:value={rdpPerformanceProfile}>
            {#each RDP_PERFORMANCE_PROFILES as m (m)}
              <option value={m}>{rdpPerfLabel(m)}</option>
            {/each}
          </select>
        </label>
      </div>

      <div class="panel-actions">
        <div style="flex: 1;"></div>
        <button class="btn" onclick={closeSettings}>Abbrechen</button>
        <button class="btn primary" onclick={onSave}>Speichern</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .sm-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 60;
    padding: var(--sp-4);
  }
  .sm-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 560px;
    max-height: 90vh;
    overflow-y: auto;
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--sp-2);
  }
  .panel-title { margin: 0; font-size: 16px; font-weight: 600; }
  .sm-section { display: flex; flex-direction: column; gap: var(--sp-2); margin-top: var(--sp-2); }
  .sm-section-title {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .sm-radio-group { display: flex; gap: var(--sp-4); flex-wrap: wrap; }
  .sm-radio { display: flex; align-items: center; gap: var(--sp-2); cursor: pointer; }
  .field { display: flex; flex-direction: column; gap: var(--sp-2); }
  .field.checkbox { flex-direction: row; align-items: center; }
  .field-label { font-size: 12px; color: var(--text-muted); }
  .field input, .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus, .field select:focus { outline: 1px solid var(--accent); }
  .sm-session-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) 0;
  }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding-top: var(--sp-3);
    margin-top: var(--sp-2);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
