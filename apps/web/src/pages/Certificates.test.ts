// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The certificate page (R-1022): both tables with days left and traffic light, "no data"
// when the ca-issuer recorded nothing, and names and subjects shown as text.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api/certificates', () => ({ overview: vi.fn() }));
vi.mock('$lib/stores/notifications', () => ({ showError: vi.fn() }));

import Certificates from './Certificates.svelte';
import { overview } from '$lib/api/certificates';
import { showError } from '$lib/stores/notifications';
import { language } from '$lib/i18n';
import type { AgentCertificate, InfraCertificate } from '$lib/api/types';

function infra(name: string, days: number, status: InfraCertificate['status']): InfraCertificate {
  return {
    name,
    subject: `CN=${name}`,
    fingerprint: `fp-${name}`,
    not_after: '2026-12-01T00:00:00Z',
    days_left: days,
    status,
  };
}

function agent(id: string, name: string | null, days: number): AgentCertificate {
  return {
    server_id: id,
    server_name: name,
    fingerprint: `fp-${id}`,
    not_after: '2026-11-05T00:00:00Z',
    days_left: days,
    status: days < 7 ? 'critical' : days < 30 ? 'warning' : 'ok',
  };
}

function section(container: HTMLElement, name: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(`[data-section="${name}"]`);
  expect(el, `no section ${name}`).not.toBeNull();
  return el as HTMLElement;
}

function cells(el: HTMLElement): string[][] {
  return [...el.querySelectorAll('tbody tr')].map((tr) =>
    [...tr.querySelectorAll('td')].map((td) => td.textContent?.trim() ?? ''),
  );
}

beforeEach(() => {
  language.set('de');
  vi.mocked(overview).mockReset();
  vi.mocked(showError).mockReset();
});

afterEach(() => cleanup());

describe('Certificates page', () => {
  it('shows days left and the traffic light in both tables', async () => {
    vi.mocked(overview).mockResolvedValue({
      infrastructure: [infra('gateway', 20, 'warning'), infra('root', 3650, 'ok')],
      agents: [agent('srv-1', 'web-01', 3), agent('srv-2', null, -1)],
    });
    const { container } = render(Certificates);
    await waitFor(() => expect(container.querySelectorAll('tbody tr').length).toBe(4));

    const inf = cells(section(container, 'infrastructure'));
    expect(inf.map((r) => [r[0], r[1], r[3], r[4]])).toEqual([
      ['gateway', 'CN=gateway', '20', 'Bald fällig'],
      ['root', 'CN=root', '3650', 'OK'],
    ]);
    const ag = cells(section(container, 'agents'));
    // A deleted server keeps its line under its id; an expired one says so.
    expect(ag.map((r) => [r[0], r[2], r[3]])).toEqual([
      ['web-01', '3', 'Kritisch'],
      ['srv-2', 'abgelaufen', 'Kritisch'],
    ]);
    expect(section(container, 'agents').querySelector('.light.critical')).not.toBeNull();
  });

  it('says "no data" when the ca-issuer recorded nothing', async () => {
    vi.mocked(overview).mockResolvedValue({ infrastructure: [], agents: [] });
    const { container } = render(Certificates);
    await waitFor(() =>
      expect(section(container, 'infrastructure').textContent).toContain('Keine Daten'),
    );
    expect(section(container, 'agents').textContent).toContain('Kein Agent');
  });

  it('shows markup in a subject or server name as text', async () => {
    vi.mocked(overview).mockResolvedValue({
      infrastructure: [{ ...infra('gateway', 100, 'ok'), subject: '<b>CN=x</b>' }],
      agents: [agent('srv-1', '<img src=x>', 100)],
    });
    const { container } = render(Certificates);
    await waitFor(() => expect(container.querySelectorAll('tbody tr').length).toBe(2));

    expect(cells(section(container, 'infrastructure'))[0][1]).toBe('<b>CN=x</b>');
    expect(cells(section(container, 'agents'))[0][0]).toBe('<img src=x>');
    expect(container.querySelector('tbody b, tbody img')).toBeNull();
  });

  it('reports a failed load and shows no table', async () => {
    const err = new Error('boom');
    vi.mocked(overview).mockRejectedValue(err);
    const { container } = render(Certificates);
    await waitFor(() => expect(showError).toHaveBeenCalledWith(err));

    expect(container.textContent).not.toContain('Lädt');
    expect(container.querySelector('table')).toBeNull();
  });
});
