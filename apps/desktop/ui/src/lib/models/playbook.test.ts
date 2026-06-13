// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { Playbook } from '$lib/api/types';
import {
  emptyPlaybookForm,
  playbookToForm,
  parseTags,
  formToInput,
  validatePlaybookForm,
} from './playbook';

describe('emptyPlaybookForm', () => {
  it('starts blank with a null id and no tags', () => {
    const f = emptyPlaybookForm();
    expect(f.id).toBeNull();
    expect(f.name).toBe('');
    expect(f.filename).toBe('');
    expect(f.description).toBe('');
    expect(f.tags).toEqual([]);
    expect(f.content).toBe('');
  });
});

describe('playbookToForm', () => {
  it('maps a playbook plus loaded content into the editable form, coercing nulls', () => {
    const p: Playbook = {
      id: 'pb1',
      name: 'Deploy',
      filename: 'deploy.yml',
      description: null,
      tags: ['prod'],
    };
    expect(playbookToForm(p, '- hosts: all')).toEqual({
      id: 'pb1',
      name: 'Deploy',
      filename: 'deploy.yml',
      description: '',
      tags: ['prod'],
      content: '- hosts: all',
    });
  });
});

describe('parseTags', () => {
  it('splits, trims, drops empties and dedups', () => {
    expect(parseTags(' a, b ,a ,, ')).toEqual(['a', 'b']);
  });
});

describe('formToInput', () => {
  it('trims text fields, dedups tags, preserves content and never emits an id', () => {
    const input = formToInput({
      ...emptyPlaybookForm(),
      name: '  Deploy  ',
      filename: '  deploy.yml  ',
      description: '  rolls out  ',
      tags: [' a ', 'a', 'b'],
      content: '- hosts: all\n',
    });
    expect(input).toEqual({
      name: 'Deploy',
      filename: 'deploy.yml',
      description: 'rolls out',
      tags: ['a', 'b'],
      content: '- hosts: all\n',
    });
    expect('id' in input).toBe(false);
  });
});

describe('validatePlaybookForm', () => {
  it('requires a name', () => {
    const f = { ...emptyPlaybookForm(), filename: 'deploy.yml' };
    expect(validatePlaybookForm(f).ok).toBe(false);
  });

  it('requires a filename', () => {
    const f = { ...emptyPlaybookForm(), name: 'Deploy' };
    expect(validatePlaybookForm(f).ok).toBe(false);
  });

  it('passes with name and filename', () => {
    const f = { ...emptyPlaybookForm(), name: 'Deploy', filename: 'deploy.yml' };
    expect(validatePlaybookForm(f).ok).toBe(true);
  });
});
