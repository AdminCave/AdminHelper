// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"slices"
	"time"
	"unicode/utf8"
)

// updatesTimeout caps a call of the security update count (apt-get, dnf, pkg audit). It runs once an
// hour and reads the whole package cache or vulnerability database, so it gets more than pluginTimeout.
const updatesTimeout = 30 * time.Second

// updatesCheckEvery spaces the counts: dnf loads all metadata on each call, and a pending security
// update is no five-minute matter.
const updatesCheckEvery = time.Hour

// updatesLeftOut ends the warning of a failed count: the field stays out until the next one.
const updatesLeftOut = "security_updates left out until the next hourly count"

// updatesCalls indirects the clock of the hourly count and its calls so tests can drive the cache and
// every outcome without the tools (same reason as cpuCalls). run runs one call under timeout
// and ctx with env added to the agent's environment.
var updatesCalls = struct {
	now func() time.Time
	run func(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error)
}{time.Now, runTimedEnv}

// updatesDue reports whether a new count is due at now: none is saved, the saved one is an hour old or
// older, or it is from the future (the clock was set back), or counting would stop until the clock
// caught up.
func updatesDue(saved *updatesCheck, now time.Time) bool {
	if saved == nil {
		return true
	}
	age := now.Sub(time.Unix(saved.CheckedUnix, 0))
	return age < 0 || age >= updatesCheckEvery
}

// maxPackageNames caps the names of a count or of a pending reboot and maxPackageNameBytes each name:
// they go out with every report, and the count says how many there are.
const (
	maxPackageNames     = 100
	maxPackageNameBytes = 128
)

// packageNames returns names as a report carries them: each cut to maxPackageNameBytes on a rune
// boundary, sorted, each once, the first maxPackageNames; nil for none.
func packageNames(names []string) []string {
	if len(names) == 0 {
		return nil
	}
	capped := make([]string, len(names))
	for i, name := range names {
		capped[i] = capPackageName(name)
	}
	slices.Sort(capped)
	capped = slices.Compact(capped)
	return capped[:min(len(capped), maxPackageNames)]
}

// capPackageName cuts name to maxPackageNameBytes without splitting a rune.
func capPackageName(name string) string {
	if len(name) <= maxPackageNameBytes {
		return name
	}
	cut := maxPackageNameBytes
	for cut > 0 && !utf8.RuneStart(name[cut]) {
		cut--
	}
	return name[:cut]
}

// putSecurityUpdates sets security_updates and, when it names any, security_packages in block from a
// count that succeeded.
func putSecurityUpdates(block map[string]any, check *updatesCheck) {
	if check == nil || check.Security == nil {
		return
	}
	block["security_updates"] = *check.Security
	if len(check.Packages) > 0 {
		block["security_packages"] = check.Packages
	}
}
