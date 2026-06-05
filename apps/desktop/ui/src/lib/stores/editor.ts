// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Editor modal store: controls whether the connection editor is open
// and which connection is currently being edited. Opening with undefined
// means "new connection".

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
