// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// All fictitious objects of the mockup; each object kind adds its fixture module here.
import type { Ack, MonObject } from '../model';
import { HOST_OBJECTS } from './host';
import { MODULE_OBJECTS } from './modules';
import { NETWORK_OBJECTS } from './network';
import { STORAGE_OBJECTS } from './storage';
import { DAY, ago } from './time';
import { WORKLOAD_OBJECTS } from './workloads';

/** Acknowledged problems by object key: the problem stays open, the Lage shows who confirmed it. */
export const ACKS: Record<string, Ack> = {
  'web-01/service/nginx.service': {
    by: 'admin',
    at: ago(30),
    note: '/var/log läuft voll, Logrotate wird repariert',
  },
  'backup-02/module/urbackup/urbackupsrv.service/laptop-03': {
    by: 'admin',
    at: ago(2 * DAY),
    note: 'Gerät im Urlaub, zurück am 25.11.',
  },
};

export const ALL_OBJECTS: MonObject[] = [
  ...STORAGE_OBJECTS,
  ...HOST_OBJECTS,
  ...WORKLOAD_OBJECTS,
  ...NETWORK_OBJECTS,
  ...MODULE_OBJECTS,
].map((o) => (ACKS[o.key] ? { ...o, ack: ACKS[o.key] } : o));
