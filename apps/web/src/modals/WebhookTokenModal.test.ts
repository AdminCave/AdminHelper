// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The trigger example points at the gateway's enrollment plane, which takes webhook triggers
// without a client certificate (R-1687): the page's host with the port the server names.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';

import WebhookTokenModal from './WebhookTokenModal.svelte';
import { language } from '$lib/i18n';

beforeEach(() => language.set('de'));
afterEach(() => cleanup());

function example(triggerPort?: number | null): string {
  const view = render(WebhookTokenModal, {
    props: { open: true, token: 'tok-placeholder', triggerPort, onClose: () => {} },
  });
  return view.container.querySelector('code')?.textContent?.trim() ?? '';
}

describe('WebhookTokenModal', () => {
  it('names the page host on the trigger port the server sent', () => {
    const { hostname } = window.location;
    expect(example(9444)).toBe(
      `curl -X POST -H "X-Hook-Token: tok-placeholder" https://${hostname}:9444/api/hooks/trigger`,
    );
  });

  it('falls back to the origin of the page without a port', () => {
    const { origin } = window.location;
    for (const port of [undefined, null]) {
      expect(example(port)).toBe(
        `curl -X POST -H "X-Hook-Token: tok-placeholder" ${origin}/api/hooks/trigger`,
      );
      cleanup();
    }
  });
});
