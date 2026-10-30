// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"time"
)

// updatesTimeout caps the apt-get and dnf call of the security update count. It runs once an hour
// and reads the whole package cache, so it gets more than pluginTimeout.
const updatesTimeout = 30 * time.Second

// updatesCheckEvery spaces the counts: dnf loads all metadata on each call, and a pending security
// update is no five-minute matter.
const updatesCheckEvery = time.Hour

// updatesLeftOut ends the warning of a failed count: the field stays out until the next one.
const updatesLeftOut = "security_updates left out until the next hourly count"

// updatesCalls indirects the clock of the hourly count and its calls so tests can drive the cache and
// every outcome without apt-get or dnf (same reason as cpuCalls). run runs one call under timeout
// and ctx with env added to the agent's environment.
var updatesCalls = struct {
	now func() time.Time
	run func(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error)
}{time.Now, runTimedEnv}

// runTimedEnv is runTimed with env added to the environment; a later entry of the same key wins
// (os/exec), so the agent's own LC_ALL is overridden.
func runTimedEnv(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = append(os.Environ(), env...)
	cmd.WaitDelay = commandWaitDelay
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrWaitDelay) {
		return out, nil
	}
	if err != nil && ctx.Err() != nil {
		return out, ctx.Err()
	}
	return out, err
}

// securityUpdates returns the count to report and to save: saved while it is younger than an hour,
// else a new count from the local package cache, never the network (apt-get -s, dnf -C). A count
// that failed is saved without a number, so the field stays out until the next hourly count instead
// of the tool running on every report. A host with neither apt-get nor dnf has nothing to count and
// gets nil, which is no failure and stays out of the log. A count that ctx ended fails like one that
// timed out.
func securityUpdates(ctx context.Context, saved *updatesCheck) *updatesCheck {
	now := updatesCalls.now()
	if saved != nil {
		// A count from the future (the clock was set back) is due as well, or counting would stop until
		// the clock caught up.
		if age := now.Sub(time.Unix(saved.CheckedUnix, 0)); age >= 0 && age < updatesCheckEvery {
			return saved
		}
	}
	var count int
	var ok bool
	if _, err := systemCLI.lookPath("apt-get"); err == nil {
		count, ok = aptSecurityUpdates(ctx)
	} else if _, err := systemCLI.lookPath("dnf"); err == nil {
		count, ok = dnfSecurityUpdates(ctx)
	} else {
		return nil
	}
	check := &updatesCheck{CheckedUnix: now.Unix()}
	if ok {
		check.Security = &count
	}
	return check
}

// aptSecurityUpdates counts the security updates a simulated dist-upgrade would install. -s needs no
// lock (apt-get(8)); LC_ALL=C runs it untranslated, the form countAptSecurity reads.
func aptSecurityUpdates(ctx context.Context) (int, bool) {
	out, err := updatesCalls.run(ctx, updatesTimeout, []string{"LC_ALL=C"}, "apt-get", "-s", "dist-upgrade")
	if err != nil {
		logger.Warnf("system state: apt-get -s dist-upgrade failed: %s, %s",
			commandFailure("apt-get", updatesTimeout, err), updatesLeftOut)
		return 0, false
	}
	return countAptSecurity(out), true
}

// dnfSecurityUpdates counts the packages with a security advisory in dnf's cache; -C keeps dnf to the
// cache, off the network. It keeps the agent's locale: countDNFSecurity reads no translated word, and
// a translation that splits a column makes the output unreadable, not the count wrong.
func dnfSecurityUpdates(ctx context.Context) (int, bool) {
	out, err := updatesCalls.run(ctx, updatesTimeout, nil, "dnf", "-C", "-q", "updateinfo", "list", "--security")
	if err != nil {
		logger.Warnf("system state: dnf updateinfo list --security failed: %s, %s",
			commandFailure("dnf", updatesTimeout, err), updatesLeftOut)
		return 0, false
	}
	count, ok := countDNFSecurity(out)
	if !ok {
		logger.Warnf("system state: unexpected output of dnf updateinfo list --security, %s", updatesLeftOut)
	}
	return count, ok
}

// countAptSecurity counts the Inst lines of apt-get -s whose origin names security, without regard to
// case: "Inst <pkg> [<old>] (<new> <origin>[, <origin>…] [<arch>])", the origin as Debian
// "Debian-Security:12/stable-security" or Ubuntu "Ubuntu:24.04/noble-security". apt-get(8) does not
// document this form, so only the parenthesis after the new version is read: a package or version
// that merely carries the word does not count. Conf and Remv lines are no updates of their own.
func countAptSecurity(out []byte) int {
	count := 0
	for _, line := range strings.Split(string(out), "\n") {
		if !strings.HasPrefix(line, "Inst ") {
			continue
		}
		_, paren, ok := strings.Cut(line, "(")
		if !ok {
			continue
		}
		paren, _, _ = strings.Cut(paren, ")")
		_, origins, _ := strings.Cut(paren, " ")
		if strings.Contains(strings.ToLower(origins), "security") {
			count++
		}
	}
	return count
}

// countDNFSecurity counts the packages in dnf updateinfo list --security, one advisory and package per
// line: "<advisory> <severity>/Sec. <name>-[<epoch>:]<version>-<release>.<arch>". A package that
// several advisories fix, also in several newer versions, counts once, as its one Inst line does in
// apt. The output is not documented (dnf5 prints other columns): a line of another form makes the
// whole output unreadable rather than the count too small.
func countDNFSecurity(out []byte) (int, bool) {
	names := map[string]bool{}
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		if len(fields) != 3 {
			return 0, false
		}
		name, ok := rpmPackageName(fields[2])
		if !ok {
			return 0, false
		}
		names[name] = true
	}
	return len(names), true
}

// rpmPackageName cuts version, release and arch off a package's NEVRA: the name ends at the last but
// one "-", since neither version nor release holds one.
func rpmPackageName(nevra string) (string, bool) {
	release := strings.LastIndex(nevra, "-")
	if release <= 0 {
		return "", false
	}
	version := strings.LastIndex(nevra[:release], "-")
	if version <= 0 {
		return "", false
	}
	return nevra[:version], true
}
