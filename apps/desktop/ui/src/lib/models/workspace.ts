// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Workspace model (R-0431): pure functions + constants, no side effects. Rust checks a
// draft again on save_workspace (launcher.rs `checked`) and stays the authority; this is
// the immediate feedback of the form.

import type { WorkspaceDraft } from '$lib/bridge/types';
import { tNow } from '$lib/i18n';
import { getSettingsDefaults, validateSettings, type SettingsValidation } from './settings';

/** The colours a workspace can take, in the order of workspace.rs PALETTE. */
export const WORKSPACE_PALETTE = [
  '#3b82f6',
  '#22c55e',
  '#f59e0b',
  '#ef4444',
  '#8b5cf6',
  '#ec4899',
  '#06b6d4',
  '#64748b',
] as const;

/** The longest name of a workspace, in characters (launcher.rs NAME_MAX_CHARS). */
export const WORKSPACE_NAME_MAX = 40;

// Rust's char::is_control: the general category Cc.
const CONTROL = /\p{Cc}/u;

export function validateDraft(draft: WorkspaceDraft): SettingsValidation {
  if (CONTROL.test(draft.name)) {
    return { ok: false, error: tNow('validation.workspaceName.control') };
  }
  const name = draft.name.trim();
  if (!name) return { ok: false, error: tNow('validation.name.empty') };
  // Characters as Rust counts them (code points), not UTF-16 units.
  if ([...name].length > WORKSPACE_NAME_MAX) {
    return {
      ok: false,
      error: tNow('validation.workspaceName.tooLong', { max: WORKSPACE_NAME_MAX }),
    };
  }
  // The URL follows the rules validateSettings has for the mode of the same name, one place
  // for both: a server or sync workspace needs one, https:// only, http:// for a server on
  // loopback; a local workspace has none to check.
  const url = draft.url ?? '';
  return validateSettings({ ...getSettingsDefaults(), mode: draft.kind, url, serverUrl: url });
}

/**
 * The host of `url` as the picker lists it (workspace.rs host_of), to name a new workspace
 * after its server; null for no URL or one without a host.
 */
export function hostOf(url: string | null | undefined): string | null {
  try {
    return new URL((url ?? '').trim()).hostname || null;
  } catch {
    return null;
  }
}
