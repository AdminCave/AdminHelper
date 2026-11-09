// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"path"
	"regexp"
	"sort"
	"strings"
)

// The FreeBSD service collectors live here without a build tag, so they are tested on any platform
// with a fake service(8); services_freebsd.go only wires them to the real one.

// rcRun runs service(8) with args.
type rcRun func(ctx context.Context, args ...string) ([]byte, error)

// reRCScriptName matches a name `service <name>` may be given. service(8) runs "$dir/<name>" for
// /etc/rc.d and each local_startup directory, so a "/" would leave the directory, "." or ".." would
// name the directory itself, and a leading "-" would be one of its options.
var reRCScriptName = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._-]*$`)

// The two answers of rc.subr's status for a script that sets command or procname (rc.subr,
// releng/14.3 and 15.0): "${name} is running as pid $rc_pid." with every pid found, and
// "${name} is not running." ${name} is the script's name=, which may differ from its file name.
var (
	reRCRunning    = regexp.MustCompile(`^\S+ is running as pid ([0-9]+)(?: [0-9]+)*\.$`)
	reRCNotRunning = regexp.MustCompile(`^\S+ is not running\.$`)
)

// reRCNothingToStop matches the stop_cmd=":" of a script whose start runs once and leaves no process
// behind (newsyslog, ntpdate, ddb in base): rc.subr's status calls it not running, by design.
var reRCNothingToStop = regexp.MustCompile(`(?m)^[ \t]*stop_cmd=(?:":"|':'|:)[ \t]*(?:#.*)?$`)

// rcScript is an enabled rc.d script: the name service(8) takes and the file `service -e` listed.
type rcScript struct{ name, file string }

// parseRCStatus reads the output of `service <name> status`: active with the first pid, or inactive.
// ok is false for any other output, from a script without a status of its own (rc.subr then prints
// "unknown directive" to stderr) or one whose status_cmd prints something else. The first line of
// either form decides.
func parseRCStatus(out []byte) (state, pid string, ok bool) {
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if m := reRCRunning.FindStringSubmatch(line); m != nil {
			return "active", m[1], true
		}
		if reRCNotRunning.MatchString(line) {
			return "inactive", "", true
		}
	}
	return "", "", false
}

// parseRCEnabled reads the output of `service -e`, the full paths of the enabled rc.d scripts, into
// the scripts sorted by name. A line that is no absolute path or whose base name service(8) would not
// take is left out. A name listed twice keeps its file in /etc/rc.d, which service(8) looks in first.
func parseRCEnabled(out []byte) []rcScript {
	files := map[string]string{}
	for _, line := range strings.Split(string(out), "\n") {
		file := strings.TrimSpace(line)
		name := path.Base(file)
		if !strings.HasPrefix(file, "/") || !reRCScriptName.MatchString(name) {
			continue
		}
		if _, seen := files[name]; !seen || path.Dir(file) == "/etc/rc.d" {
			files[name] = file
		}
	}
	scripts := make([]rcScript, 0, len(files))
	for name, file := range files {
		scripts = append(scripts, rcScript{name, file})
	}
	// Sorted, so an aborted run and the server's cap on the inventory always keep the same scripts.
	sort.Slice(scripts, func(i, j int) bool { return scripts[i].name < scripts[j].name })
	return scripts
}

// rcServiceHealth builds the service-health block in the format of the systemd block from service(8):
// `service -e` lists the enabled scripts and `service <name> status` asks each. all_services holds
// the scripts whose status parseRCStatus reads, all enabled; enabled_inactive those inactive unless
// their file says there is nothing to stop (reRCNothingToStop; a file it cannot read stays). failed
// stays empty: rc(8) keeps no failed state. A failed `service -e`, or a status call that did not
// answer (it hung or was killed), sets error and leaves the counts out; after the latter no script is
// asked further, since each such call waits pluginTimeout.
func rcServiceHealth(ctx context.Context, run rcRun, readFile func(string) ([]byte, error)) map[string]any {
	result := map[string]any{
		"failed":           []string{},
		"enabled_inactive": []string{},
		"all_services":     []ServiceEntry{},
	}
	out, err := run(ctx, "-e")
	if err != nil {
		result["error"] = "service -e failed: " + commandFailure("service", pluginTimeout, err)
		return result
	}
	services, enabledInactive := []ServiceEntry{}, []string{}
	for _, s := range parseRCEnabled(out) {
		out, err := run(ctx, s.name, "status")
		if err != nil && !answered(err) {
			result["error"] = "service " + s.name + " status failed: " +
				commandFailure("service", pluginTimeout, err)
			break
		}
		state, _, ok := parseRCStatus(out)
		if !ok {
			continue
		}
		services = append(services, ServiceEntry{"unit": s.name, "active_state": state, "enabled_state": "enabled"})
		if state == "inactive" {
			if script, err := readFile(s.file); err == nil && reRCNothingToStop.Match(script) {
				continue
			}
			enabledInactive = append(enabledInactive, s.name)
		}
	}
	result["all_services"] = services
	result["enabled_inactive"] = enabledInactive
	if _, failed := result["error"]; !failed {
		result["counts"] = serviceCounts(services)
	}
	return result
}

// rcWatchedServices asks `service <name> status` for each watched name, in the entry form of the other
// platforms. A name service(8) would not take, an output parseRCStatus cannot read and a failed call
// are not running; after a call that did not answer no name is asked further.
func rcWatchedServices(ctx context.Context, run rcRun, names []string) []map[string]any {
	services := make([]map[string]any, 0, len(names))
	asking := true
	for _, name := range names {
		svc := map[string]any{"name": name, "running": false, "pid": nil}
		if asking && reRCScriptName.MatchString(name) {
			out, err := run(ctx, name, "status")
			if err == nil || answered(err) {
				if state, pid, ok := parseRCStatus(out); ok && state == "active" {
					svc["running"] = true
					svc["pid"] = pid
				}
			} else {
				asking = false
			}
		}
		services = append(services, svc)
	}
	return services
}
