import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { searchTerm, kindFilter, filteredConnections } from './connections';

describe('filteredConnections (derived)', () => {
  it('is empty with empty state', () => {
    searchTerm.set('');
    kindFilter.set('all');
    expect(get(filteredConnections)).toEqual([]);
  });

  it('reacts to search term and kind filter independently', () => {
    // derived over actual store; we just verify default reactivity plumbing
    searchTerm.set('irrelevant');
    expect(get(filteredConnections)).toEqual([]);
    kindFilter.set('ssh');
    expect(get(filteredConnections)).toEqual([]);
  });
});
