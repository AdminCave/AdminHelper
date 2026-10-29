// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { tNow } from '$lib/i18n';
import { showToast } from '$lib/stores/notifications';

// Copies text and says how it went: the toast of okKey, or "copy failed" when the browser refuses
// or has no clipboard API (an insecure context). Never throws; true if the text was copied.
export async function copyToClipboard(text: string, okKey: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    showToast(tNow('toast.copyFailed'), 'error');
    return false;
  }
  showToast(tNow(okKey));
  return true;
}
