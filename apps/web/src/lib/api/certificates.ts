// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { CertificateOverview } from './types';

export function overview(): Promise<CertificateOverview> {
  return http.get<CertificateOverview>('/api/enrollment/certificates');
}
