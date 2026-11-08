// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The connect button of a connection (R-1069, R-1098): for SSH and RDP the main part starts where
// the settings say and the arrow picks for this start; Web has a single button.

import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import type { Connection } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import ConnectButton from './ConnectButton.svelte';

const SSH = { id: 'a', name: 'web01', kind: 'ssh', host: 'web01.example' } as Connection;
const RDP = { id: 'b', name: 'db01', kind: 'rdp', host: 'db01.example' } as Connection;
const WEB = { id: 'c', name: 'portal', kind: 'web', url: 'https://portal.example' } as Connection;

function setup(conn: Connection) {
  const onConnect = vi.fn();
  render(ConnectButton, { conn, onConnect });
  return onConnect;
}

const arrow = () => screen.queryByRole('button', { name: tNow('connections.connect.choose') });

beforeAll(() => setLanguage('de'));
afterEach(() => cleanup());

describe('ConnectButton', () => {
  it('starts an SSH connection in the console of the settings with the main button', async () => {
    const onConnect = setup(SSH);
    await fireEvent.click(screen.getByRole('button', { name: tNow('action.connect') }));
    expect(onConnect).toHaveBeenCalledExactlyOnceWith(SSH);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('starts an SSH connection in the console picked from the menu of the arrow', async () => {
    const onConnect = setup(SSH);
    expect(arrow()?.getAttribute('aria-haspopup')).toBe('menu');

    await fireEvent.click(arrow()!);
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent?.trim())).toEqual([
      tNow('connections.connect.embedded'),
      tNow('connections.connect.external'),
    ]);
    await fireEvent.click(
      screen.getByRole('menuitem', { name: tNow('connections.connect.embedded') }),
    );
    expect(onConnect).toHaveBeenLastCalledWith(SSH, 'embedded');
    expect(screen.queryByRole('menu')).toBeNull();

    await fireEvent.click(arrow()!);
    await fireEvent.click(
      screen.getByRole('menuitem', { name: tNow('connections.connect.external') }),
    );
    expect(onConnect).toHaveBeenLastCalledWith(SSH, 'external');
    expect(onConnect).toHaveBeenCalledTimes(2);
  });

  it('starts RDP where the settings say, or in the client picked from the arrow', async () => {
    const onConnect = setup(RDP);
    expect(arrow()).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: tNow('action.connect') }));
    expect(onConnect).toHaveBeenCalledExactlyOnceWith(RDP);

    const rdpArrow = screen.getByRole('button', { name: tNow('connections.connect.rdpChoose') });
    await fireEvent.click(rdpArrow);
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent?.trim())).toEqual([
      tNow('connections.connect.rdpEmbedded'),
      tNow('connections.connect.rdpExternal'),
    ]);
    await fireEvent.click(
      screen.getByRole('menuitem', { name: tNow('connections.connect.rdpEmbedded') }),
    );
    expect(onConnect).toHaveBeenLastCalledWith(RDP, 'embedded');
    await fireEvent.click(rdpArrow);
    await fireEvent.click(
      screen.getByRole('menuitem', { name: tNow('connections.connect.rdpExternal') }),
    );
    expect(onConnect).toHaveBeenLastCalledWith(RDP, 'external');
  });

  it('gives Web a single open button without a menu', async () => {
    const onConnect = setup(WEB);
    expect(arrow()).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    await fireEvent.click(screen.getByRole('button', { name: tNow('connections.open') }));
    expect(onConnect).toHaveBeenCalledExactlyOnceWith(WEB);
  });
});
