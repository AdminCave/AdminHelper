// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"context"
	"errors"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

// The FreeBSD system state tools, by their full paths: freebsd-version is part of the base system;
// pkg is the one from the ports, as periodic's 405.pkg-base-audit calls it, not the bootstrap
// /usr/sbin/pkg, which offers to install it.
const (
	freebsdVersionPath = "/bin/freebsd-version"
	pkgPath            = "/usr/local/sbin/pkg"
)

// freebsdCalls indirects the lookup and the calls of the FreeBSD system state tools so tests can
// drive every path without them, on any system (same reason as systemCLI). run runs one call under
// timeout and ctx. The clock of the hourly count is updatesCalls.now, as on Linux.
var freebsdCalls = struct {
	lookPath func(file string) (string, error)
	run      func(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error)
}{exec.LookPath, runTimed}

// reFreeBSDVersion is one line of freebsd-version: the characters its pattern for the kernel's
// version takes (KERNEL_RE in bin/freebsd-version/freebsd-version.sh.in), as in "15.0-RELEASE-p3".
var reFreeBSDVersion = regexp.MustCompile(`^[-.0-9A-Za-z]+$`)

// reFreeBSDRelease is a release with or without a patch level, the only versions the VuXML entries of
// the base system name; a STABLE, CURRENT, BETA or RC has none to match.
var reFreeBSDRelease = regexp.MustCompile(`^[0-9]+\.[0-9]+-RELEASE(-p[0-9]+)?$`)

// freebsdVersions are the lines of freebsd-version: kernel the installed kernel (-k), running the
// running one (-r), userland the base system (-u). In a jail only userland is read: the kernel is
// the host's.
type freebsdVersions struct {
	kernel, running, userland string
}

// freebsdSystemState reports the system_state block of a FreeBSD system and returns st with the
// hourly count replaced. reboot_required compares the installed kernel with the running one, outside
// a jail only; security_updates is pkgSecurityUpdates. A field is set only when measured; why one is
// missing goes to the log. ctx ends its tool calls.
func freebsdSystemState(ctx context.Context, st reportState) (map[string]any, reportState) {
	block := map[string]any{}
	jailed := inContainer()
	versions, why := readFreeBSDVersions(ctx, jailed)
	if !jailed {
		if why != "" {
			logger.Warnf("system state: %s, reboot_required left out", why)
		} else {
			block["reboot_required"] = versions.kernel != versions.running
		}
	}
	st.Updates = pkgSecurityUpdates(ctx, st.Updates, versions, why)
	if st.Updates != nil && st.Updates.Security != nil {
		block["security_updates"] = *st.Updates.Security
	}
	return block, st
}

// readFreeBSDVersions runs freebsd-version once, with -kru on a host and -u in a jail, and returns
// its lines, or why it could not read them. freebsd-version prints one line per flag in the order
// k, r, u; a missing kernel version prints none (bin/freebsd-version), so a line too few is
// unreadable rather than shifted.
func readFreeBSDVersions(ctx context.Context, jailed bool) (freebsdVersions, string) {
	flags, lines := "-kru", 3
	if jailed {
		flags, lines = "-u", 1
	}
	out, err := freebsdCalls.run(ctx, pluginTimeout, freebsdVersionPath, flags)
	if err != nil {
		return freebsdVersions{}, "freebsd-version " + flags + " failed: " +
			commandFailure("freebsd-version", pluginTimeout, err)
	}
	got := strings.Split(strings.TrimSuffix(string(out), "\n"), "\n")
	if len(got) != lines {
		return freebsdVersions{}, "unexpected output of freebsd-version " + flags
	}
	for _, line := range got {
		if !reFreeBSDVersion.MatchString(line) {
			return freebsdVersions{}, "unexpected output of freebsd-version " + flags
		}
	}
	if jailed {
		return freebsdVersions{userland: got[0]}, ""
	}
	return freebsdVersions{kernel: got[0], running: got[1], userland: got[2]}, ""
}

// pkgSecurityUpdates returns the count to report and to save, hourly like securityUpdates on Linux:
// the installed packages pkg audit finds vulnerable, plus the base system and, outside a jail, the
// installed kernel of a release, matched as periodic's 405.pkg-base-audit matches them. pkg audit
// reads the local vuln.xml, which periodic's daily security run fetches; the agent never fetches it
// (-F). Without pkg there is nothing to count (nil). A failed part, or versions it could not read
// (why), saves the attempt without a number, as a failed count on Linux does.
func pkgSecurityUpdates(ctx context.Context, saved *updatesCheck, versions freebsdVersions, why string) *updatesCheck {
	now := updatesCalls.now()
	if !updatesDue(saved, now) {
		return saved
	}
	if _, err := freebsdCalls.lookPath(pkgPath); err != nil {
		return nil
	}
	check := &updatesCheck{CheckedUnix: now.Unix()}
	if why != "" {
		logger.Warnf("system state: %s, %s", why, updatesLeftOut)
		return check
	}
	count, ok := pkgAudit(ctx, "pkg audit -q")
	if !ok {
		return check
	}
	if names := freebsdBaseNames(versions); len(names) > 0 {
		// Without names pkg audit would audit the installed packages again.
		base, ok := pkgAudit(ctx, "pkg audit -q of the base system", names...)
		if !ok {
			return check
		}
		count += base
	}
	check.Security = &count
	return check
}

// freebsdBaseNames are the base system's names for pkg audit: FreeBSD-<userland> and, outside a jail,
// FreeBSD-kernel-<installed kernel>, each only for a release. A STABLE or CURRENT has no VuXML
// entry, so its part counts nothing rather than failing the count.
func freebsdBaseNames(versions freebsdVersions) []string {
	var names []string
	if reFreeBSDRelease.MatchString(versions.userland) {
		names = append(names, freebsdPkgName("FreeBSD-", versions.userland))
	}
	if reFreeBSDRelease.MatchString(versions.kernel) {
		names = append(names, freebsdPkgName("FreeBSD-kernel-", versions.kernel))
	}
	return names
}

// freebsdPkgName turns a release into the package name and version pkg audit matches the VuXML
// entries of the base system with, as 405.pkg-base-audit does with sed: "15.0-RELEASE-p3" becomes
// prefix+"15.0_3", "15.0-RELEASE" prefix+"15.0".
func freebsdPkgName(prefix, release string) string {
	return prefix + strings.TrimSuffix(strings.Replace(release, "-RELEASE-p", "_", 1), "-RELEASE")
}

// pkgAudit runs pkg audit -q with args and counts the vulnerable packages, or logs why it could not
// (what names the call). pkg audit exits 1 both for vulnerable packages and for an error, the missing
// vuln.xml included; with -q only a vulnerable package prints a line, and every error stops before
// one (pkg src/audit.c). So exit 1 with lines counts, exit 1 without fails. Its exit status is not
// documented (pkg-audit(8)).
func pkgAudit(ctx context.Context, what string, args ...string) (int, bool) {
	out, err := freebsdCalls.run(ctx, updatesTimeout, pkgPath, append([]string{"audit", "-q"}, args...)...)
	var exitErr *exec.ExitError
	found := errors.As(err, &exitErr) && exitErr.ExitCode() == 1 && len(bytes.TrimSpace(out)) > 0
	if err != nil && !found {
		logger.Warnf("system state: %s failed: %s, %s", what, commandFailure("pkg", updatesTimeout, err), updatesLeftOut)
		return 0, false
	}
	count, ok := countPkgAudit(out)
	if !ok {
		logger.Warnf("system state: unexpected output of %s, %s", what, updatesLeftOut)
	}
	return count, ok
}

// rePkgAuditLine is a line of pkg audit -q: name and version, the version after the last "-".
var rePkgAuditLine = regexp.MustCompile(`^\S+-[^-\s]+$`)

// countPkgAudit counts the lines of pkg audit -q, one "<name>-<version>" per vulnerable package
// (pkg src/audit.c), each package once. A line of another form makes the whole output unreadable
// rather than the count too small.
func countPkgAudit(out []byte) (int, bool) {
	count := 0
	for _, line := range strings.Split(string(out), "\n") {
		if line == "" {
			continue
		}
		if !rePkgAuditLine.MatchString(line) {
			return 0, false
		}
		count++
	}
	return count, true
}
