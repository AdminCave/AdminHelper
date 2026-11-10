// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * The FRP status view names each proxy by its tunnel (R-1210): frps lists a proxy as
 * "{server-id}.{tunnel-id}", which reads as two UUIDs; the server attaches the tunnel with
 * its display name. A proxy without a tunnel (another frpc) keeps the name frps gives it.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';
import type * as FrpApi from '$lib/api/frp';

vi.mock('$lib/api/frp', async (importOriginal) => ({
  ...(await importOriginal<typeof FrpApi>()),
  status: vi.fn(),
}));

import FrpStatusModal from './FrpStatusModal.svelte';
import { status } from '$lib/api/frp';

afterEach(cleanup);

const proxy = (name: string, tunnel: { id: string; name: string } | null) => ({
  name,
  type: 'stcp',
  status: 'online',
  curConns: 0,
  todayTrafficIn: 0,
  todayTrafficOut: 0,
  tunnel,
});

describe('FrpStatusModal', () => {
  it('shows the tunnel name for a proxy of a tunnel, the proxy name otherwise', async () => {
    vi.mocked(status).mockResolvedValueOnce({
      proxies: [
        proxy('7a0e4d2c-1b3f-4a5e-8c6d-9e0f1a2b3c4d.2f6b1c3e-0d4a-4e8b-9a71-5c2d8e9f0a1b', {
          id: '2f6b1c3e-0d4a-4e8b-9a71-5c2d8e9f0a1b',
          name: 'web01.example.org · SSH (FRP)',
        }),
        proxy('other.legacy', null),
      ],
      total: 2,
    });
    const { container } = render(FrpStatusModal, { props: { open: true, onClose: vi.fn() } });
    await waitFor(() => expect(container.querySelectorAll('tbody tr')).toHaveLength(2));
    const names = [...container.querySelectorAll('tbody tr')].map((row) =>
      row.querySelectorAll('td')[1].textContent?.trim(),
    );
    expect(names).toEqual(['web01.example.org · SSH (FRP)', 'other.legacy']);
  });
});
