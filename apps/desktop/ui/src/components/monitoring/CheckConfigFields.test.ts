// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T20: form-level guardrails mirroring the T4 backend boundary — number inputs
// carry min/max, a warn>=crit misconfiguration shows an inline hint (nvme_spare
// excluded: lower is worse there), and the dead check_restarts checkbox is gone.

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorCheck, MonitorCheckConfig } from '$lib/api/types';
import { setLanguage, tNow } from '$lib/i18n';
import CheckConfigFields from './CheckConfigFields.svelte';

setLanguage('de');
afterEach(cleanup);

function inputFor(container: HTMLElement, label: string): HTMLInputElement {
  const fields = Array.from(container.querySelectorAll('label.field'));
  const match = fields.find((f) => f.textContent?.includes(label));
  if (!match) throw new Error(`no field labelled ${label}`);
  return match.querySelector('input') as HTMLInputElement;
}

describe('CheckConfigFields guardrails (T20)', () => {
  it('percent thresholds carry min/max mirroring the backend boundary', async () => {
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'agent_resources', config: {} as MonitorCheckConfig },
    });
    await tick();
    const cpuWarn = inputFor(container, 'CPU Warn');
    expect(cpuWarn.min).toBe('0');
    expect(cpuWarn.max).toBe('100');
    // hysteresis_pp is editable now (T6 introduced the key).
    expect(inputFor(container, 'Hysterese').max).toBe('50');
  });

  it('shows the warn>=crit hint only for genuinely inverted pairs', async () => {
    const bad = { cpu_warn: 95, cpu_crit: 90 } as MonitorCheckConfig;
    const { container, getByRole } = render(CheckConfigFields, {
      props: { checkType: 'agent_resources', config: bad },
    });
    await tick();
    expect(getByRole('note').textContent).toContain('CPU');
    expect(container.querySelectorAll('.cfg-hint').length).toBe(1);
  });

  it('nvme_spare warn>crit is NOT flagged (lower is worse there)', async () => {
    const spare = { nvme_spare_warn: 20, nvme_spare_crit: 10 } as MonitorCheckConfig;
    const { queryByRole } = render(CheckConfigFields, {
      props: { checkType: 'smart_health', config: spare },
    });
    await tick();
    expect(queryByRole('note')).toBeNull();
  });

  it('docker_health no longer renders the dead check_restarts checkbox', async () => {
    const config = {} as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'docker_health', config },
    });
    await tick();
    // The one checkbox left is the outage switch (R-0419), and it never writes
    // check_restarts.
    const boxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(boxes).toHaveLength(1);
    await fireEvent.click(boxes[0]);
    expect(config).toEqual({ alert_on_unavailable: false });
  });
});

// monitoring-silent-outages T11 (R-0419): a docker or zfs check the agent
// cannot read is a warning now, switchable per check, and the form had no
// switch. At the default the key must go: a template's check whose config
// carried {"alert_on_unavailable": true} would differ from the template's {}
// and count as changed by the user (mark_overrides).
// monitoring-linux-base-v2 T23 (R-0492): proxmox_backup has the same switch on
// the server since T14, so the form offers it there too.
describe('CheckConfigFields outage switch (R-0419)', () => {
  const TYPES = ['zfs_health', 'docker_health', 'proxmox_backup'] as const;

  async function outageBox(
    checkType: (typeof TYPES)[number],
    config: MonitorCheckConfig,
    label = 'Ausfall melden',
  ): Promise<HTMLInputElement> {
    const { container } = render(CheckConfigFields, { props: { checkType, config } });
    await tick();
    const input = inputFor(container, label);
    expect(input.type).toBe('checkbox');
    return input;
  }

  it.each(TYPES)('%s shows the switch, on by default, without writing it', async (type) => {
    const config = {} as MonitorCheckConfig;
    expect((await outageBox(type, config)).checked).toBe(true);
    expect(config).toEqual({});
  });

  it.each(TYPES)('%s writes false when switched off', async (type) => {
    const config = {} as MonitorCheckConfig;
    await fireEvent.click(await outageBox(type, config));
    expect(config).toEqual({ alert_on_unavailable: false });
  });

  it.each(TYPES)('%s drops the key instead of writing true when switched back on', async (type) => {
    const config = {} as MonitorCheckConfig;
    const box = await outageBox(type, config);
    await fireEvent.click(box);
    await fireEvent.click(box);
    expect(box.checked).toBe(true);
    expect(config).toEqual({});
  });

  it.each(TYPES)('%s shows a stored false as off and drops it when switched on', async (type) => {
    const config = { alert_on_unavailable: false } as MonitorCheckConfig;
    const box = await outageBox(type, config);
    expect(box.checked).toBe(false);
    await fireEvent.click(box);
    expect(config).toEqual({});
  });

  it('labels the switch in English', async () => {
    setLanguage('en');
    try {
      expect((await outageBox('docker_health', {}, 'Report outage')).checked).toBe(true);
    } finally {
      setLanguage('de');
    }
  });
});

// monitoring-services T7 (R-0418): the list mode now takes names with or
// without .service and aliases, ignore takes globs; the editor says so. A
// name entered twice gave SecServices a duplicate {#each} key.
describe('CheckConfigFields service_process (R-0418)', () => {
  function hints(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('.field-hint')).map(
      (h) => h.textContent?.trim() ?? '',
    );
  }

  it('shows the list hint in list mode and the glob hint in auto mode', async () => {
    const list = render(CheckConfigFields, {
      props: { checkType: 'service_process', config: { mode: 'list' } as MonitorCheckConfig },
    });
    await tick();
    const listHints = hints(list.container);
    expect(listHints).toHaveLength(1);
    expect(listHints[0]).toContain('.service');
    expect(listHints[0]).toContain('Aliase');
    expect(listHints[0]).not.toContain('foo@*');
    list.unmount();

    const auto = render(CheckConfigFields, {
      props: { checkType: 'service_process', config: { mode: 'auto' } as MonitorCheckConfig },
    });
    await tick();
    expect(hints(auto.container)).toEqual([expect.stringContaining('foo@*')]);
  });

  it('shows the hints in English', async () => {
    setLanguage('en');
    try {
      const list = render(CheckConfigFields, {
        props: { checkType: 'service_process', config: { mode: 'list' } as MonitorCheckConfig },
      });
      await tick();
      expect(hints(list.container)).toEqual([expect.stringContaining('aliases')]);
      list.unmount();

      const auto = render(CheckConfigFields, {
        props: { checkType: 'service_process', config: { mode: 'auto' } as MonitorCheckConfig },
      });
      await tick();
      expect(hints(auto.container)).toEqual([expect.stringContaining('Glob patterns')]);
    } finally {
      setLanguage('de');
    }
  });

  it('stores a name entered twice once', async () => {
    const config = { mode: 'list' } as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'service_process', config },
    });
    await tick();
    const input = inputFor(container, 'Dienste');
    await fireEvent.input(input, { target: { value: 'sshd, nginx, sshd , nginx' } });
    await fireEvent.change(input);
    expect(config.services).toEqual(['sshd', 'nginx']);
  });

  it('stores an ignore pattern entered twice once', async () => {
    const config = { mode: 'auto' } as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'service_process', config },
    });
    await tick();
    const input = inputFor(container, 'Ignorieren');
    await fireEvent.input(input, { target: { value: 'foo@*, bar.service, foo@*' } });
    await fireEvent.change(input);
    expect(config.ignore).toEqual(['foo@*', 'bar.service']);
  });

  // The field re-renders from config: dropping "nginx" from "nginx, nginx" per
  // keystroke would turn the typing of "nginx, nginx-exporter" into
  // "nginx-exporter". Only leaving the field (change) drops the repeat.
  it('keeps a repeat while typing and drops it on change', async () => {
    const config = { mode: 'list' } as MonitorCheckConfig;
    const { container } = render(CheckConfigFields, {
      props: { checkType: 'service_process', config },
    });
    await tick();
    const input = inputFor(container, 'Dienste');
    await fireEvent.input(input, { target: { value: 'nginx, nginx' } });
    expect(config.services).toEqual(['nginx', 'nginx']);
    await fireEvent.change(input);
    expect(config.services).toEqual(['nginx']);
  });
});

// monitoring-linux-base-v2 T18 (R-0423): agent_resources gained swap, inode
// and load thresholds, a minimum of free GB for the disk alarm and a list of
// ignored mounts (app/check_configs.py AgentResourcesConfig).
describe('CheckConfigFields agent_resources v2 (R-0423)', () => {
  function renderResources(config: MonitorCheckConfig) {
    return render(CheckConfigFields, { props: { checkType: 'agent_resources', config } });
  }

  it('renders the new thresholds with the backend bounds', async () => {
    const { container } = renderResources({} as MonitorCheckConfig);
    await tick();
    for (const label of ['Swap Warnung', 'Swap Kritisch', 'Inodes Warnung', 'Inodes Kritisch']) {
      const input = inputFor(container, label);
      expect([input.min, input.max, input.getAttribute('step')]).toEqual(['0', '100', null]);
    }
    for (const label of ['Last je CPU Warnung', 'Last je CPU Kritisch']) {
      const input = inputFor(container, label);
      expect([input.min, input.max, input.step]).toEqual(['0', '100', '0.1']);
    }
    const minFree = inputFor(container, 'Festplatte Alarm nur unter');
    expect([minFree.min, minFree.max, minFree.getAttribute('step')]).toEqual([
      '0',
      '1000000',
      null,
    ]);
    // The optional step leaves the existing fields at the browser default.
    expect(inputFor(container, 'CPU Warnung').getAttribute('step')).toBeNull();
  });

  it('stores a decimal load and 0 GB as numbers, an emptied field drops its key', async () => {
    const config = {} as MonitorCheckConfig;
    const { container } = renderResources(config);
    await tick();
    await fireEvent.input(inputFor(container, 'Last je CPU Warnung'), { target: { value: '1.5' } });
    // 0 turns the free-GB gate off; it is a value, not an empty field.
    await fireEvent.input(inputFor(container, 'Festplatte Alarm nur unter'), {
      target: { value: '0' },
    });
    await fireEvent.input(inputFor(container, 'Swap Warnung'), { target: { value: '70' } });
    expect(config).toEqual({ load_warn: 1.5, disk_min_free_gb: 0, swap_warn: 70 });
    await fireEvent.input(inputFor(container, 'Swap Warnung'), { target: { value: '' } });
    expect(config).toEqual({ load_warn: 1.5, disk_min_free_gb: 0 });
  });

  it('shows the warn>=crit hint for swap, inodes and load', async () => {
    const bad = {
      swap_warn: 95,
      swap_crit: 90,
      inode_warn: 90,
      inode_crit: 90,
      load_warn: 3,
      load_crit: 1.5,
    } as MonitorCheckConfig;
    const { getByRole } = renderResources(bad);
    await tick();
    const note = getByRole('note').textContent ?? '';
    for (const label of ['Swap', 'Inodes', 'Load']) expect(note).toContain(label);
  });

  it('shows no hint for the new pairs at sane values', async () => {
    const good = {
      swap_warn: 80,
      swap_crit: 95,
      inode_warn: 80,
      inode_crit: 90,
      load_warn: 1.5,
      load_crit: 3,
    } as MonitorCheckConfig;
    const { queryByRole } = renderResources(good);
    await tick();
    expect(queryByRole('note')).toBeNull();
  });

  it('stores ignore_mounts as a list and drops the key when emptied', async () => {
    const config = {} as MonitorCheckConfig;
    const { container } = renderResources(config);
    await tick();
    const input = inputFor(container, 'Mounts ignorieren');
    await fireEvent.input(input, { target: { value: '/boot/efi, /mnt/backup ,' } });
    expect(config.ignore_mounts).toEqual(['/boot/efi', '/mnt/backup']);
    await fireEvent.input(input, { target: { value: ' ' } });
    expect('ignore_mounts' in config).toBe(false);
  });

  it('shows stored ignore_mounts and the exact-path hint', async () => {
    const { container } = renderResources({
      ignore_mounts: ['/boot/efi', '/mnt/backup'],
    } as MonitorCheckConfig);
    await tick();
    expect(inputFor(container, 'Mounts ignorieren').value).toBe('/boot/efi, /mnt/backup');
    const hints = Array.from(container.querySelectorAll('.field-hint')).map((h) => h.textContent);
    expect(hints).toEqual([expect.stringContaining('Exakte Mount-Pfade')]);
  });

  it('labels the new fields in English', async () => {
    setLanguage('en');
    try {
      const { container } = renderResources({} as MonitorCheckConfig);
      await tick();
      for (const label of [
        'Swap warning (%)',
        'Swap critical (%)',
        'Inodes warning (%)',
        'Inodes critical (%)',
        'Load per CPU warning',
        'Load per CPU critical',
        'Disk alert only below (GB free, 0 = always)',
        'Ignore mounts',
      ]) {
        expect(inputFor(container, label)).toBeTruthy();
      }
      const hint = container.querySelector('.field-hint')?.textContent ?? '';
      expect(hint).toContain('Exact mount paths');
    } finally {
      setLanguage('de');
    }
  });
});

// monitoring-linux-base-v2 T20 (R-0423): system_state rates four points, each
// on unless switched off (SystemStateConfig). As with the outage switch, back
// at on the key goes, so a template's check keeps the template's config.
describe('CheckConfigFields system_state (R-0423)', () => {
  const SWITCHES = [
    ['Neustart nötig melden', 'check_reboot'],
    ['Nicht synchronisierte Uhr melden', 'check_time_sync'],
    ['Offene Sicherheits-Updates melden', 'check_security_updates'],
    ['OOM-Kills melden', 'check_oom'],
  ] as const;

  async function renderSystemState(config: MonitorCheckConfig) {
    const r = render(CheckConfigFields, { props: { checkType: 'system_state', config } });
    await tick();
    return r;
  }

  it('shows the four switches, on by default, without writing them', async () => {
    const config = {} as MonitorCheckConfig;
    const { container } = await renderSystemState(config);
    const boxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(boxes).toHaveLength(4);
    for (const [label] of SWITCHES) {
      const box = inputFor(container, label);
      expect(box.type).toBe('checkbox');
      expect(box.checked).toBe(true);
    }
    expect(config).toEqual({});
  });

  it.each(SWITCHES)('%s writes %s false when switched off', async (label, key) => {
    const config = {} as MonitorCheckConfig;
    const { container } = await renderSystemState(config);
    await fireEvent.click(inputFor(container, label));
    expect(config).toEqual({ [key]: false });
  });

  it.each(SWITCHES)(
    '%s shows a stored false as off and drops it when switched on',
    async (label, key) => {
      const config = { [key]: false } as MonitorCheckConfig;
      const { container } = await renderSystemState(config);
      const box = inputFor(container, label);
      expect(box.checked).toBe(false);
      await fireEvent.click(box);
      expect(box.checked).toBe(true);
      expect(config).toEqual({});
    },
  );

  it('labels the switches in English', async () => {
    setLanguage('en');
    try {
      const { container } = await renderSystemState({} as MonitorCheckConfig);
      for (const label of [
        'Report reboot required',
        'Report unsynchronized clock',
        'Report pending security updates',
        'Report OOM kills',
      ]) {
        expect(inputFor(container, label).checked).toBe(true);
      }
    } finally {
      setLanguage('de');
    }
  });
});

// R-1224 T11: a central check — the monitoring service probes a public endpoint
// itself. Sensor, host and port sit at the top of config, the sensor's own
// settings in config.params, the agent partner in config.pair_check_id.
describe('CheckConfigFields central (R-1224)', () => {
  function selectFor(container: HTMLElement, label: string): HTMLSelectElement {
    const fields = Array.from(container.querySelectorAll('label.field'));
    const match = fields.find((f) => f.textContent?.includes(label));
    if (!match) throw new Error(`no field labelled ${label}`);
    return match.querySelector('select') as HTMLSelectElement;
  }

  function labels(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('label.field .field-label')).map(
      (l) => l.textContent?.trim() ?? '',
    );
  }

  function probe(id: string, name: string, config: MonitorCheckConfig): MonitorCheck {
    return {
      id,
      name,
      serverId: 'srv-1',
      checkType: 'probe',
      interval: '5m',
      severity: 'warning',
      enabled: true,
      config,
    };
  }

  async function renderCentral(
    config: MonitorCheckConfig,
    extra: { serverChecks?: MonitorCheck[]; onSensorChange?: (s: string) => void } = {},
  ) {
    const r = render(CheckConfigFields, { props: { checkType: 'central', config, ...extra } });
    await tick();
    return r;
  }

  it('shows the port each sensor takes', async () => {
    const tls = await renderCentral({ sensor: 'tls', host: 'web.example', port: 443 });
    expect(inputFor(tls.container, 'Port').value).toBe('443');
    expect(tls.container.textContent).toContain(tNow('monitoring.checkCfg.tlsPortHint'));
    expect(tls.container.textContent).toContain(tNow('monitoring.checkCfg.hostPublic'));
    cleanup();

    const smtp = await renderCentral({ sensor: 'smtp', host: 'mail.example' });
    const port = selectFor(smtp.container, 'Port');
    expect(Array.from(port.options).map((o) => o.value)).toEqual(['25', '465', '587']);
    expect(port.value).toBe('25');
    cleanup();

    const dns = await renderCentral({ sensor: 'dns', host: 'example.org' });
    expect(labels(dns.container)).not.toContain('Port');
    expect(dns.container.textContent).toContain(tNow('monitoring.checkCfg.hostNameOnly'));
  });

  it('keeps the host on a sensor change and tells the parent', async () => {
    const config = {
      sensor: 'tls',
      host: 'mail.example',
      port: 8443,
      pair_check_id: 'p1',
    } as MonitorCheckConfig;
    let told = '';
    const { container } = await renderCentral(config, { onSensorChange: (s) => (told = s) });
    const sensor = selectFor(container, 'Fühler');
    sensor.value = 'smtp';
    await fireEvent.change(sensor);
    expect(config).toEqual({ sensor: 'smtp', host: 'mail.example', port: 25 });
    expect(told).toBe('smtp');
  });

  it('writes the expected addresses into params and drops them when emptied', async () => {
    const config = { sensor: 'dns', host: 'example.org' } as MonitorCheckConfig;
    const { container } = await renderCentral(config);
    const input = inputFor(container, 'Erwartete Adressen');
    await fireEvent.input(input, { target: { value: ' 192.0.2.1, ,2001:db8::1 ' } });
    expect(config.params).toEqual({ expected: ['192.0.2.1', '2001:db8::1'] });
    await fireEvent.input(input, { target: { value: ' ' } });
    expect('params' in config).toBe(false);
  });

  it('writes the rdap days as numbers and drops an emptied one', async () => {
    const config = { sensor: 'rdap', host: 'example.org' } as MonitorCheckConfig;
    const { container } = await renderCentral(config);
    await fireEvent.input(inputFor(container, 'Warnung ab'), { target: { value: '20' } });
    await fireEvent.input(inputFor(container, 'Kritisch ab'), { target: { value: '5' } });
    expect(config.params).toEqual({ warn_days: 20, crit_days: 5 });
    await fireEvent.input(inputFor(container, 'Warnung ab'), { target: { value: '' } });
    expect(config.params).toEqual({ crit_days: 5 });
  });

  it('stores the chosen lists in the table order, none chosen leaves the default', async () => {
    const config = { sensor: 'dnsbl', host: 'example.org' } as MonitorCheckConfig;
    const { container } = await renderCentral(config);
    const boxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(Array.from(boxes).map((b) => b.parentElement?.textContent?.trim())).toEqual([
      'PSBL',
      'SpamCop',
      'UCEPROTECT Level 1',
      'Spamhaus ZEN (DQS)',
    ]);
    expect(container.textContent).toContain(tNow('monitoring.checkCfg.dnsblListsHint'));
    await fireEvent.click(boxes[3]);
    await fireEvent.click(boxes[0]);
    expect(config.params).toEqual({ lists: ['psbl', 'spamhaus_zen'] });
    await fireEvent.click(boxes[3]);
    expect(config.params).toEqual({ lists: ['psbl'] });
    await fireEvent.click(boxes[0]);
    expect('params' in config).toBe(false);
  });

  it('offers the agent partners and keeps a stored one it does not know', async () => {
    const config = {
      sensor: 'tls',
      host: 'web.example',
      port: 443,
      pair_check_id: 'gone',
    } as MonitorCheckConfig;
    const serverChecks = [
      probe('p-tls', 'web tls', { sensor: 'tls' }),
      probe('p-file', 'cert file', { sensor: 'certfile', fields: ['not_after'] }),
      probe('p-load', 'load', { sensor: 'load' }),
    ];
    const { container } = await renderCentral(config, { serverChecks });
    const partner = selectFor(container, 'Agent-Partner');
    expect(Array.from(partner.options).map((o) => o.value)).toEqual([
      '',
      'gone',
      'p-tls',
      'p-file',
    ]);
    expect(partner.value).toBe('gone');
    partner.value = 'p-tls';
    await fireEvent.change(partner);
    expect(config.pair_check_id).toBe('p-tls');
    partner.value = '';
    await fireEvent.change(partner);
    expect('pair_check_id' in config).toBe(false);
  });

  it('offers no partner where the sensor takes none', async () => {
    for (const sensor of ['rdap', 'mail_dns', 'dnsbl']) {
      const { container } = await renderCentral({ sensor, host: 'example.org' });
      expect(labels(container)).not.toContain('Agent-Partner');
      cleanup();
    }
  });
});
