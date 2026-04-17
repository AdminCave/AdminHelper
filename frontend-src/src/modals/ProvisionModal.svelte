<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t, language } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';
  import * as api from '$lib/api/frp';
  import type { FrpProvisionToken, Server } from '$lib/api/types';

  interface Props {
    open: boolean;
    server: Server | null;
    onClose: () => void;
  }

  let { open, server, onClose }: Props = $props();

  let tokens = $state<FrpProvisionToken[]>([]);
  let command = $state<string>('');
  let loading = $state(false);

  const locale = $derived($language === 'de' ? 'de-DE' : 'en-GB');

  $effect(() => {
    if (open && server) {
      command = '';
      void loadTokens();
    } else {
      tokens = [];
    }
  });

  async function loadTokens() {
    if (!server) return;
    loading = true;
    try {
      tokens = await api.listProvisionTokens(server.id);
    } catch {
      showToast($t('frp.provision.loadError'), 'error');
    } finally {
      loading = false;
    }
  }

  async function createToken() {
    if (!server) return;
    try {
      const result = await api.createProvisionToken(server.id);
      const srmUrl = window.location.origin;
      let cmd = `# FRP-Client einrichten\nsudo adminhelper-agent frpc init \\\n  --url ${srmUrl} \\\n  --token ${result.token} \\\n  --server-id ${server.id} \\\n  --insecure`;
      try {
        const agentKey = await api.createMonitoringAgentKey(server.id);
        cmd += `\n\n# Monitoring-Agent einrichten\nsudo adminhelper-agent monitor init \\\n  --url ${srmUrl}/api/monitoring \\\n  --api-key ${agentKey.apiKey} \\\n  --server-id ${server.id} \\\n  --insecure`;
      } catch {
        /* Monitoring-Agent-Key nicht verfuegbar — nur FRP anzeigen */
      }
      command = cmd;
      showToast($t('toast.provision.created'));
      await loadTokens();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function copyCommand() {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      showToast($t('toast.provision.commandCopied'));
    } catch {
      showToast('Fehler', 'error');
    }
  }

  function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString(locale);
    } catch {
      return '';
    }
  }

  function tokenStatus(tk: FrpProvisionToken): { label: string; color: string } {
    if (tk.usedAt) {
      return {
        label: $t('frp.provision.used', { time: formatDateTime(tk.usedAt) }),
        color: '#22c55e',
      };
    }
    if (tk.isValid) return { label: $t('frp.provision.active'), color: 'var(--accent)' };
    return { label: $t('frp.provision.expired'), color: '#ef4444' };
  }
</script>

<Modal
  {open}
  title={$t('frp.provision.title', { name: server?.name ?? '' })}
  width="820px"
  {onClose}
>
  <div style="display:flex;flex-direction:column;gap:16px">
    <div>
      <Button variant="primary" onclick={createToken}>
        {$t('frp.provision.createToken')}
      </Button>
    </div>
    {#if command}
      <div style="background:var(--bg-elevated);padding:12px;border-radius:var(--radius-sm)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <strong>{$t('frp.provision.oneLiner')}</strong>
          <button class="btn small" onclick={copyCommand}>{$t('action.copy')}</button>
        </div>
        <pre
          style="margin:0;font-size:12px;white-space:pre-wrap;overflow-x:auto">{command}</pre>
      </div>
    {/if}
    <div>
      <h4 style="margin:0 0 8px">{$t('frp.provision.existingTokens')}</h4>
      {#if loading}
        <p style="color:var(--text-muted)">{$t('state.loading')}</p>
      {:else if tokens.length === 0}
        <p style="color:var(--text-muted)">{$t('frp.provision.noTokens')}</p>
      {:else}
        <table class="data-table" style="margin:0;font-size:13px">
          <thead>
            <tr>
              <th>{$t('label.created')}</th>
              <th>{$t('frp.pki.expiry')}</th>
              <th>{$t('label.status')}</th>
            </tr>
          </thead>
          <tbody>
            {#each tokens as tk (tk.id)}
              {@const st = tokenStatus(tk)}
              <tr>
                <td>{formatDateTime(tk.createdAt)}</td>
                <td>{formatDateTime(tk.expiresAt)}</td>
                <td><span style="color:{st.color}">{st.label}</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  </div>
  {#snippet footer()}
    <Button variant="primary" onclick={onClose}>{$t('action.close')}</Button>
  {/snippet}
</Modal>
