// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live progress of a provisioning (R-1597): the dialog polls the server every 5 s until every
// stage is done, stops when it closes, and names the likely cause when a stage hangs.

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { setLanguage, tNow } from '$lib/i18n';
import type { ProvisionProgress } from '$lib/api/types';

const SERVER_ID = '3f2b8c1e-5d4a-4b6f-9e2d-7a1c0b9e8f42';
const NOW = Date.parse('2026-11-18T12:00:00Z');

const h = vi.hoisted(() => ({
  progress: vi.fn(),
}));

vi.mock('$lib/api/provisioning', () => ({ provisioningApi: { progress: h.progress } }));
vi.mock('$lib/stores/session', async () => {
  const { readable } = await import('svelte/store');
  return { session: readable({ serverUrl: 'https://srm.example', username: 'admin' }) };
});

import ProvisioningProgress from './ProvisioningProgress.svelte';

function at(offsetMs: number): string {
  return new Date(NOW + offsetMs).toISOString();
}

function progress(over: Partial<ProvisionProgress> = {}): ProvisionProgress {
  return {
    token: null,
    certificate: null,
    report: null,
    monitoringReachable: true,
    tunnel: { configured: false, connected: null },
    reportedPlatform: null,
    platformMismatch: false,
    ...over,
  };
}

const MIN = 60_000;
const ISSUED = progress({
  token: { createdAt: at(-2 * MIN), usedAt: null, expiresAt: at(24 * 60 * MIN) },
});
const DONE = progress({
  token: { createdAt: at(-2 * MIN), usedAt: at(-MIN), expiresAt: at(24 * 60 * MIN) },
  certificate: { issuedAt: at(-MIN) },
  report: {
    lastReportAt: at(0),
    hostFacts: { os: 'linux', platform: 'debian', platformVersion: '13' },
  },
  reportedPlatform: 'linux',
});

function states(container: HTMLElement): Record<string, string | null> {
  return Object.fromEntries(
    Array.from(container.querySelectorAll('li[data-stage]')).map((li) => [
      li.getAttribute('data-stage'),
      li.getAttribute('data-state'),
    ]),
  );
}

setLanguage('de');
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('ProvisioningProgress', () => {
  it('polls every 5 s until every stage is done, then stops', async () => {
    h.progress.mockResolvedValueOnce(ISSUED).mockResolvedValueOnce(ISSUED).mockResolvedValue(DONE);
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });

    await waitFor(() => expect(h.progress).toHaveBeenCalledTimes(1));
    expect(h.progress).toHaveBeenCalledWith(expect.anything(), SERVER_ID);
    await waitFor(() =>
      expect(states(view.container)).toEqual({
        token: 'waiting',
        certificate: 'waiting',
        report: 'waiting',
      }),
    );

    await vi.advanceTimersByTimeAsync(5_000);
    expect(h.progress).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(h.progress).toHaveBeenCalledTimes(3);
    await waitFor(() =>
      expect(states(view.container)).toEqual({
        token: 'done',
        certificate: 'done',
        report: 'done',
      }),
    );

    await vi.advanceTimersByTimeAsync(30_000);
    expect(h.progress).toHaveBeenCalledTimes(3);
  });

  it('stops polling when the dialog closes', async () => {
    h.progress.mockResolvedValue(ISSUED);
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(h.progress).toHaveBeenCalledTimes(1));

    view.unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(h.progress).toHaveBeenCalledTimes(1);
  });

  it('keeps polling through a failed request and says so only without data', async () => {
    h.progress.mockRejectedValueOnce(new Error('down')).mockResolvedValue(ISSUED);
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() =>
      expect(view.container.querySelector('[data-testid="prov-progress-error"]')).not.toBeNull(),
    );

    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() =>
      expect(view.container.querySelector('[data-testid="prov-progress-error"]')).toBeNull(),
    );
    expect(states(view.container).token).toBe('waiting');
  });

  it('keeps the stages of an earlier answer through a failed request, without an error', async () => {
    h.progress
      .mockResolvedValueOnce(ISSUED)
      .mockRejectedValueOnce(new Error('bad gateway'))
      .mockResolvedValue(DONE);
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).token).toBe('waiting'));

    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() => expect(h.progress).toHaveBeenCalledTimes(2));
    expect(states(view.container)).toEqual({
      token: 'waiting',
      certificate: 'waiting',
      report: 'waiting',
    });
    expect(view.container.querySelector('[data-testid="prov-progress-error"]')).toBeNull();

    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() => expect(states(view.container).report).toBe('done'));
  });

  it('counts an agent certificate as redeemed once the used token is gone', async () => {
    // The token cleanup deletes redeemed tokens: only the certificate is left.
    h.progress.mockResolvedValue(progress({ certificate: { issuedAt: at(-MIN) } }));
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).token).toBe('done'));
    expect(states(view.container).certificate).toBe('done');
  });

  it('names an expired token', async () => {
    h.progress.mockResolvedValue(
      progress({ token: { createdAt: at(-25 * 60 * MIN), usedAt: null, expiresAt: at(-MIN) } }),
    );
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() =>
      expect(
        view.container.querySelector('[data-testid="prov-hint-expired"]')?.textContent,
      ).toContain(tNow('infra.prov.hint.expired')),
    );
  });

  it('hints at ports, clock and proxy 5 min after the redemption without a report', async () => {
    const redeemed = progress({
      token: { createdAt: at(-5 * MIN), usedAt: at(-4 * MIN), expiresAt: at(24 * 60 * MIN) },
      certificate: { issuedAt: at(-4 * MIN) },
    });
    h.progress.mockResolvedValue(redeemed);
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).certificate).toBe('done'));
    expect(view.container.querySelector('[data-testid="prov-hint-report"]')).toBeNull();

    await vi.advanceTimersByTimeAsync(65_000);
    await waitFor(() =>
      expect(
        view.container.querySelector('[data-testid="prov-hint-report"]')?.textContent,
      ).toContain('8444'),
    );
  });

  it('takes the certificate as the anchor when the token is gone', async () => {
    h.progress.mockResolvedValue(progress({ certificate: { issuedAt: at(-6 * MIN) } }));
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() =>
      expect(view.container.querySelector('[data-testid="prov-hint-report"]')).not.toBeNull(),
    );
  });

  it('shows no report hint while the monitoring cannot be asked', async () => {
    h.progress.mockResolvedValue(
      progress({ certificate: { issuedAt: at(-60 * MIN) }, monitoringReachable: false }),
    );
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).report).toBe('unknown'));
    expect(view.container.querySelector('[data-testid="prov-hint-report"]')).toBeNull();
  });

  it('adds the tunnel stage only for a server with a tunnel, and hints when it is down', async () => {
    h.progress.mockResolvedValue({ ...DONE, tunnel: { configured: true, connected: false } });
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).tunnel).toBe('waiting'));
    expect(view.container.querySelector('[data-testid="prov-hint-tunnel"]')).not.toBeNull();
    // Not complete: still polling.
    await vi.advanceTimersByTimeAsync(5_000);
    expect(h.progress).toHaveBeenCalledTimes(2);
  });

  it('marks a tunnel without proxy lists as unknown, not as down', async () => {
    h.progress.mockResolvedValue({ ...DONE, tunnel: { configured: true, connected: null } });
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).tunnel).toBe('unknown'));
    expect(view.container.querySelector('[data-testid="prov-hint-tunnel"]')).toBeNull();
  });

  it('names a reported platform that differs from the chosen one', async () => {
    h.progress.mockResolvedValue({ ...DONE, reportedPlatform: 'windows', platformMismatch: true });
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() =>
      expect(
        view.container.querySelector('[data-testid="prov-hint-platform"]')?.textContent,
      ).toContain('Windows'),
    );
  });

  it('offers the monitoring suggestions once everything is done', async () => {
    h.progress.mockResolvedValueOnce(ISSUED).mockResolvedValue(DONE);
    const onShowMonitoring = vi.fn();
    const view = render(ProvisioningProgress, { serverId: SERVER_ID, onShowMonitoring });
    await waitFor(() => expect(h.progress).toHaveBeenCalledTimes(1));
    expect(view.container.querySelector('[data-action="prov-show-monitoring"]')).toBeNull();

    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() =>
      expect(view.container.querySelector('[data-action="prov-show-monitoring"]')).not.toBeNull(),
    );
    await fireEvent.click(
      view.container.querySelector('[data-action="prov-show-monitoring"]') as HTMLElement,
    );
    expect(onShowMonitoring).toHaveBeenCalledTimes(1);
  });

  it('counts nothing of an earlier run for a fresh token on a registered server', async () => {
    // Re-registration: certificate and reports of the earlier run, a new token not yet redeemed.
    const fresh = {
      ...DONE,
      token: { createdAt: at(-MIN), usedAt: null, expiresAt: at(24 * 60 * MIN) },
      certificate: { issuedAt: at(-30 * 24 * 60 * MIN) },
      report: { lastReportAt: at(0), hostFacts: null },
    };
    const redeemed = {
      ...fresh,
      token: { ...fresh.token, usedAt: at(4_000) },
      certificate: { issuedAt: at(4_000) },
      report: { lastReportAt: at(6_000), hostFacts: null },
    };
    h.progress.mockResolvedValueOnce(fresh).mockResolvedValue(redeemed);
    const view = render(ProvisioningProgress, { serverId: SERVER_ID, onShowMonitoring: vi.fn() });
    await waitFor(() =>
      expect(states(view.container)).toEqual({
        token: 'waiting',
        certificate: 'waiting',
        report: 'waiting',
      }),
    );
    expect(view.container.querySelector('[data-action="prov-show-monitoring"]')).toBeNull();

    await vi.advanceTimersByTimeAsync(5_000);
    await waitFor(() =>
      expect(states(view.container)).toEqual({
        token: 'done',
        certificate: 'done',
        report: 'done',
      }),
    );
  });

  it('takes a certificate newer than the token as its redemption', async () => {
    h.progress.mockResolvedValue({
      ...DONE,
      token: { createdAt: at(-2 * MIN), usedAt: null, expiresAt: at(-MIN) },
      certificate: { issuedAt: at(-MIN) },
    });
    const view = render(ProvisioningProgress, { serverId: SERVER_ID });
    await waitFor(() => expect(states(view.container).token).toBe('done'));
    expect(view.container.querySelector('[data-testid="prov-hint-expired"]')).toBeNull();
  });
});
