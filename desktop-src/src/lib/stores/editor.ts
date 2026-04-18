// Editor-Modal-Store: steuert, ob der Connection-Editor offen ist
// und welche Connection gerade bearbeitet wird. Open mit undefined
// bedeutet "neue Verbindung".

import { writable } from 'svelte/store';
import type { Connection } from '$lib/bridge/types';

interface EditorState {
  open: boolean;
  target: Connection | null;
}

const _state = writable<EditorState>({ open: false, target: null });
export const editorState = { subscribe: _state.subscribe };

export function openEditor(target?: Connection | null): void {
  _state.set({ open: true, target: target ?? null });
}

export function closeEditor(): void {
  _state.set({ open: false, target: null });
}
