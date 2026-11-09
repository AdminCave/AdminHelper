// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The section RDP of the settings offers the client an RDP start opens in (R-1098): the OS client
// first, the default of Rust, then the tab in AdminHelper. Saving it is SettingsModal.save.test.ts.
// On Linux also the switch for H.264 through Cisco's OpenH264 (R-1102) with Cisco's notice and licence.

import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { render, cleanup, screen } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import { OPENH264_LICENSE, OPENH264_NOTICE } from '$lib/models/openh264';
import RdpSection from './RdpSection.svelte';

const props = {
  rdpScalingMode: 'auto',
  rdpWindowMode: 'fit',
  rdpCustomSize: '1920x1080',
  rdpPerformanceProfile: 'auto',
  rdpH264: true,
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

describe('RdpSection — H.264 through OpenH264 (R-1102)', () => {
  it("shows the switch on Linux with Cisco's notice and the whole licence behind a summary", () => {
    const { container } = render(RdpSection, { ...props, rdpClient: 'embedded', linux: true });
    const box = screen.getByRole<HTMLInputElement>('checkbox', {
      name: tNow('settings.rdp.h264'),
    });
    expect(box.checked).toBe(true);
    expect(screen.getByText(OPENH264_NOTICE)).toBeTruthy();
    const details = container.querySelector('details')!;
    expect(details.open).toBe(false);
    expect(details.querySelector('summary')!.textContent).toBe(tNow('settings.rdp.h264.license'));
    expect(container.querySelector('[data-field="openh264-license"]')!.textContent).toBe(
      OPENH264_LICENSE,
    );
    // Condition 4 of the licence asks for all of it, the notice and itself included.
    expect(OPENH264_LICENSE).toContain(`"${OPENH264_NOTICE}"`);
    expect(OPENH264_LICENSE).toContain('4.  Any third-party software');
  });

  it('shows the state given', () => {
    render(RdpSection, { ...props, rdpClient: 'os', rdpH264: false, linux: true });
    const box = screen.getByRole<HTMLInputElement>('checkbox', {
      name: tNow('settings.rdp.h264'),
    });
    expect(box.checked).toBe(false);
  });

  it('has no switch, notice or licence off Linux', () => {
    const { container } = render(RdpSection, { ...props, rdpClient: 'os', linux: false });
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByText(OPENH264_NOTICE)).toBeNull();
    expect(container.querySelector('details')).toBeNull();
  });
});
