// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"testing"
	"time"
)

type wmiRowOS struct {
	NumberOfProcesses  uint32
	FreePhysicalMemory uint64
	hidden             int
}

func TestAWMIQueryAsksForTheFieldsOfItsStruct(t *testing.T) {
	var rows []wmiRowOS
	cases := []struct {
		name string
		q    wmiQuery
		dst  any
		want string
	}{
		{"plain", wmiQuery{namespace: `root\cimv2`, class: "Win32_OperatingSystem"}, &rows,
			"SELECT NumberOfProcesses, FreePhysicalMemory FROM Win32_OperatingSystem"},
		{"where", wmiQuery{namespace: `root\Microsoft\Windows\Storage`, class: "MSFT_PhysicalDisk", where: "HealthStatus <> 0"},
			&rows, "SELECT NumberOfProcesses, FreePhysicalMemory FROM MSFT_PhysicalDisk WHERE HealthStatus <> 0"},
		{"quoted", wmiQuery{namespace: `root\cimv2`, class: "Win32_Service", where: "Name = 'NTDS'"}, &rows,
			"SELECT NumberOfProcesses, FreePhysicalMemory FROM Win32_Service WHERE Name = 'NTDS'"},
	}
	for _, c := range cases {
		got, err := c.q.wql(c.dst)
		if err != nil || got != c.want {
			t.Errorf("%s: wql() = %q, %v; want %q", c.name, got, err, c.want)
		}
	}
}

func TestAWMIQueryRefusesWhatIsNoFixedRead(t *testing.T) {
	var rows []wmiRowOS
	var empty []struct{ hidden int }
	ok := wmiQuery{namespace: `root\cimv2`, class: "Win32_OperatingSystem"}
	cases := []struct {
		name string
		q    wmiQuery
		dst  any
	}{
		{"namespace outside root", wmiQuery{namespace: `cimv2`, class: ok.class}, &rows},
		{"namespace too deep", wmiQuery{namespace: `root\a\b\c\d\e`, class: ok.class}, &rows},
		{"namespace of another host", wmiQuery{namespace: `\\host\root\cimv2`, class: ok.class}, &rows},
		{"class with a statement", wmiQuery{namespace: ok.namespace, class: "Win32_Service; DROP"}, &rows},
		{"class with a dot", wmiQuery{namespace: ok.namespace, class: "Win32_Process.Handle"}, &rows},
		{"where with a call", wmiQuery{namespace: ok.namespace, class: ok.class, where: "Name = Terminate()"}, &rows},
		{"where with an open quote", wmiQuery{namespace: ok.namespace, class: ok.class, where: "Name = 'x"}, &rows},
		{"where with a second statement", wmiQuery{namespace: ok.namespace, class: ok.class, where: "1=1; SELECT"}, &rows},
		{"no pointer", ok, rows},
		{"pointer to no slice", ok, &wmiRowOS{}},
		{"slice of no struct", ok, &[]string{}},
		{"nil", ok, nil},
		{"no exported field", ok, &empty},
	}
	for _, c := range cases {
		if got, err := c.q.wql(c.dst); err == nil {
			t.Errorf("%s: wql() = %q, want an error", c.name, got)
		}
	}
}

func TestAnEventQueryFiltersOnSystemValuesOnly(t *testing.T) {
	cases := []struct {
		name string
		q    eventQuery
		want string
	}{
		{"all", eventQuery{channel: "System"}, "*"},
		{"levels and window", eventQuery{channel: "System", levels: []uint8{1, 2}, within: 15 * time.Minute},
			"*[System[(Level=1 or Level=2) and TimeCreated[timediff(@SystemTime) <= 900000]]]"},
		{"source and ids", eventQuery{channel: "Microsoft-Windows-Backup", provider: "Microsoft-Windows-Backup", ids: []uint16{4, 5}},
			"*[System[Provider[@Name='Microsoft-Windows-Backup'] and (EventID=4 or EventID=5)]]"},
		{"channel with a blank", eventQuery{channel: "Veeam Agent", ids: []uint16{190}}, "*[System[(EventID=190)]]"},
	}
	for _, c := range cases {
		got, err := c.q.xpath()
		if err != nil || got != c.want {
			t.Errorf("%s: xpath() = %q, %v; want %q", c.name, got, err, c.want)
		}
	}
}

func TestAnEventQueryRefusesWhatCouldLeaveTheFilter(t *testing.T) {
	cases := []struct {
		name string
		q    eventQuery
	}{
		{"no channel", eventQuery{}},
		{"quote in the channel", eventQuery{channel: "System'"}},
		{"quote in the provider", eventQuery{channel: "System", provider: "x'] or [@Name='y"}},
		{"bracket in the provider", eventQuery{channel: "System", provider: "x]"}},
		{"level out of range", eventQuery{channel: "System", levels: []uint8{9}}},
		{"negative window", eventQuery{channel: "System", within: -time.Second}},
	}
	for _, c := range cases {
		if got, err := c.q.xpath(); err == nil {
			t.Errorf("%s: xpath() = %q, want an error", c.name, got)
		}
	}
}
