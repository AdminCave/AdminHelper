// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The form -> payload mapping of the hook dialog (R-0722), pinned with the exact payload the
// dialog hands the hooks store: trimming, an empty description as null, the fields per hook type,
// the custom cron, and the validation that sends nothing.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('$lib/stores/hooks', () => ({ hooks: { create: vi.fn(), update: vi.fn() } }));
vi.mock('$lib/stores/notifications', () => ({ showToast: vi.fn(), showError: vi.fn() }));

import HookModal from './HookModal.svelte';
import { hooks } from '$lib/stores/hooks';
import { showToast, showError } from '$lib/stores/notifications';
import { t } from '$lib/i18n';
import { HOOK_EVENTS } from '$lib/utils/hooks';
import type { HookDetail } from '$lib/api/types';

const create = vi.mocked(hooks.create);
const update = vi.mocked(hooks.update);

function renderModal(editing: HookDetail | null = null) {
  const onClose = vi.fn();
  const view = render(HookModal, { props: { open: true, editing, onClose } });
  const el = <T extends Element = HTMLInputElement>(selector: string) =>
    view.container.querySelector(selector) as unknown as T;
  return {
    onClose,
    el,
    input: (selector: string, value: string) =>
      fireEvent.input(el(selector), { target: { value } }),
    select: (selector: string, value: string) =>
      fireEvent.change(el<HTMLSelectElement>(selector), { target: { value } }),
    clickEvent: (evt: string) =>
      fireEvent.click(
        view.container.querySelectorAll('input[type="checkbox"]')[
          HOOK_EVENTS.indexOf(evt as never)
        ],
      ),
    submit: () => fireEvent.submit(el('#hook-form')),
  };
}

function detail(over: Partial<HookDetail>): HookDetail {
  return {
    id: 'h1',
    name: 'nightly',
    description: 'old text',
    hook_type: 'schedule',
    enabled: true,
    script: 'print(1)',
    ...over,
  } as HookDetail;
}

beforeEach(() => {
  create
    .mockReset()
    .mockResolvedValue({ id: 'new', name: 'x', hook_type: 'webhook', enabled: true, script: '' });
  update.mockReset().mockResolvedValue(detail({}));
  vi.mocked(showToast).mockReset();
  vi.mocked(showError).mockReset();
});

afterEach(() => cleanup());

describe('HookModal: create', () => {
  it('a webhook: trimmed name, a blank description as null, no trigger fields; the token goes to onClose', async () => {
    create.mockResolvedValue({
      id: 'new',
      name: 'deploy',
      hook_type: 'webhook',
      enabled: true,
      token: 'one-time-placeholder',
    } as never);
    const m = renderModal();
    await m.input('#hkName', '  deploy  ');
    await m.input('#hkDesc', '   ');
    await m.input('#hkScript', 'echo');
    await m.submit();

    await waitFor(() => expect(m.onClose).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith({
      name: 'deploy',
      description: null,
      hook_type: 'webhook',
      script: 'echo',
    });
    expect(m.onClose).toHaveBeenCalledWith({ token: 'one-time-placeholder' });
  });

  it('an event hook without an event sends nothing and says why', async () => {
    const m = renderModal();
    await m.input('#hkName', 'e');
    await m.select('#hkType', 'event');
    await m.submit();

    expect(create).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(get(t)('modal.hook.selectEvent'), 'error');
  });

  it('an event hook sends its events in click order', async () => {
    const m = renderModal();
    await m.input('#hkName', 'e');
    await m.select('#hkType', 'event');
    await m.clickEvent(HOOK_EVENTS[2]);
    await m.clickEvent(HOOK_EVENTS[0]);
    await m.submit();

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith({
      name: 'e',
      description: null,
      hook_type: 'event',
      script: '',
      event_triggers: [HOOK_EVENTS[2], HOOK_EVENTS[0]],
    });
  });

  it('a schedule hook with a preset sends that interval', async () => {
    const m = renderModal();
    await m.input('#hkName', 's');
    await m.select('#hkType', 'schedule');
    await m.select('#hkInterval', '6h');
    await m.submit();

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith({
      name: 's',
      description: null,
      hook_type: 'schedule',
      script: '',
      schedule_interval: '6h',
    });
  });

  it('a custom schedule sends the cron trimmed', async () => {
    const m = renderModal();
    await m.input('#hkName', 's');
    await m.select('#hkType', 'schedule');
    await m.select('#hkInterval', 'custom');
    await m.input('#hkCron', '  */5 * * * *  ');
    await m.submit();

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith({
      name: 's',
      description: null,
      hook_type: 'schedule',
      script: '',
      schedule_interval: '*/5 * * * *',
    });
  });

  it('an empty custom schedule sends nothing and says why', async () => {
    const m = renderModal();
    await m.input('#hkName', 's');
    await m.select('#hkType', 'schedule');
    await m.select('#hkInterval', 'custom');
    await m.input('#hkCron', '   ');
    await m.submit();

    expect(create).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(get(t)('modal.hook.selectInterval'), 'error');
  });

  it('a store that throws leaves the dialog open', async () => {
    create.mockRejectedValue(new Error('refused'));
    const m = renderModal();
    await m.input('#hkName', 'w');
    await m.submit();

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(m.onClose).not.toHaveBeenCalled();
  });
});

describe('HookModal: edit', () => {
  it('a schedule hook with a cron that is no preset shows custom; the update has no type or events', async () => {
    const m = renderModal(detail({ schedule_interval: '*/7 * * * *' }));
    expect(m.el<HTMLSelectElement>('#hkInterval').value).toBe('custom');
    expect(m.el('#hkCron').value).toBe('*/7 * * * *');
    await m.input('#hkDesc', '');
    await m.submit();

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update).toHaveBeenCalledWith('h1', {
      name: 'nightly',
      description: null,
      script: 'print(1)',
      schedule_interval: '*/7 * * * *',
    });
  });

  it('an event hook sends its events and no interval', async () => {
    const m = renderModal(
      detail({
        hook_type: 'event',
        event_triggers: [HOOK_EVENTS[1]],
        schedule_interval: undefined,
      }),
    );
    await m.submit();

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update).toHaveBeenCalledWith('h1', {
      name: 'nightly',
      description: 'old text',
      script: 'print(1)',
      event_triggers: [HOOK_EVENTS[1]],
    });
  });
});
