// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import "testing"

func TestParseArcstats(t *testing.T) {
	const kstat = `13 1 0x01 123 33456 1234567 7654321
name                            type data
hits                            4    1000
c                               4    8589934592
c_min                           4    1073741824
c_max                           4    17179869184
size                            4    6442450944
`
	if got, want := parseArcstats([]byte(kstat)), uint64(6442450944-1073741824); got != want {
		t.Fatalf("parseArcstats = %d, want %d", got, want)
	}
	for name, text := range map[string]string{
		"empty":         "",
		"no c_min":      "size 4 100\n",
		"below the min": "c_min 4 200\nsize 4 100\n",
		"not a number":  "c_min 4 x\nsize 4 100\n",
	} {
		if got := parseArcstats([]byte(text)); got != 0 {
			t.Errorf("%s: parseArcstats = %d, want 0", name, got)
		}
	}
}
