// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"testing"
	"time"

	"golang.org/x/sys/windows"
)

func TestFileTimeReadsTheEpochAndTheYear9999(t *testing.T) {
	ticks := func(t time.Time) windows.Filetime {
		n := uint64(t.Unix()+11644473600)*10_000_000 + uint64(t.Nanosecond()/100)
		return windows.Filetime{LowDateTime: uint32(n), HighDateTime: uint32(n >> 32)}
	}
	for _, want := range []time.Time{
		time.Unix(0, 0).UTC(),
		time.Date(2026, 11, 14, 12, 30, 15, 700, time.UTC),
		time.Date(9999, 12, 31, 23, 59, 59, 0, time.UTC),
	} {
		if got := fileTime(ticks(want)); !got.Equal(want) {
			t.Errorf("fileTime = %v, want %v", got, want)
		}
	}
}
