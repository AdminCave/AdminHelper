// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form controls of the design system: bind: writes back, FormField wires label, hint
// and error to the control, and disabled reaches the native element. Keyboard handling
// is the platform's (native input, select, radio, range, button); jsdom does not
// emulate it, so the tests pin the native elements that provide it.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import Checkbox from './Checkbox.svelte';
import Input from './Input.svelte';
import RadioGroup from './RadioGroup.svelte';
import SearchField from './SearchField.svelte';
import Select from './Select.svelte';
import Slider from './Slider.svelte';
import Switch from './Switch.svelte';
import FormsHarness from './__fixtures__/FormsHarness.svelte';

setLanguage('de');
afterEach(() => cleanup());

function state(getByTestId: (id: string) => HTMLElement) {
  return JSON.parse(getByTestId('state').textContent!);
}

describe('FormField + Input', () => {
  it('links label, hint and required mark to the control', () => {
    const { getByLabelText, getByText } = render(FormsHarness);
    const input = getByLabelText(/Name/) as HTMLInputElement;
    expect(input.tagName).toBe('INPUT');
    expect(input.value).toBe('a');
    const hint = getByText('Pflichtfeld');
    expect(input.getAttribute('aria-describedby')).toBe(hint.id);
    expect(input.hasAttribute('aria-invalid')).toBe(false);
    expect(getByText('*').getAttribute('aria-hidden')).toBe('true');
  });

  it('typing writes back; an error replaces the hint and marks the control invalid', async () => {
    const { getByLabelText, getByTestId, getByText, queryByText } = render(FormsHarness);
    const input = getByLabelText(/Name/) as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'host-1' } });
    expect(state(getByTestId).text).toBe('host-1');
    await fireEvent.input(input, { target: { value: '' } });
    const err = getByText('leer');
    expect(queryByText('Pflichtfeld')).toBeNull();
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('aria-describedby')).toBe(err.id);
  });

  it('a bare input has no description and multiline renders a textarea', () => {
    const { container } = render(Input, { value: 'x', multiline: true, rows: 3 });
    const ta = container.querySelector('textarea')!;
    expect(ta.rows).toBe(3);
    expect(ta.value).toBe('x');
    expect(ta.hasAttribute('aria-describedby')).toBe(false);
    expect(container.querySelector('.input')!.className).toContain('multiline');
  });

  it('disabled reaches the native input', () => {
    const { container } = render(Input, { disabled: true, size: 'lg' });
    expect(container.querySelector('input')!.disabled).toBe(true);
    expect(container.querySelector('.input')!.className).toContain('input-lg');
  });
});

describe('SearchField', () => {
  it('shows the shortcut while empty and a clear button once typed', async () => {
    const { getByRole, getByTestId, queryByRole, container } = render(FormsHarness);
    const search = getByRole('searchbox', { name: 'Suche' }) as HTMLInputElement;
    expect(container.querySelector('.search kbd')!.textContent).toBe('⌘K');
    expect(queryByRole('button', { name: 'Leeren' })).toBeNull();

    await fireEvent.input(search, { target: { value: 'db' } });
    expect(state(getByTestId).q).toBe('db');
    expect(container.querySelector('.search kbd')).toBeNull();

    await fireEvent.click(getByRole('button', { name: 'Leeren' }));
    expect(state(getByTestId).q).toBe('');
    expect(search.value).toBe('');
    expect(document.activeElement).toBe(search);
  });

  it('calls onClear', async () => {
    let cleared = 0;
    const { getByRole } = render(SearchField, {
      value: 'x',
      onClear: () => cleared++,
    });
    await fireEvent.click(getByRole('button', { name: 'Leeren' }));
    expect(cleared).toBe(1);
  });
});

describe('Select', () => {
  it('is a native select under its label, with a placeholder while empty', async () => {
    const { getByLabelText, getByTestId } = render(FormsHarness);
    const select = getByLabelText('Farbe') as HTMLSelectElement;
    expect(select.tagName).toBe('SELECT');
    expect([...select.options].map((o) => o.textContent)).toEqual(['Auswählen …', 'rot', 'blau']);
    await fireEvent.change(select, { target: { value: 'b' } });
    expect(state(getByTestId).sel).toBe('b');
  });

  it('reports changes and honours disabled', async () => {
    let got = '';
    const { container } = render(Select, {
      value: 'a',
      options: ['a', 'b'],
      onChange: (v: string) => (got = v),
    });
    const select = container.querySelector('select')!;
    await fireEvent.change(select, { target: { value: 'b' } });
    expect(got).toBe('b');
    const d = render(Select, { options: ['a'], disabled: true });
    expect(d.container.querySelector('select')!.disabled).toBe(true);
  });
});

describe('Switch and Checkbox', () => {
  it('the switch is a native button with role switch and toggles aria-checked', async () => {
    const { getByRole, getByTestId } = render(FormsHarness);
    const sw = getByRole('switch', { name: 'Aktiv' });
    expect(sw.tagName).toBe('BUTTON');
    expect(sw.getAttribute('aria-checked')).toBe('false');
    await fireEvent.click(sw);
    expect(sw.getAttribute('aria-checked')).toBe('true');
    expect(state(getByTestId).on).toBe(true);
  });

  it('a disabled switch is disabled natively', () => {
    const { getByRole } = render(Switch, { disabled: true, size: 'sm' });
    const sw = getByRole('switch') as HTMLButtonElement;
    expect(sw.disabled).toBe(true);
    expect(sw.className).toContain('switch-sm');
  });

  it('the checkbox is native, labelled and writes back', async () => {
    const { getByRole, getByTestId, getByText } = render(FormsHarness);
    const box = getByRole('checkbox', { name: /Zustimmen/ }) as HTMLInputElement;
    expect(getByText('Pflicht')).toBeTruthy();
    await fireEvent.click(box);
    expect(box.checked).toBe(true);
    expect(state(getByTestId).ok).toBe(true);
  });

  it('a disabled checkbox reports nothing', () => {
    const { getByRole } = render(Checkbox, { label: 'x', disabled: true });
    expect((getByRole('checkbox') as HTMLInputElement).disabled).toBe(true);
  });
});

describe('RadioGroup', () => {
  it('is named by its FormField and shares one name across native radios', async () => {
    const { getByRole, getByTestId } = render(FormsHarness);
    const group = getByRole('radiogroup', { name: 'Modus' });
    const radios = [...group.querySelectorAll('input')];
    expect(radios.map((r) => r.type)).toEqual(['radio', 'radio']);
    // One name makes the radios one group, which is what gives the arrow keys.
    expect(new Set(radios.map((r) => r.name)).size).toBe(1);
    expect(radios[0].checked).toBe(true);
    await fireEvent.click(getByRole('radio', { name: /y/ }));
    expect(state(getByTestId).mode).toBe('y');
    expect(radios[1].checked).toBe(true);
  });

  it('two groups on one page get different names', () => {
    const a = render(RadioGroup, { options: ['1'] });
    const b = render(RadioGroup, { options: ['1'] });
    expect(a.container.querySelector('input')!.name).not.toBe(
      b.container.querySelector('input')!.name,
    );
  });

  it('disabled reaches every radio', () => {
    const { container } = render(RadioGroup, { options: ['1', '2'], disabled: true });
    expect([...container.querySelectorAll('input')].every((r) => r.disabled)).toBe(true);
  });
});

describe('Slider', () => {
  it('is a labelled native range that writes back and shows value and suffix', async () => {
    const { getByLabelText, getByTestId, getByText } = render(FormsHarness);
    const range = getByLabelText('Wert') as HTMLInputElement;
    expect(range.type).toBe('range');
    expect(getByText('10%')).toBeTruthy();
    await fireEvent.input(range, { target: { value: '42' } });
    expect(state(getByTestId).num).toBe(42);
    expect(getByText('42%')).toBeTruthy();
    expect(range.getAttribute('aria-valuetext')).toBe('42%');
  });

  it('honours min, max, step and disabled', () => {
    const { container } = render(Slider, { min: 5, max: 9, step: 2, value: 7, disabled: true });
    const r = container.querySelector('input')!;
    expect([r.min, r.max, r.step, r.value]).toEqual(['5', '9', '2', '7']);
    expect(r.disabled).toBe(true);
  });
});
