// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// All fictitious objects of the mockup; each object kind adds its fixture module here.
import type { MonObject } from '../model';
import { HOST_OBJECTS } from './host';
import { MODULE_OBJECTS } from './modules';
import { NETWORK_OBJECTS } from './network';
import { STORAGE_OBJECTS } from './storage';
import { WORKLOAD_OBJECTS } from './workloads';

export const ALL_OBJECTS: MonObject[] = [
  ...STORAGE_OBJECTS,
  ...HOST_OBJECTS,
  ...WORKLOAD_OBJECTS,
  ...NETWORK_OBJECTS,
  ...MODULE_OBJECTS,
];
