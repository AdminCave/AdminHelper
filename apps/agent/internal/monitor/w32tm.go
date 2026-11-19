// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"strings"
)

// unsyncedSources are the Source values of `w32tm /query /status` for a clock that follows no time
// source; w32tm prints them untranslated.
var unsyncedSources = []string{"Local CMOS Clock", "Free-running System Clock"}

// parseW32tmStatus reads whether the Windows Time service has synchronized the clock from the output
// of `w32tm /query /status`: the first line is the leap indicator ("Leap Indicator: 0(no warning)"),
// whose 3 means "not synchronized", and a Source of the local clock means the same. The labels are
// translated on other display languages, so the leap indicator is read by its place and its value
// (digit and parenthesis), not by its label; this is verified for English output only. ok is false
// when the first line carries no leap indicator.
func parseW32tmStatus(out []byte) (synced, ok bool) {
	var lines []string
	for _, line := range strings.Split(string(out), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			lines = append(lines, line)
		}
	}
	if len(lines) == 0 {
		return false, false
	}
	_, value, found := strings.Cut(lines[0], ":")
	value = strings.TrimSpace(value)
	if !found || len(value) < 2 || value[0] < '0' || value[0] > '3' || strings.TrimSpace(value[1:])[0] != '(' {
		return false, false
	}
	if value[0] == '3' {
		return false, true
	}
	for _, line := range lines[1:] {
		_, value, found := strings.Cut(line, ":")
		if !found {
			continue
		}
		for _, src := range unsyncedSources {
			if strings.TrimSpace(value) == src {
				return false, true
			}
		}
	}
	return true, true
}
