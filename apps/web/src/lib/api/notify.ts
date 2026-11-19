// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type {
  NotifyChannels,
  NotifyChannelsInput,
  NotifyChannelTest,
  NotifyTemplate,
  NotifyTemplateInput,
  NotifyTemplateLogo,
  NotifyTemplatePreview,
  NotifyTemplateTest,
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

export function getTemplate(): Promise<NotifyTemplate> {
  return http.get<NotifyTemplate>('/api/admin/notify/template');
}

export function saveTemplate(data: NotifyTemplateInput): Promise<NotifyTemplate> {
  return http.put<NotifyTemplate>('/api/admin/notify/template', data);
}

export function resetTemplate(): Promise<NotifyTemplate> {
  return http.del<NotifyTemplate>('/api/admin/notify/template');
}

export function previewTemplate(data: NotifyTemplateInput): Promise<NotifyTemplatePreview> {
  return http.post<NotifyTemplatePreview>('/api/admin/notify/template/preview', data);
}

export function testTemplate(data: NotifyTemplateTest): Promise<NotifyTestResult> {
  return http.post<NotifyTestResult>('/api/admin/notify/template/test', data);
}

export function saveLogo(data: NotifyTemplateLogo): Promise<NotifyTemplate> {
  return http.put<NotifyTemplate>('/api/admin/notify/template/logo', data);
}

export function deleteLogo(): Promise<NotifyTemplate> {
  return http.del<NotifyTemplate>('/api/admin/notify/template/logo');
}
