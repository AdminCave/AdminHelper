// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// OS notifications name the workspace they come from (R-0431): "[<name>] " before the title of
// every toast and of the summary; the launcher has no workspace and no prefix. The notification
// plugin and the bridge are mocked; the workspace store is the real one.

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { setLanguage, tNow } from '$lib/i18n';
import { loadContext } from '$lib/stores/workspace';
import type { NotificationItem } from '$lib/api/types';
import type { WorkspaceContext } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  workspaceContext: vi.fn<() => Promise<WorkspaceContext>>(),
  isPermissionGranted: vi.fn(async () => true),
  requestPermission: vi.fn(async () => 'granted'),
  sendNotification: vi.fn(),
}));

vi.mock('$lib/bridge', () => ({ workspaceContext: h.workspaceContext }));
vi.mock('@tauri-apps/plugin-notification', () => ({
  isPermissionGranted: h.isPermissionGranted,
  requestPermission: h.requestPermission,
  sendNotification: h.sendNotification,
}));

import { notifyOs } from './osNotify';

const item = (id: number, title: string, body: string | null = null): NotificationItem => ({
  id,
  createdAt: '2026-10-20T12:00:00Z',
  severity: 'warning',
  category: 'monitoring',
  eventType: 'alert',
  title,
  body,
  read: false,
});

const two = [item(1, 'web01 down', 'no answer for 5 min'), item(2, 'db01 disk 90 %')];
const many = [1, 2, 3, 4].map((id) => item(id, `alert ${id}`));

async function windowOf(context: WorkspaceContext): Promise<void> {
  h.workspaceContext.mockResolvedValue(context);
  await loadContext();
}

beforeAll(() => {
  setLanguage('de');
});

beforeEach(() => {
  vi.clearAllMocks();
  h.isPermissionGranted.mockResolvedValue(true);
});

describe('notifyOs in the window of a workspace', () => {
  beforeEach(async () => {
    await windowOf({
      launcher: false,
      workspace: {
        id: 'w-0a1b2c3d',
        name: 'Kunde A',
        color: '#3b82f6',
        kind: 'server',
        url: 'https://ah.example.com',
        host: 'ah.example.com',
        open: true,
      },
    });
  });

  it('puts the name of the workspace before the title of every toast', async () => {
    await notifyOs(two);

    expect(h.sendNotification.mock.calls).toEqual([
      [{ title: '[Kunde A] web01 down', body: 'no answer for 5 min' }],
      [{ title: '[Kunde A] db01 disk 90 %', body: '' }],
    ]);
  });

  it('puts it before the title of the summary too', async () => {
    await notifyOs(many);

    expect(h.sendNotification).toHaveBeenCalledExactlyOnceWith({
      title: `[Kunde A] ${tNow('notifications.title')}`,
      body: tNow('notifications.osSummary', { count: 4 }),
    });
  });
});

describe('notifyOs without a workspace (launcher)', () => {
  beforeEach(async () => {
    await windowOf({ launcher: true, workspace: null });
  });

  it('sends the toasts without a prefix', async () => {
    await notifyOs(two);

    expect(h.sendNotification.mock.calls).toEqual([
      [{ title: 'web01 down', body: 'no answer for 5 min' }],
      [{ title: 'db01 disk 90 %', body: '' }],
    ]);
  });

  it('sends the summary without a prefix', async () => {
    await notifyOs(many);

    expect(h.sendNotification).toHaveBeenCalledExactlyOnceWith({
      title: tNow('notifications.title'),
      body: tNow('notifications.osSummary', { count: 4 }),
    });
  });
});
