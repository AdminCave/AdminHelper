// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0 T6 (R-1558, R-1515): the exception dialog builds the exception the
// server would keep and asks once more before saving; the list "Ausgeblendet" sorts every
// exception by review and state; the coverage view shows profiles and findings per server; the
// mockup applies every change to the objects again.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, within } from '@testing-library/svelte';
import MockupApp from '../MockupApp.svelte';
import type { MonObject } from '../model';
import type { Exception } from '../exceptions';
import { BASE_OBJECTS } from '../fixtures';
import { AIO, EXCEPTIONS, FINDINGS, PROFILES, STATUS_PHP, TOPOLOGY } from '../fixtures/exceptions';
import { NOW } from '../fixtures/time';
import CoverageView from './CoverageView.svelte';
import ExceptionDialog from './ExceptionDialog.svelte';
import HiddenView from './HiddenView.svelte';
import { applyExceptions, conditionText } from '../exceptions';

afterEach(cleanup);

function base(key: string): MonObject {
  const o = BASE_OBJECTS.find((x) => x.key === key);
  if (!o) throw new Error(`no object ${key}`);
  return o;
}

function dialog(anchor: string, existing?: Exception) {
  const onSave = vi.fn<(e: Exception) => void>();
  const onRemove = vi.fn<(id: string) => void>();
  const onClose = vi.fn();
  // `anchor` is also a mount option of Svelte: the props go under `props`.
  const r = render(ExceptionDialog, {
    props: {
      anchor: base(anchor),
      objects: BASE_OBJECTS,
      topology: TOPOLOGY,
      now: NOW,
      existing,
      onSave,
      onRemove,
      onClose,
    },
  });
  return { ...r, onSave, onRemove, onClose };
}

/** The confirm step as "key: value" lines. */
function summary(): string[] {
  const dl = document.querySelector('dl.summary');
  return [...(dl?.querySelectorAll('dt') ?? [])].map(
    (dt) => `${dt.textContent?.trim()}: ${dt.nextElementSibling?.textContent?.trim()}`,
  );
}

const preview = (c: HTMLElement) =>
  c.querySelector('.preview')?.textContent?.replace(/\s+/g, ' ').trim();

describe('exception dialog', () => {
  it('offers the scopes around the object, each with its count', () => {
    const { getByRole } = dialog('pve-01/disk/wwn-0x5000c500a1b2c303');
    const group = getByRole('radiogroup', { name: 'Geltung' });
    const text = (sel: string) =>
      [...group.querySelectorAll(sel)].map((x) => x.textContent?.trim());
    expect(text('.label')).toEqual([
      'Dieses Objekt',
      'Eine Regel dieses Objekts',
      'Check smart_health auf pve-01',
      'Alle Checks smart_health',
      'Server pve-01',
      'Ein Tag des Servers',
      'Cluster cl-a',
    ]);
    const own = BASE_OBJECTS.filter((o) => o.server === 'pve-01').length;
    expect(text('.desc')[0]).toMatch(/· betrifft 1 Objekt$/);
    expect(text('.desc')[4]).toBe(`Alles, was dieser Server meldet · betrifft ${own} Objekte`);
  });

  it('counts the draft and says whether it holds now', async () => {
    const { container, getByRole } = dialog('pve-01/disk/wwn-0x5000c500a1b2c303');
    expect(preview(container)).toBe('betrifft 1 Objekt, gilt sofort');
    await fireEvent.click(getByRole('radio', { name: /^Server pve-01/ }));
    const own = BASE_OBJECTS.filter((o) => o.server === 'pve-01').length;
    expect(preview(container)).toBe(`betrifft ${own} Objekte, gilt sofort`);
    await fireEvent.click(getByRole('radio', { name: /^Cluster cl-a/ }));
    const cluster = BASE_OBJECTS.filter((o) => ['pve-01', 'pve-02'].includes(o.server)).length;
    expect(preview(container)).toBe(`betrifft ${cluster} Objekte, gilt sofort`);
  });

  it('asks once more, then saves the exception as the server keeps it', async () => {
    const { getByRole, getByLabelText, onSave } = dialog('pve-01/disk/wwn-0x5000c500a1b2c303');
    await fireEvent.click(getByRole('radio', { name: /^nur für mich still/ }));
    await fireEvent.click(getByRole('radio', { name: 'bis' }));
    expect(getByRole('button', { name: 'Weiter' })).toHaveProperty('disabled', true);
    await fireEvent.input(getByLabelText('Bis einschließlich'), {
      target: { value: '2026-11-30' },
    });
    await fireEvent.input(getByLabelText('Grund'), { target: { value: 'Tausch bestellt' } });
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    expect(summary()).toEqual([
      'Wirkung: nur für mich still',
      'Geltung: Platte sda auf pve-01',
      'Dauer: bis 30.11.2026, 23:59',
      'Grund: Tausch bestellt',
      'Betrifft: 1 Objekt, gilt sofort',
    ]);
    expect(onSave).not.toHaveBeenCalled();
    await fireEvent.click(getByRole('button', { name: 'Anlegen' }));
    expect(onSave).toHaveBeenCalledWith({
      id: '',
      scope: { kind: 'object', value: 'pve-01/disk/wwn-0x5000c500a1b2c303' },
      effect: 'mute-me',
      duration: { kind: 'until', until: '2026-11-30T23:59:00Z' },
      bound: undefined,
      condition: undefined,
      reason: 'Tausch bestellt',
    });
  });

  it('binds to the current value of the object', async () => {
    const { getByRole, getByLabelText, onSave } = dialog('pve-01/disk/wwn-0x5000c500a1b2c303');
    await fireEvent.click(getByRole('checkbox', { name: /An den aktuellen Wert binden/ }));
    await fireEvent.change(getByLabelText('Wert'), { target: { value: 'realloc' } });
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    await fireEvent.click(getByRole('button', { name: 'Anlegen' }));
    expect(onSave.mock.calls[0][0].bound).toEqual({
      metric: 'realloc',
      value: 8,
      text: 'Umgelagert 8',
    });
  });

  it('a rule scope cannot skip the check', async () => {
    const { getByRole, queryByRole } = dialog('backup-01/module/restic/restic-backup.service');
    await fireEvent.click(getByRole('radio', { name: /^nicht prüfen/ }));
    await fireEvent.click(getByRole('radio', { name: /^Eine Regel dieses Objekts/ }));
    expect(queryByRole('radio', { name: /^nicht prüfen/ })).toBeNull();
    expect(getByRole('radio', { name: /^prüfen, nicht bewerten/ })).toHaveProperty('checked', true);
  });

  it('R-1515: status.php only while the AIO backup runs', async () => {
    const { container, getByRole, getByLabelText, onSave } = dialog(STATUS_PHP);
    await fireEvent.click(getByRole('checkbox', { name: /Nur solange ein anderes Objekt/ }));
    await fireEvent.change(getByLabelText('Objekt'), { target: { value: AIO } });
    await fireEvent.change(getByLabelText('Feld'), { target: { value: 'backup' } });
    expect((getByLabelText('meldet') as HTMLInputElement).value).toBe('ja');
    expect(preview(container)).toBe('betrifft 1 Objekt, gilt sofort');
    await fireEvent.input(getByLabelText('meldet'), { target: { value: 'nein' } });
    expect(preview(container)).toBe(
      'betrifft 1 Objekt, ruht jetzt: Bedingung nicht erfüllt: Backup läuft ja',
    );
    await fireEvent.input(getByLabelText('meldet'), { target: { value: 'ja' } });
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    expect(summary().find((l) => l.startsWith('Bedingung: '))).toBe(
      `Bedingung: ${conditionText({ object: AIO, field: 'backup', equals: 'ja' }, BASE_OBJECTS)}`,
    );
    await fireEvent.click(getByRole('button', { name: 'Anlegen' }));
    expect(onSave.mock.calls[0][0].condition).toEqual({
      object: AIO,
      field: 'backup',
      equals: 'ja',
    });
  });

  it('a recurring window needs a day', async () => {
    const { getByRole, getByText } = dialog('web-01/container/certbot-renew');
    await fireEvent.click(getByRole('radio', { name: 'wiederkehrend' }));
    expect(getByText('An welchen Tagen?')).toBeTruthy();
    await fireEvent.click(getByRole('checkbox', { name: 'Sa' }));
    expect(getByRole('button', { name: 'Weiter' })).toHaveProperty('disabled', false);
  });

  it('narrowing an exception names the objects it no longer covers', async () => {
    const e9 = EXCEPTIONS.find((e) => e.id === 'e9') as Exception;
    const web02 = BASE_OBJECTS.filter((o) => o.server === 'web-02');
    expect(web02.length).toBeGreaterThan(1);
    const { getByRole } = dialog(web02[0].key, e9);
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    expect(summary().some((l) => l.startsWith('Nicht mehr betroffen'))).toBe(false);
    await fireEvent.click(getByRole('button', { name: 'Zurück' }));
    await fireEvent.click(getByRole('radio', { name: /^Dieses Objekt/ }));
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    expect(summary()).toContain(
      `Nicht mehr betroffen: ${web02.length - 1} Objekte; für sie gilt die Ausnahme nicht mehr`,
    );
  });

  it('changes an existing exception and can lift it', async () => {
    const e14 = EXCEPTIONS.find((e) => e.id === 'e14') as Exception;
    const { getByRole, getByLabelText, onRemove } = dialog(STATUS_PHP, e14);
    expect(getByRole('heading', { name: 'Ausnahme ändern' })).toBeTruthy();
    expect(getByRole('radio', { name: /^Check / })).toHaveProperty('checked', true);
    expect((getByLabelText('Objekt') as HTMLSelectElement).value).toBe(AIO);
    expect((getByLabelText('Feld') as HTMLSelectElement).value).toBe('backup');
    await fireEvent.click(getByRole('button', { name: 'Aufheben' }));
    expect(onRemove).toHaveBeenCalledWith('e14');
  });
});

describe('list Ausgeblendet', () => {
  function ids(c: HTMLElement, section: string): string[] {
    return [...c.querySelectorAll(`[data-section="${section}"] li`)].map(
      (li) => li.getAttribute('data-id') ?? '',
    );
  }

  it('puts review first and sorts the rest by state', () => {
    const { container } = render(HiddenView, {
      exceptions: EXCEPTIONS,
      objects: BASE_OBJECTS,
      topology: TOPOLOGY,
      now: NOW,
      onEdit: vi.fn(),
      onRemove: vi.fn(),
      onReview: vi.fn(),
    });
    expect(ids(container, 'review')).toEqual(['e5', 'e8', 'e11', 'e12']);
    expect(ids(container, 'active')).toEqual(['e1', 'e2', 'e3', 'e4', 'e9', 'e10', 'e13', 'e14']);
    expect(ids(container, 'resting')).toEqual(['e7']);
    expect(ids(container, 'ended')).toEqual(['e6', 'e15']);
  });

  it('names who and when, unknown for migrated ones, and why one is up for review', () => {
    const { container } = render(HiddenView, {
      exceptions: EXCEPTIONS,
      objects: BASE_OBJECTS,
      topology: TOPOLOGY,
      now: NOW,
      onEdit: vi.fn(),
      onRemove: vi.fn(),
      onReview: vi.fn(),
    });
    const text = (id: string) =>
      container.querySelector(`li[data-id="${id}"]`)?.textContent?.replace(/\s+/g, ' ') ?? '';
    expect(text('e5')).toContain('von unbekannt (migriert)');
    expect(text('e5')).toContain(
      'Zur Prüfung: migriert aus ignore_containers, wer und wann unbekannt',
    );
    expect(text('e9')).toContain('von admin, 15.11.2026, 09:00');
    expect(text('e9')).toContain('wiederkehrend Mi 09:30–11:00 (Europe/Berlin)');
    expect(text('e14')).toContain('„Backup läuft: ja“');
    expect(text('e6')).toContain('erloschen: Umgelagert jetzt 8, gebunden an 5');
    expect(text('e7')).toContain('ruht: außerhalb des Fensters');
    expect(text('e12')).toContain('betrifft 0 Objekte');
  });

  it('confirms, changes and lifts', async () => {
    const onEdit = vi.fn();
    const onRemove = vi.fn();
    const onReview = vi.fn();
    const { container } = render(HiddenView, {
      exceptions: EXCEPTIONS,
      objects: BASE_OBJECTS,
      topology: TOPOLOGY,
      now: NOW,
      onEdit,
      onRemove,
      onReview,
    });
    const item = (id: string) =>
      within(container.querySelector(`li[data-id="${id}"]`) as HTMLElement);
    await fireEvent.click(item('e11').getByRole('button', { name: 'Bestätigen' }));
    expect(onReview).toHaveBeenCalledWith('e11');
    await fireEvent.click(item('e1').getByRole('button', { name: 'Ändern …' }));
    expect(onEdit).toHaveBeenCalledWith('e1');
    await fireEvent.click(item('e6').getByRole('button', { name: 'Aufheben' }));
    expect(onRemove).toHaveBeenCalledWith('e6');
    // Nothing to start the dialog from: an exception without objects is confirmed or lifted.
    expect(item('e12').queryByRole('button', { name: 'Ändern …' })).toBeNull();
    expect(item('e1').queryByRole('button', { name: 'Bestätigen' })).toBeNull();
  });
});

describe('coverage', () => {
  const objects = applyExceptions(BASE_OBJECTS, EXCEPTIONS, NOW, TOPOLOGY);

  it('shows per server the counts and the open and automatic findings', async () => {
    const onDecide = vi.fn();
    const { container } = render(CoverageView, {
      objects,
      findings: FINDINGS,
      profiles: PROFILES,
      topology: TOPOLOGY,
      now: NOW,
      onDecide,
      onPolicy: vi.fn(),
    });
    const row = (server: string) =>
      container.querySelector(`tr[data-server="${server}"]`) as HTMLElement;
    const nums = [...row('nas-01').querySelectorAll('td.num')].map((td) => Number(td.textContent));
    const own = objects.filter((o) => o.server === 'nas-01');
    expect(nums.reduce((a, b) => a + b, 0)).toBe(own.length);
    expect(row('nas-01').textContent).toContain('automatisch übernommen');
    expect(row('nas-01').textContent).toContain('Platte sde (WDC WD40EFZX)');
    expect(container.textContent).toContain('2 Funde warten');
    await fireEvent.click(within(row('web-01')).getByRole('button', { name: 'Übernehmen' }));
    expect(onDecide).toHaveBeenCalledWith('f1', 'taken');
    expect(row('dc-02').textContent).not.toContain('W32Time');
    expect(container.querySelector('[aria-label="Entschieden"]')?.textContent).toContain(
      'abgelehnt: Dienst W32Time auf dc-02',
    );
  });

  it('switches the policy of a profile', async () => {
    const onPolicy = vi.fn();
    const { getByRole } = render(CoverageView, {
      objects,
      findings: FINDINGS,
      profiles: PROFILES,
      topology: TOPOLOGY,
      now: NOW,
      onDecide: vi.fn(),
      onPolicy,
    });
    const group = within(getByRole('radiogroup', { name: 'Neue Funde für Docker' }));
    await fireEvent.click(group.getByRole('radio', { name: 'automatisch' }));
    expect(onPolicy).toHaveBeenCalledWith('Docker', 'automatisch');
  });
});

describe('mockup: every change is applied again', () => {
  it('an exception made in the drawer hides the object; lifting it shows it again', async () => {
    const { container, getByRole, queryAllByRole } = render(MockupApp);
    await fireEvent.click(getByRole('tab', { name: 'Objekte' }));
    const key = 'pve-01/disk/wwn-0x5000c500a1b2c303';
    const tr = () => container.querySelector(`main tr[data-key="${key}"]`) as HTMLElement;
    const note = () => container.querySelector('aside.drawer .note')?.textContent ?? '';
    // e6 is bound to 5 reallocated sectors, the disk reports 8: ended, the disk reports again.
    expect(tr().classList.contains('hidden')).toBe(false);
    await fireEvent.click(tr().querySelector('button.open') as HTMLElement);
    expect(note()).toMatch(/^erloschen \(Umgelagert jetzt 8, gebunden an 5\)/);
    const drawer = within(container.querySelector('aside.drawer') as HTMLElement);
    await fireEvent.click(drawer.getByRole('button', { name: 'Ausnahme ändern …' }));
    // Saving an ended bound exception binds it to today's value: the admin accepts 8 now.
    expect(getByRole('checkbox', { name: /An den aktuellen Wert binden/ })).toHaveProperty(
      'checked',
      true,
    );
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    expect(summary()).toContain('Gebunden an: Umgelagert 8; erlischt, sobald sich der Wert ändert');
    await fireEvent.click(getByRole('button', { name: 'Speichern' }));
    expect(queryAllByRole('dialog').length).toBe(0);
    expect(note()).toMatch(
      /^prüfen, nicht bewerten · .* · von admin · dauerhaft · gilt nur bei Umgelagert 8$/,
    );
    expect(tr().classList.contains('hidden')).toBe(true);

    await fireEvent.click(drawer.getByRole('button', { name: 'Ausnahme ändern …' }));
    await fireEvent.click(getByRole('button', { name: 'Aufheben' }));
    expect(queryAllByRole('dialog').length).toBe(0);
    expect(note()).toBe('');
    expect(drawer.getByRole('button', { name: 'Ausnahme anlegen …' })).toBeTruthy();
    expect(tr().classList.contains('hidden')).toBe(false);
  });

  it('a server-wide exception stays; the drawer adds a narrower one for this object alone', async () => {
    const { container, getByRole } = render(MockupApp);
    await fireEvent.click(getByRole('tab', { name: 'Objekte' }));
    const [first, second] = BASE_OBJECTS.filter((o) => o.server === 'web-02' && !o.parent);
    const open = async (key: string) =>
      fireEvent.click(
        container.querySelector(`main tr[data-key="${key}"] button.open`) as HTMLElement,
      );
    const note = () => container.querySelector('aside.drawer .note')?.textContent ?? '';
    await open(first.key);
    expect(note()).toContain('wiederkehrend Mi 09:30–11:00 (Europe/Berlin)');
    const drawer = () => within(container.querySelector('aside.drawer') as HTMLElement);
    await fireEvent.click(drawer().getByRole('button', { name: 'Nur für dieses Objekt …' }));
    expect(getByRole('heading', { name: 'Ausnahme anlegen' })).toBeTruthy();
    expect(getByRole('radio', { name: /^Dieses Objekt/ })).toHaveProperty('checked', true);
    await fireEvent.click(getByRole('button', { name: 'Weiter' }));
    await fireEvent.click(getByRole('button', { name: 'Anlegen' }));
    expect(note()).toMatch(/^prüfen, nicht bewerten · /);
    expect(note()).not.toContain('wiederkehrend');
    expect(drawer().queryByRole('button', { name: 'Nur für dieses Objekt …' })).toBeNull();
    await open(second.key);
    expect(note()).toContain('wiederkehrend Mi 09:30–11:00 (Europe/Berlin)');
  });

  it('confirming in the list moves the exception out of the review', async () => {
    const { container, getByRole } = render(MockupApp);
    await fireEvent.click(getByRole('tab', { name: 'Ausgeblendet' }));
    const e11 = () => container.querySelector('li[data-id="e11"]') as HTMLElement;
    expect(e11().closest('section')?.getAttribute('data-section')).toBe('review');
    await fireEvent.click(within(e11()).getByRole('button', { name: 'Bestätigen' }));
    expect(e11().closest('section')?.getAttribute('data-section')).toBe('active');
  });

  it('taking a finding over removes it from the open ones', async () => {
    const { container, getByRole } = render(MockupApp);
    await fireEvent.click(getByRole('tab', { name: 'Abdeckung' }));
    expect(container.textContent).toContain('2 Funde warten');
    const row = container.querySelector('tr[data-server="web-01"]') as HTMLElement;
    await fireEvent.click(within(row).getByRole('button', { name: 'Übernehmen' }));
    expect(container.textContent).toContain('1 Fund wartet');
    expect(container.textContent).toContain('übernommen: Dienst redis-server.service auf web-01');
  });
});
