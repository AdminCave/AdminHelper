// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"testing"
)

// The golden files of these tests were written by hand, since only the Windows CI job runs them.

func TestReportGoldenSystemStateWindows(t *testing.T) {
	stubW32tm(t, "Leap Indicator: 3(not synchronized)\r\nSource: Local CMOS Clock\r\n", nil)
	block, _ := collectSystemState(context.Background(), reportState{})
	checkGolden(t, "system_state_windows", wireValue(t, block))

	stubW32tm(t, "", errors.New("exit status 1"))
	block, _ = collectSystemState(context.Background(), reportState{})
	checkGolden(t, "system_state_windows_failed", wireValue(t, block))
}

// Names sc is never asked for: the watched list's form without this host's services.
func TestReportGoldenWatchedWindows(t *testing.T) {
	checkGolden(t, "services_windows",
		wireValue(t, collectWatchedServices(context.Background(), []string{"bad name", "a;b"})))
}
