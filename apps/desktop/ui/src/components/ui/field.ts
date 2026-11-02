// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { getContext, setContext } from 'svelte';

// What FormField hands to the control inside it, so label, hint and error reach the
// control without the page wiring ids by hand.
export interface FieldContext {
  readonly id: string;
  // Unset while the field has no visible label.
  readonly labelId: string | undefined;
  readonly describedBy: string | undefined;
  readonly invalid: boolean;
  // A group (radiogroup) is no labelable element: the label then names it by id only.
  markGroup(): void;
}

const KEY = Symbol('ui-field');

export function setField(ctx: FieldContext): void {
  setContext(KEY, ctx);
}

export function getField(): FieldContext | undefined {
  return getContext<FieldContext | undefined>(KEY);
}
