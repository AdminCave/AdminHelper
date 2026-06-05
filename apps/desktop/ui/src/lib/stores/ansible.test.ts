// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
  ansibleSelectedPlaybookId,
  ansibleSelectedServerIds,
  ansibleTargetMode,
  selectPlaybook,
  setTargetMode,
  toggleServer,
  clearSelection,
} from './ansible';

describe('ansible store', () => {
  beforeEach(() => clearSelection());

  it('selects and clears playbook', () => {
    selectPlaybook('p1');
    expect(get(ansibleSelectedPlaybookId)).toBe('p1');
    selectPlaybook(null);
    expect(get(ansibleSelectedPlaybookId)).toBeNull();
  });

  it('toggles server ids idempotently', () => {
    toggleServer('s1');
    toggleServer('s2');
    expect([...get(ansibleSelectedServerIds)].sort()).toEqual(['s1', 's2']);
    toggleServer('s1');
    expect([...get(ansibleSelectedServerIds)]).toEqual(['s2']);
  });

  it('creates a new Set on toggle so subscribers fire', () => {
    const before = get(ansibleSelectedServerIds);
    toggleServer('s1');
    const after = get(ansibleSelectedServerIds);
    expect(after).not.toBe(before);
  });

  it('switches target mode', () => {
    expect(get(ansibleTargetMode)).toBe('servers');
    setTargetMode('tags');
    expect(get(ansibleTargetMode)).toBe('tags');
  });
});
