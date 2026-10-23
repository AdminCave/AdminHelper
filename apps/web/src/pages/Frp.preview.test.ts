// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * The frps.toml / visitor.toml preview on the FRP page: open, it gets the fetched text; closed,
 * the page no longer holds it.
 *
 * The real Modal renders nothing while closed (`{#if open}` in Modal.svelte), so a test that
 * looks at the DOM after closing would pass whether or not the page still holds the text. So
 * FrpConfigPreviewModal is a vi.fn here and the test reads the props the page handed it: Svelte 5
 * calls a component as `Component(anchor, props)`, with getters on the page's state, so
 * `props.content` is what the page holds right now. FrpConfigModal and FrpStatusModal stay real;
 * closed, they do nothing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type * as FrpApi from '$lib/api/frp';
import type { FrpConfig } from '$lib/api/types';

interface PreviewProps {
  open: boolean;
  title: string;
  content: string;
  onClose: () => void;
}

const h = vi.hoisted(() => ({
  Preview: vi.fn<(anchor: Node, props: PreviewProps) => void>(),
}));

vi.mock('$lib/api/frp', async (importOriginal) => ({
  ...(await importOriginal<typeof FrpApi>()),
  listConfigs: vi.fn(),
  supervisorStatus: vi.fn(),
  getFrpsToml: vi.fn(),
  getVisitorToml: vi.fn(),
}));
vi.mock('$modals/FrpConfigPreviewModal.svelte', () => ({ default: h.Preview }));

import Frp from './Frp.svelte';
import { listConfigs, supervisorStatus, getFrpsToml, getVisitorToml } from '$lib/api/frp';

// Without a config the page shows no preview buttons.
const CONFIG: FrpConfig = {
  id: 'cfg-1',
  name: 'frps',
  serverAddr: '203.0.113.10',
  bindPort: 7000,
  dashboardPort: 7500,
  dashboardUser: 'admin',
};

const FILES = [
  {
    file: 'frps.toml',
    fetcher: getFrpsToml,
    text: [
      'bindPort = 7000',
      'auth.token = "frp-s3cr3t-token"',
      'webServer.port = 7500',
      'webServer.user = "admin"',
      'webServer.password = "dash-s3cr3t"',
    ].join('\n'),
  },
  {
    file: 'visitor.toml',
    fetcher: getVisitorToml,
    text: [
      'serverAddr = "203.0.113.10"',
      'auth.token = "frp-s3cr3t-token"',
      '',
      '[[visitors]]',
      'name = "web01-ssh-visitor"',
      'type = "stcp"',
      'secretKey = "stcp-s3cr3t"',
    ].join('\n'),
  },
];

/** The props the page handed the preview once, on mounting; reading them reads its state now. */
function previewProps(): PreviewProps {
  expect(h.Preview).toHaveBeenCalledTimes(1);
  return h.Preview.mock.calls[0][1];
}

/** Mounts the page and waits for its preview buttons. */
async function mount() {
  const view = render(Frp);
  await view.findByRole('button', { name: 'frps.toml' });
  return view;
}

async function open(view: Awaited<ReturnType<typeof mount>>, file: string) {
  await fireEvent.click(view.getByRole('button', { name: file }));
  await waitFor(() => expect(previewProps().open).toBe(true));
}

beforeEach(() => {
  h.Preview.mockReset();
  vi.mocked(listConfigs).mockReset().mockResolvedValue([CONFIG]);
  // The state block is not under test; a failed request turns it neutral without a toast.
  vi.mocked(supervisorStatus).mockReset().mockRejectedValue(new TypeError('Failed to fetch'));
  vi.mocked(getFrpsToml).mockReset();
  vi.mocked(getVisitorToml).mockReset();
});

afterEach(() => {
  cleanup();
});

describe.each(FILES)('the $file preview', ({ file, fetcher, text }) => {
  beforeEach(() => {
    vi.mocked(fetcher).mockResolvedValue(text);
  });

  it('gets the fetched text while open', async () => {
    const view = await mount();
    expect(previewProps().open).toBe(false);
    expect(previewProps().content).toBe('');

    await open(view, file);

    expect(fetcher).toHaveBeenCalledTimes(1);
    const props = previewProps();
    expect(props.title).toBe(file);
    expect(props.content).toBe(text);
  });

  it('leaves no text behind once closed', async () => {
    const view = await mount();
    await open(view, file);

    previewProps().onClose();
    await tick();

    const props = previewProps();
    expect(props.open).toBe(false);
    expect(props.content).toBe('');
  });

  it('fetches the text again when opened again', async () => {
    const view = await mount();
    await open(view, file);
    previewProps().onClose();
    await tick();

    await open(view, file);

    expect(fetcher).toHaveBeenCalledTimes(2);
    const props = previewProps();
    expect(props.title).toBe(file);
    expect(props.content).toBe(text);
  });
});
