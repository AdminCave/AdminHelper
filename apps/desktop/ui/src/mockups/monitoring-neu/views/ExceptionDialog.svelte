<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // The exception dialog (Konzept §2): from one object to the scope, the effect and the duration,
  // optionally bound to the current value or to a condition over another object of the server
  // (R-1515). The preview counts what the draft covers; a second step repeats it in words before
  // anything is saved.
  import { untrack } from 'svelte';
  import Button from '../../../components/ui/Button.svelte';
  import Checkbox from '../../../components/ui/Checkbox.svelte';
  import FormField from '../../../components/ui/FormField.svelte';
  import Input from '../../../components/ui/Input.svelte';
  import Modal from '../../../components/ui/Modal.svelte';
  import RadioGroup from '../../../components/ui/RadioGroup.svelte';
  import Segmented from '../../../components/ui/Segmented.svelte';
  import Select from '../../../components/ui/Select.svelte';
  import type { Effect, MonObject } from '../model';
  import { EFFECT_LABEL, STATUS_LABEL, formatValue } from '../grammar';
  import {
    affected,
    checkOf,
    checkText,
    checkTypeOf,
    conditionText,
    covers,
    durationText,
    exceptionState,
    scopeText,
    type Duration,
    type Exception,
    type Scope,
    type ScopeKind,
    type Topology,
  } from '../exceptions';

  interface Props {
    /** The object the dialog was opened from; it offers the scopes around it. */
    anchor: MonObject;
    /** The objects as the checks report them, before any exception. */
    objects: readonly MonObject[];
    topology: Topology;
    now: Date;
    existing?: Exception;
    onSave: (e: Exception) => void;
    onRemove?: (id: string) => void;
    onClose: () => void;
  }

  let { anchor, objects, topology, now, existing, onSave, onRemove, onClose }: Props = $props();

  const EFFECTS: { value: Effect; description: string }[] = [
    {
      value: 'skip',
      description:
        'Der Check läuft für diese Objekte nicht; sie stehen grau als „Nicht geprüft“ am Ende.',
    },
    {
      value: 'no-rating',
      description:
        'Der Check läuft und speichert Werte, bewertet aber nicht; grau am Ende der Listen.',
    },
    {
      value: 'no-notify',
      description: 'Bewertet und angezeigt wie sonst, aber niemand wird benachrichtigt.',
    },
    {
      value: 'mute-me',
      description:
        'Nur deine Benachrichtigungen schweigen; alle anderen werden weiter benachrichtigt.',
    },
  ];
  const DAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  const ALL = 'all';

  const type = $derived(checkTypeOf(anchor));
  const check = $derived(checkOf(anchor));
  const serverTags = $derived(topology.tags[anchor.server] ?? []);
  const clusters = $derived(
    Object.keys(topology.clusters).filter((c) => topology.clusters[c].includes(anchor.server)),
  );
  const others = $derived(
    objects.filter((o) => o.server === anchor.server && o.key !== anchor.key),
  );

  // The form starts from the exception being changed, else from the narrowest choice; it is read
  // once, so a later change of the props does not reset what the user typed.
  const form = $state(untrack(start));

  function start() {
    const e = existing;
    const s = e?.scope;
    const d: Duration = e?.duration ?? { kind: 'permanent' };
    const days = Array.from({ length: 8 }, (_, i) => d.kind === 'window' && d.days.includes(i));
    return {
      scope: s?.kind ?? ('object' as ScopeKind),
      rule: s?.rule ?? anchor.rules?.find((r) => r.firing)?.key ?? anchor.rules?.[0]?.key ?? '',
      tag: s?.kind === 'tag' ? s.value : (serverTags[0] ?? ''),
      typeTag: s?.tag ?? ALL,
      effect: e?.effect ?? ('no-rating' as Effect),
      duration: d.kind,
      untilDate: d.kind === 'until' ? d.until.slice(0, 10) : '',
      days,
      from: d.kind === 'window' ? d.from : '22:00',
      to: d.kind === 'window' ? d.to : '02:00',
      tz: d.kind === 'window' ? d.tz : 'Europe/Berlin',
      bind: !!e?.bound,
      metric: e?.bound?.metric ?? anchor.metrics[0]?.key ?? '',
      cond: !!e?.condition,
      condObject: e?.condition?.object ?? others[0]?.key ?? '',
      condField: e?.condition?.field ?? 'status',
      condEquals: e?.condition?.equals ?? '',
      reason: e?.reason ?? '',
    };
  }

  let step = $state<'edit' | 'confirm'>('edit');

  function scopeOf(kind: ScopeKind): Scope {
    switch (kind) {
      case 'object':
        return { kind, value: anchor.key };
      case 'rule':
        return { kind, value: anchor.key, rule: form.rule };
      case 'check':
        return { kind, value: check };
      case 'check-type':
        return { kind, value: type, tag: form.typeTag === ALL ? undefined : form.typeTag };
      case 'server':
        return { kind, value: anchor.server };
      case 'tag':
        return { kind, value: form.tag };
      case 'cluster':
        return { kind, value: clusters[0] ?? '' };
    }
  }

  function count(scope: Scope): number {
    return objects.filter((o) => covers(scope, o, topology)).length;
  }

  function objectsText(n: number): string {
    return `betrifft ${n} ${n === 1 ? 'Objekt' : 'Objekte'}`;
  }

  const scopeOptions = $derived(
    (
      [
        ['object', 'Dieses Objekt', scopeText(scopeOf('object'), objects)],
        anchor.rules?.length && [
          'rule',
          'Eine Regel dieses Objekts',
          'Die übrigen Regeln bewerten weiter',
        ],
        ['check', `Check ${checkText(check, objects)}`, 'Alle Objekte, die dieser Check meldet'],
        [
          'check-type',
          `Alle Checks ${type}`,
          'Auf allen Servern oder nur auf Servern mit einem Tag',
        ],
        ['server', `Server ${anchor.server}`, 'Alles, was dieser Server meldet'],
        serverTags.length && ['tag', 'Ein Tag des Servers', 'Alle Server mit diesem Tag'],
        clusters.length && ['cluster', `Cluster ${clusters[0]}`, 'Alle Server des Clusters'],
      ].filter(Boolean) as [ScopeKind, string, string][]
    ).map(([value, label, text]) => ({
      value,
      label,
      description: `${text} · ${objectsText(count(scopeOf(value)))}`,
    })),
  );

  // Skipping a check cannot spare one rule of an object: the rule scope only rates or reports.
  const effectOptions = $derived(
    EFFECTS.filter((e) => form.scope !== 'rule' || e.value !== 'skip').map((e) => ({
      value: e.value,
      label: EFFECT_LABEL[e.value],
      description: e.description,
    })),
  );

  function onScope(kind: string): void {
    if (kind === 'rule' && form.effect === 'skip') form.effect = 'no-rating';
  }

  const duration = $derived.by((): Duration => {
    if (form.duration === 'until') return { kind: 'until', until: `${form.untilDate}T23:59:00Z` };
    if (form.duration === 'window')
      return {
        kind: 'window',
        days: form.days.flatMap((on, i) => (on ? [i] : [])),
        from: form.from,
        to: form.to,
        tz: form.tz,
      };
    return { kind: 'permanent' };
  });

  const boundMetric = $derived(anchor.metrics.find((m) => m.key === form.metric));
  const condTarget = $derived(others.find((o) => o.key === form.condObject));

  function currentValue(o: MonObject | undefined, field: string): string {
    if (!o) return '';
    if (field === 'status') return o.status;
    const m = o.metrics.find((x) => x.key === field);
    return m ? String(m.value) : '';
  }

  function onCondObject(key: string): void {
    form.condField = 'status';
    form.condEquals = currentValue(
      others.find((o) => o.key === key),
      'status',
    );
  }

  function onCondField(field: string): void {
    form.condEquals = currentValue(condTarget, field);
  }

  const draft: Exception = $derived({
    id: existing?.id ?? '',
    scope: scopeOf(form.scope),
    effect: form.effect,
    duration,
    bound:
      form.scope === 'object' && form.bind && boundMetric
        ? {
            metric: boundMetric.key,
            value: boundMetric.value,
            text: `${boundMetric.label} ${formatValue(boundMetric.value, boundMetric.unit)}`,
          }
        : undefined,
    condition:
      form.cond && condTarget
        ? { object: condTarget.key, field: form.condField, equals: form.condEquals }
        : undefined,
    reason: form.reason.trim() || undefined,
  });

  const coveredKeys = $derived(new Set(affected(draft, objects, topology).map((o) => o.key)));
  const covered = $derived(coveredKeys.size);
  // Changing an exception takes it from the objects it no longer covers; the second step names
  // how many, so narrowing a server-wide one to one object is no silent loss for the others.
  const lost = $derived(
    existing
      ? affected(existing, objects, topology).filter((o) => !coveredKeys.has(o.key)).length
      : 0,
  );
  const draftState = $derived(exceptionState(draft, objects, now));
  const stateText = $derived(
    draftState.state === 'active'
      ? 'gilt sofort'
      : draftState.state === 'resting'
        ? `ruht jetzt: ${draftState.text}`
        : `wäre sofort erloschen: ${draftState.text}`,
  );

  const problem = $derived.by(() => {
    if (form.scope === 'rule' && !form.rule) return 'Welche Regel?';
    if (form.scope === 'tag' && !form.tag) return 'Welches Tag?';
    if (form.duration === 'until' && !form.untilDate) return 'Bis wann?';
    if (form.duration === 'window' && !form.days.some(Boolean)) return 'An welchen Tagen?';
    if (form.duration === 'window' && (!form.from || !form.to)) return 'Von wann bis wann?';
    if (form.cond && (!condTarget || !form.condEquals.trim()))
      return 'Welcher Wert gilt als Bedingung?';
    return '';
  });

  const summary = $derived(
    [
      ['Wirkung', EFFECT_LABEL[draft.effect]],
      ['Geltung', scopeText(draft.scope, objects)],
      ['Dauer', durationText(draft.duration)],
      draft.bound && ['Gebunden an', `${draft.bound.text}; erlischt, sobald sich der Wert ändert`],
      draft.condition && ['Bedingung', conditionText(draft.condition, objects)],
      ['Grund', draft.reason ?? 'keiner angegeben'],
      ['Betrifft', `${objectsText(covered).replace('betrifft ', '')}, ${stateText}`],
      lost > 0 && [
        'Nicht mehr betroffen',
        `${objectsText(lost).replace('betrifft ', '')}; für sie gilt die Ausnahme nicht mehr`,
      ],
    ].filter(Boolean) as [string, string][],
  );

  const STATUSES = Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }));
</script>

<Modal
  open
  title={existing ? 'Ausnahme ändern' : 'Ausnahme anlegen'}
  description="Ausgangspunkt: {scopeText({ kind: 'object', value: anchor.key }, objects)}"
  width="640px"
  {onClose}
>
  {#if step === 'edit'}
    <div class="form">
      <FormField label="Geltung">
        <RadioGroup
          name="scope"
          options={scopeOptions}
          bind:value={form.scope}
          onChange={onScope}
        />
      </FormField>
      {#if form.scope === 'rule'}
        <FormField label="Regel">
          <Select
            bind:value={form.rule}
            options={(anchor.rules ?? []).map((r) => ({ value: r.key, label: r.text }))}
          />
        </FormField>
      {:else if form.scope === 'tag'}
        <FormField label="Tag">
          <Select bind:value={form.tag} options={serverTags} />
        </FormField>
      {:else if form.scope === 'check-type'}
        <FormField label="Nur auf Servern mit Tag">
          <Select
            bind:value={form.typeTag}
            options={[{ value: ALL, label: 'alle Server' }, ...serverTags]}
          />
        </FormField>
      {/if}

      <FormField label="Wirkung">
        <RadioGroup name="effect" options={effectOptions} bind:value={form.effect} />
      </FormField>

      <FormField label="Dauer">
        <Segmented
          options={[
            { value: 'permanent', label: 'dauerhaft' },
            { value: 'until', label: 'bis' },
            { value: 'window', label: 'wiederkehrend' },
          ]}
          value={form.duration}
          label="Dauer"
          onChange={(v) => (form.duration = v as Duration['kind'])}
        />
      </FormField>
      {#if form.duration === 'until'}
        <FormField label="Bis einschließlich">
          <Input type="date" bind:value={form.untilDate} />
        </FormField>
      {:else if form.duration === 'window'}
        <div class="days" role="group" aria-label="Tage">
          {#each DAYS as day, i (day)}
            <Checkbox label={day} bind:checked={form.days[i + 1]} />
          {/each}
        </div>
        <div class="row">
          <FormField label="Von"><Input type="time" bind:value={form.from} /></FormField>
          <FormField label="Bis"><Input type="time" bind:value={form.to} /></FormField>
          <FormField label="Zeitzone">
            <Select bind:value={form.tz} options={['Europe/Berlin', 'UTC']} />
          </FormField>
        </div>
      {/if}

      {#if form.scope === 'object' && anchor.metrics.length}
        <Checkbox
          label="An den aktuellen Wert binden"
          description="Die Ausnahme erlischt, sobald der Wert sich ändert; das Objekt meldet dann wieder."
          bind:checked={form.bind}
        />
        {#if form.bind}
          <FormField label="Wert">
            <Select
              bind:value={form.metric}
              options={anchor.metrics.map((m) => ({
                value: m.key,
                label: `${m.label}: ${formatValue(m.value, m.unit)}`,
              }))}
            />
          </FormField>
        {/if}
      {/if}

      {#if others.length}
        <Checkbox
          label="Nur solange ein anderes Objekt dieses Servers einen Wert meldet"
          description="Etwa: status.php nicht bewerten, solange das Backup läuft."
          bind:checked={form.cond}
        />
        {#if form.cond}
          <div class="row">
            <FormField label="Objekt">
              <Select
                bind:value={form.condObject}
                options={others.map((o) => ({ value: o.key, label: o.name }))}
                onChange={onCondObject}
              />
            </FormField>
            <FormField label="Feld">
              <Select
                bind:value={form.condField}
                options={[
                  { value: 'status', label: 'Zustand' },
                  ...(condTarget?.metrics ?? []).map((m) => ({ value: m.key, label: m.label })),
                ]}
                onChange={onCondField}
              />
            </FormField>
            <FormField label="meldet">
              {#if form.condField === 'status'}
                <Select bind:value={form.condEquals} options={STATUSES} />
              {:else}
                <Input bind:value={form.condEquals} />
              {/if}
            </FormField>
          </div>
        {/if}
      {/if}

      <FormField
        label="Grund"
        hint="Steht bei jedem betroffenen Objekt und in der Liste Ausgeblendet."
      >
        <Input bind:value={form.reason} placeholder="z. B. Tausch beim nächsten Wartungsfenster" />
      </FormField>

      <p class="preview" aria-live="polite">
        <strong>{objectsText(covered)}</strong>, {stateText}
      </p>
      {#if problem}<p class="problem">{problem}</p>{/if}
    </div>
  {:else}
    <dl class="summary">
      {#each summary as [key, value] (key)}
        <dt>{key}</dt>
        <dd>{value}</dd>
      {/each}
    </dl>
  {/if}

  {#snippet footer()}
    {#if step === 'edit'}
      {#if existing && onRemove}
        <Button variant="danger" onclick={() => onRemove?.(existing.id)}>Aufheben</Button>
      {/if}
      <span class="grow"></span>
      <Button variant="ghost" onclick={onClose}>Abbrechen</Button>
      <Button variant="primary" disabled={!!problem} onclick={() => (step = 'confirm')}>
        Weiter
      </Button>
    {:else}
      <Button variant="ghost" onclick={() => (step = 'edit')}>Zurück</Button>
      <Button variant="primary" onclick={() => onSave(draft)}>
        {existing ? 'Speichern' : 'Anlegen'}
      </Button>
    {/if}
  {/snippet}
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .row {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .days {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .preview {
    margin: 0;
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--surface-inset);
  }
  .problem {
    margin: 0;
    color: var(--warning);
    font-size: var(--text-sm);
  }
  .summary {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: var(--space-2) var(--space-4);
    margin: 0;
  }
  dt {
    color: var(--text-muted);
  }
  dd {
    margin: 0;
  }
  .grow {
    flex: 1;
  }
</style>
