// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Password prompt store: controls the RDP password modal.
// After confirmation it continues via the continuation into the performConnect flow.

import { writable } from 'svelte/store';
import type { Connection } from '$lib/bridge/types';

interface PromptState {
  open: boolean;
  connection: Connection | null;
  keepEditorOpen: boolean;
  allowRemember: boolean;
  continuation:
    | ((outcome: {
        cancelled: boolean;
        updated?: Connection;
        password?: string;
        remember?: boolean;
      }) => void)
    | null;
}

const initial: PromptState = {
  open: false,
  connection: null,
  keepEditorOpen: false,
  allowRemember: false,
  continuation: null,
};

const _state = writable<PromptState>(initial);
export const passwordPromptState = { subscribe: _state.subscribe };

export function requestPassword(
  connection: Connection,
  keepEditorOpen: boolean,
  allowRemember: boolean,
): Promise<{
  cancelled: boolean;
  updated?: Connection;
  password?: string;
  remember?: boolean;
}> {
  // A second request while a prompt is still open would overwrite the existing
  // continuation and permanently hang the first awaited promise. Cancel the
  // in-flight one first so its awaiter unblocks.
  const prev = _stateSnapshot();
  if (prev.open && prev.continuation) {
    prev.continuation({ cancelled: true });
  }
  return new Promise((resolve) => {
    _state.set({
      open: true,
      connection,
      keepEditorOpen,
      allowRemember,
      continuation: (outcome) => {
        _state.set(initial);
        resolve(outcome);
      },
    });
  });
}

export function resolvePrompt(outcome: {
  cancelled: boolean;
  updated?: Connection;
  password?: string;
  remember?: boolean;
}): void {
  const current = _stateSnapshot();
  current?.continuation?.(outcome);
}

let _snapshot: PromptState = initial;
_state.subscribe((v) => (_snapshot = v));
function _stateSnapshot(): PromptState {
  return _snapshot;
}
