// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { ApiKey, ApiKeyCreate, ApiKeyCreateResult } from '$lib/api/types';
import * as api from '$lib/api/apikeys';
import { listStore } from './listStore';

const list = listStore<ApiKey>(api.list);

export const apikeys = {
  subscribe: list.subscribe,
  refresh: list.refresh,
  reset: list.reset,

  create(data: ApiKeyCreate): Promise<ApiKeyCreateResult> {
    return list.mutate(
      () => api.create(data),
      (keys, created) => [
        ...keys,
        { id: created.id, name: created.name, permission: created.permission },
      ],
    );
  },

  remove(id: number): Promise<void> {
    return list.mutate(
      () => api.remove(id),
      (keys) => keys.filter((k) => k.id !== id),
    );
  },
};
