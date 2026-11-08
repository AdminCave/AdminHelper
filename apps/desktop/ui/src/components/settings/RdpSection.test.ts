// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The section RDP of the settings offers the client an RDP start opens in (R-1098): the OS client
// first, the default of Rust, then the tab in AdminHelper. Saving it is SettingsModal.save.test.ts.

import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { render, cleanup, screen } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import RdpSection from './RdpSection.svelte';

const props = {
  rdpScalingMode: 'auto',
  rdpWindowMode: 'fit',
  rdpCustomSize: '1920x1080',
  rdpPerformanceProfile: 'auto',
} as const;

beforeAll(() => setLanguage('de'));
afterEach(() => cleanup());

describe('RdpSection — client for RDP (R-1098)', () => {
  it('offers the OS client and AdminHelper and shows the one given', () => {
    render(RdpSection, { ...props, rdpClient: 'embedded' });
    const select = screen.getByRole<HTMLSelectElement>('combobox', {
      name: tNow('settings.rdp.client'),
    });
    expect([...select.options].map((o) => [o.value, o.textContent])).toEqual([
      ['os', tNow('settings.rdp.client.os')],
      ['embedded', tNow('settings.rdp.client.embedded')],
    ]);
    expect(select.value).toBe('embedded');
  });
});
