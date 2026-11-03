<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts" module>
  // Up to two letters: the first of the first and of the last word, else the first two of a
  // single name ("kevin" → "KE"), so a login name without a space still reads as two letters.
  export function initials(name: string): string {
    const words = name
      .trim()
      .split(/[\s._@-]+/u)
      .filter(Boolean);
    if (words.length === 0) return '?';
    if (words.length === 1) return Array.from(words[0]).slice(0, 2).join('').toUpperCase();
    const first = Array.from(words[0])[0] ?? '';
    const last = Array.from(words[words.length - 1])[0] ?? '';
    return (first + last).toUpperCase();
  }
</script>

<script lang="ts">
  type Size = 'sm' | 'md';

  interface Props {
    name: string;
    size?: Size;
  }

  let { name, size = 'md' }: Props = $props();
</script>

<span class="ui-avatar ui-avatar-{size}" title={name} aria-hidden="true">{initials(name)}</span>

<style>
  .ui-avatar {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-raised);
    color: var(--text-strong);
    font-weight: 600;
    letter-spacing: 0.02em;
    user-select: none;
  }
  .ui-avatar-sm {
    width: 28px;
    height: 28px;
    font-size: 11px;
  }
  .ui-avatar-md {
    width: 36px;
    height: 36px;
    font-size: 13px;
  }
</style>
