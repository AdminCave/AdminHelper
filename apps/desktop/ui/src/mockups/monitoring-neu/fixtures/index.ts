// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// All fictitious objects of the mockup; each object kind adds its fixture module here.
import type { MonObject } from '../model';
import { STORAGE_OBJECTS } from './storage';

export const ALL_OBJECTS: MonObject[] = [...STORAGE_OBJECTS];
