// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type {
  NotifyChannels,
  NotifyChannelsInput,
  NotifyChannelTest,
  NotifyTestResult,
} from './types';

export function getChannels(): Promise<NotifyChannels> {
  return http.get<NotifyChannels>('/api/admin/notify/channels');
}

export function saveChannels(data: NotifyChannelsInput): Promise<NotifyChannels> {
  return http.put<NotifyChannels>('/api/admin/notify/channels', data);
}

export function testChannel(data: NotifyChannelTest): Promise<NotifyTestResult> {
  return http.post<NotifyTestResult>('/api/admin/notify/channels/test', data);
}
