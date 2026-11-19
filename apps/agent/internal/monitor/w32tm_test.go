// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import "testing"

func TestParseW32tmStatus(t *testing.T) {
	const synced = "Leap Indicator: 0(no warning)\r\n" +
		"Stratum: 4 (secondary reference - syncd by (S)NTP)\r\n" +
		"Precision: -23 (119.209ns per tick)\r\n" +
		"Root Delay: 0.0312500s\r\n" +
		"Root Dispersion: 7.8159282s\r\n" +
		"ReferenceId: 0xC0000201 (source IP:  192.0.2.1)\r\n" +
		"Last Successful Sync Time: 11/18/2026 2:11:05 PM\r\n" +
		"Source: dc01.example.test\r\n" +
		"Poll Interval: 10 (1024s)\r\n"
	const leap3 = "Leap Indicator: 3(not synchronized)\r\n" +
		"Stratum: 0 (unspecified)\r\n" +
		"Source: dc01.example.test\r\n"
	const cmos = "Leap Indicator: 0(no warning)\r\n" +
		"Stratum: 1 (primary reference - syncd by radio clock)\r\n" +
		"Source: Local CMOS Clock\r\n"
	const freeRunning = "Leap Indicator: 0(no warning)\r\n" +
		"Stratum: 1 (primary reference - syncd by radio clock)\r\n" +
		"Source: Free-running System Clock\r\n"
	// Another display language: labels translated, the leap indicator read by place and value.
	const translated = "\r\nSprungindikator: 0(keine Warnung)\r\nStratum: 3\r\nQuelle: dc01.example.test\r\n"
	cases := []struct {
		name         string
		out          string
		synced, isOK bool
	}{
		{"synchronized", synced, true, true},
		{"leap indicator 3", leap3, false, true},
		{"local CMOS clock", cmos, false, true},
		{"free-running clock", freeRunning, false, true},
		{"translated labels", translated, true, true},
		{"empty", "", false, false},
		{"error text", "The following error occurred: The service has not been started. (0x80070426)\r\n", false, false},
		{"no leap value", "Leap Indicator:\r\nSource: x\r\n", false, false},
		{"leap out of range", "Leap Indicator: 7(?)\r\n", false, false},
	}
	for _, c := range cases {
		synced, ok := parseW32tmStatus([]byte(c.out))
		if synced != c.synced || ok != c.isOK {
			t.Errorf("%s: parseW32tmStatus = %v, %v, want %v, %v", c.name, synced, ok, c.synced, c.isOK)
		}
	}
}
