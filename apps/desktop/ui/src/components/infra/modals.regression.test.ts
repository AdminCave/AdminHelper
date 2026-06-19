// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Regression guard for an effect_update_depth_exceeded crash: both modals used
// to read `form.tags` right after assigning a fresh object to `form` inside the
// open-effect, making the effect depend on the state it writes. That self-looped
// on every open, killed the component's reactivity, and left every input and
// button (including Cancel) dead. Mounting the real component reproduces it.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { setLanguage } from '$lib/i18n';
import TunnelModal from './TunnelModal.svelte';
import ServerConnectionModal from './ServerConnectionModal.svelte';

setLanguage('de');
afterEach(cleanup);

describe('infra modals open without an effect loop', () => {
  it('ServerConnectionModal: mounts, keeps typed input, Cancel fires onClose', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole, container } = render(ServerConnectionModal, {
      props: { open: true, target: null, serverId: 'srv-1', onClose, onSaved: vi.fn() },
    });
    await tick();

    expect(getByRole('dialog')).toBeTruthy();

    const nameInput = container.querySelector('input[type="text"]') as HTMLInputElement;
    await fireEvent.input(nameInput, { target: { value: 'my-server' } });
    await tick();
    expect(nameInput.value).toBe('my-server');

    await fireEvent.click(getByText('Abbrechen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('TunnelModal: mounts, keeps typed input, Cancel fires onClose', async () => {
    const onClose = vi.fn();
    const { getByText, getByRole, container } = render(TunnelModal, {
      props: {
        open: true,
        editing: null,
        serverId: 'srv-1',
        configs: [],
        onClose,
        onSaved: vi.fn(),
      },
    });
    await tick();

    expect(getByRole('dialog')).toBeTruthy();

    const nameInput = container.querySelector('input[type="text"]') as HTMLInputElement;
    await fireEvent.input(nameInput, { target: { value: 'k01-ssh' } });
    await tick();
    expect(nameInput.value).toBe('k01-ssh');

    await fireEvent.click(getByText('Abbrechen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
