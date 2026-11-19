<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Coverage (Konzept §8.4): profiles bind check types to tags; what discovery finds on a server
  // is taken silently by a profile set to "automatisch", else it waits here for a decision. Per
  // server: what is watched, not collected and hidden, and the open findings.
  import Badge from '../../../components/ui/Badge.svelte';
  import Button from '../../../components/ui/Button.svelte';
  import Segmented from '../../../components/ui/Segmented.svelte';
  import type { MonObject } from '../model';
  import { sinceText } from '../grammar';
  import {
    coverageOf,
    findingState,
    type Finding,
    type Policy,
    type Profile,
    type Topology,
  } from '../exceptions';

  interface Props {
    /** The objects as the server delivers them, with exceptions applied. */
    objects: readonly MonObject[];
    findings: readonly Finding[];
    profiles: readonly Profile[];
    topology: Topology;
    now: Date;
    onDecide: (id: string, decision: 'taken' | 'declined') => void;
    onPolicy: (profile: string, policy: Policy) => void;
  }

  let { objects, findings, profiles, topology, now, onDecide, onPolicy }: Props = $props();

  const rows = $derived(coverageOf(objects, findings, profiles, topology));
  const open = $derived(rows.reduce((n, r) => n + r.open.length, 0));
  const taken = $derived(findings.filter((f) => findingState(f, profiles, topology) === 'taken'));
  const declined = $derived(
    findings.filter((f) => findingState(f, profiles, topology) === 'declined'),
  );
</script>

<div class="coverage">
  <section aria-label="Profile">
    <h2>Profile</h2>
    <p class="hint">
      Ein Profil bindet Check-Typen an Tags. „automatisch“ übernimmt neue Funde still, „vorschlagen“
      legt sie hier zur Entscheidung vor.
    </p>
    <div class="cv-wrap">
      <table class="tbl">
        <thead>
          <tr><th>Profil</th><th>Tags</th><th>Check-Typen</th><th>Neue Funde</th></tr>
        </thead>
        <tbody>
          {#each profiles as p (p.name)}
            <tr data-profile={p.name}>
              <td>{p.name}</td>
              <td>{p.tags.join(', ')}</td>
              <td class="mono">{p.checkTypes.join(', ')}</td>
              <td>
                <Segmented
                  size="sm"
                  label="Neue Funde für {p.name}"
                  options={[
                    { value: 'vorschlagen', label: 'vorschlagen' },
                    { value: 'automatisch', label: 'automatisch' },
                  ]}
                  value={p.policy}
                  onChange={(v) => onPolicy(p.name, v as Policy)}
                />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section aria-label="Server">
    <h2>Server <span class="count">{open} {open === 1 ? 'Fund wartet' : 'Funde warten'}</span></h2>
    <div class="cv-wrap">
      <table class="tbl">
        <thead>
          <tr>
            <th>Server</th>
            <th>Tags · Profile</th>
            <th>überwacht</th>
            <th>nicht erhoben</th>
            <th>ausgeblendet</th>
            <th>Neue Funde</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as r (r.server)}
            <tr data-server={r.server}>
              <td>{r.server}</td>
              <td class="muted">
                {r.tags.join(', ') || 'keine Tags'} · {r.profiles.join(', ') || 'kein Profil'}
              </td>
              <td class="num">{r.watched}</td>
              <td class="num">{r.notCollected}</td>
              <td class="num">{r.hidden}</td>
              <td>
                {#each r.open as f (f.id)}
                  <div class="finding" data-finding={f.id}>
                    <span
                      >{f.what}
                      <span class="muted">({f.checkType}, {sinceText(f.foundAt, now)})</span></span
                    >
                    <Button size="sm" variant="secondary" onclick={() => onDecide(f.id, 'taken')}>
                      Übernehmen
                    </Button>
                    <Button size="sm" variant="ghost" onclick={() => onDecide(f.id, 'declined')}>
                      Ablehnen
                    </Button>
                  </div>
                {/each}
                {#each r.auto as f (f.id)}
                  <div class="finding" data-finding={f.id}>
                    <Badge tone="info">automatisch übernommen</Badge>
                    <span>{f.what}</span>
                  </div>
                {/each}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  {#if taken.length || declined.length}
    <section aria-label="Entschieden">
      <h2>Entschieden</h2>
      <ul>
        {#each taken as f (f.id)}<li>übernommen: {f.what} auf {f.server}</li>{/each}
        {#each declined as f (f.id)}<li>abgelehnt: {f.what} auf {f.server}</li>{/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  .coverage {
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
  }
  h2 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-base);
    color: var(--text-strong);
  }
  .count {
    color: var(--text-subtle);
    font-weight: normal;
  }
  .hint {
    margin: 0 0 var(--space-3);
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  th {
    text-align: left;
    color: var(--text-muted);
    font-weight: normal;
    padding: var(--space-2);
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: var(--space-2);
    border-bottom: 1px solid var(--border-faint);
    vertical-align: top;
  }
  .num {
    text-align: right;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .muted {
    color: var(--text-muted);
  }
  .finding {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .finding + .finding {
    margin-top: var(--space-1);
  }
  ul {
    margin: 0;
    padding-left: var(--space-5);
    font-size: var(--text-sm);
  }
  .cv-wrap {
    overflow-x: auto;
  }
</style>
