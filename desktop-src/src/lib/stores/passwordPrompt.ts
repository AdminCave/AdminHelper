// Password-Prompt-Store: steuert das RDP-Passwort-Modal.
// Nach Bestaetigen geht es via continuation weiter in den performConnect-Flow.

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
