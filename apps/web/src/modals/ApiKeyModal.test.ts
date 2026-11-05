// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The permission select binds a string; what is chosen there is what the API key is created with.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/stores/apikeys', () => ({ apikeys: { create: vi.fn() } }));

import ApiKeyModal from './ApiKeyModal.svelte';
import { apikeys } from '$lib/stores/apikeys';
import { language } from '$lib/i18n';

beforeEach(() => {
  language.set('de');
  vi.mocked(apikeys.create)
    .mockReset()
    .mockResolvedValue({ key: 'key-placeholder' } as Awaited<ReturnType<typeof apikeys.create>>);
});

afterEach(() => cleanup());

describe('ApiKeyModal', () => {
  it.each(['read', 'read_write'])('creates the key with permission %s', async (permission) => {
    const onReveal = vi.fn();
    const view = render(ApiKeyModal, { props: { open: true, onClose: () => {}, onReveal } });
    const name = view.container.querySelector<HTMLInputElement>('#akName')!;
    const select = view.container.querySelector<HTMLSelectElement>('#akPermission')!;

    await fireEvent.input(name, { target: { value: ' sync ' } });
    await fireEvent.change(select, { target: { value: permission } });
    await fireEvent.submit(view.container.querySelector('#apikey-form')!);

    await waitFor(() => expect(onReveal).toHaveBeenCalledWith('key-placeholder'));
    expect(apikeys.create).toHaveBeenCalledWith({ name: 'sync', permission });
  });
});
