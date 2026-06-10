// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import "testing"

func TestHasPrefix(t *testing.T) {
	prefixes := []string{"/sys", "/proc", "/dev/", "/run/snapd", "/snap"}

	cases := []struct {
		mount string
		want  bool
	}{
		{"/sys", true},
		{"/sys/kernel/debug", true},
		{"/proc/sys/fs", true},
		{"/dev/shm", true},
		{"/snap", true},
		{"/run/snapd/ns", true},
		{"/", false},
		{"/data", false},
		{"/home", false},
		// "/dev/" has the trailing slash so the /dev mountpoint itself passes.
		{"/dev", false},
		{"/run", false},
		{"", false},
	}
	for _, c := range cases {
		if got := hasPrefix(c.mount, prefixes); got != c.want {
			t.Errorf("hasPrefix(%q) = %v, erwartet %v", c.mount, got, c.want)
		}
	}
}

func TestHasPrefixEmptyList(t *testing.T) {
	if hasPrefix("/anything", nil) {
		t.Error("hasPrefix mit leerer Prefix-Liste muss false liefern")
	}
}
