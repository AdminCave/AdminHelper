// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"fmt"
	"io/fs"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// The FreeBSD service collectors live here without a build tag, so they are tested on any platform
// with a fake service(8); services_freebsd.go only wires them to the real one.

// rcRun runs service(8) with args.
type rcRun func(ctx context.Context, args ...string) ([]byte, error)

// reRCScriptName matches a name `service <name>` may be given. service(8) runs "$dir/<name>" for
// /etc/rc.d and each local_startup directory, so a "/" would leave the directory, "." or ".." would
// name the directory itself, and a leading "-" would be one of its options.
var reRCScriptName = regexp.MustCompile("^(?:" + argClasses["rcscript"] + ")$")

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
func rcServiceHealth(ctx context.Context, run rcRun, readFile func(string) ([]byte, error)) *ServiceHealth {
	scripts, result := rcEnabled(ctx, run)
	if result.Error != "" {
		return result
	}
	return rcStatus(ctx, run, readFile, scripts, result)
}

// rcEnabled lists the enabled scripts with `service -e`, and returns the block rcStatus fills: on a
// failed call it carries the error.
func rcEnabled(ctx context.Context, run rcRun) ([]rcScript, *ServiceHealth) {
	result := &ServiceHealth{Failed: []string{}, EnabledInactive: []string{}, AllServices: []ServiceEntry{}}
	out, err := run(ctx, "-e")
	if err != nil {
		result.Error = "service -e failed: " + commandFailure("service", pluginTimeout, err)
		return nil, result
	}
	return parseRCEnabled(out), result
}

// rcStatus asks `service <name> status` for each of scripts and fills result (rcServiceHealth).
func rcStatus(ctx context.Context, run rcRun, readFile func(string) ([]byte, error), scripts []rcScript, result *ServiceHealth) *ServiceHealth {
	services, enabledInactive := []ServiceEntry{}, []string{}
	for _, s := range scripts {
		out, err := run(ctx, s.name, "status")
		if err != nil && !answered(err) {
			result.Error = "service " + s.name + " status failed: " +
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
	result.AllServices = services
	result.EnabledInactive = enabledInactive
	if result.Error == "" {
		result.Counts = serviceCounts(services)
	}
	return result
}

// rcServicesEvery spaces the status calls of the service-health block: on FreeBSD they are one
// process per enabled script, about 2 CPU seconds a run on a small host (R-1706). The watched
// services are asked every run all the same.
const rcServicesEvery = 15 * time.Minute

// rcConfPaths are the files and directories `service -e` reads whether a script is enabled
// (rc.subr's load_rc_config) and where it finds the scripts (/etc/rc.d, local_startup).
var rcConfPaths = []string{
	"/etc/defaults/rc.conf", "/etc/rc.conf", "/etc/rc.conf.local", "/etc/rc.conf.d",
	"/usr/local/etc/rc.conf.d", "/etc/rc.d", "/usr/local/etc/rc.d",
}

// serviceCache is the last service-health block of a FreeBSD host, kept in the report state: Health as
// read at CheckedUnix, and Enabled, the script files `service -e` listed while the rc.conf files bore
// Stamp (rcConfStamp).
type serviceCache struct {
	CheckedUnix int64          `json:"checked_unix"`
	Stamp       string         `json:"stamp"`
	Enabled     []string       `json:"enabled"`
	Health      *ServiceHealth `json:"health"`
}

// rcConfStamp is what changes when a script is enabled, disabled, installed or removed: path, mtime
// and size of every entry under paths. A missing path counts as one value of its own.
func rcConfStamp(paths []string) string {
	var b strings.Builder
	for _, root := range paths {
		err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				fmt.Fprintf(&b, "%s:-\n", p)
				return nil
			}
			info, err := d.Info()
			if err != nil {
				fmt.Fprintf(&b, "%s:-\n", p)
				return nil
			}
			fmt.Fprintf(&b, "%s:%d:%d\n", p, info.ModTime().UnixNano(), info.Size())
			return nil
		})
		if err != nil {
			fmt.Fprintf(&b, "%s:-\n", root)
		}
	}
	return b.String()
}

// rcServiceHealthCached is rcServiceHealth against saved, the cache the last run left: younger than
// rcServicesEvery its block comes back without a call; older, the status calls run again, over its
// list of scripts while stamp still gives its Stamp. It returns the cache to keep, nil after a
// failed `service -e` or a status call that did not answer, so the next run asks again.
func rcServiceHealthCached(ctx context.Context, run rcRun, readFile func(string) ([]byte, error),
	stamp func() string, saved *serviceCache, now time.Time) (*ServiceHealth, *serviceCache) {
	if saved != nil && saved.Health != nil {
		if age := now.Sub(time.Unix(saved.CheckedUnix, 0)); age >= 0 && age < rcServicesEvery {
			health := *saved.Health
			return &health, saved
		}
	}
	st := stamp()
	var scripts []rcScript
	result := &ServiceHealth{Failed: []string{}, EnabledInactive: []string{}, AllServices: []ServiceEntry{}}
	if saved != nil && saved.Enabled != nil && saved.Stamp == st {
		for _, file := range saved.Enabled {
			scripts = append(scripts, rcScript{path.Base(file), file})
		}
	} else if scripts, result = rcEnabled(ctx, run); result.Error != "" {
		return result, nil
	}
	result = rcStatus(ctx, run, readFile, scripts, result)
	if result.Error != "" {
		return result, nil
	}
	enabled := make([]string, 0, len(scripts))
	for _, s := range scripts {
		enabled = append(enabled, s.file)
	}
	// A copy: the report adds the watched services and the service logs to the block it sends.
	kept := *result
	return result, &serviceCache{CheckedUnix: now.Unix(), Stamp: st, Enabled: enabled, Health: &kept}
}

// rcWatchedServices asks `service <name> status` for each watched name, in the entry form of the other
// platforms. A name service(8) would not take, an output parseRCStatus cannot read and a failed call
// are not running; after a call that did not answer no name is asked further.
func rcWatchedServices(ctx context.Context, run rcRun, names []string) []WatchedService {
	services := make([]WatchedService, 0, len(names))
	asking := true
	for _, name := range names {
		svc := WatchedService{Name: name}
		if asking && reRCScriptName.MatchString(name) {
			out, err := run(ctx, name, "status")
			if err == nil || answered(err) {
				if state, pid, ok := parseRCStatus(out); ok && state == "active" {
					svc.Running = true
					svc.PID = &pid
				}
			} else {
				asking = false
			}
		}
		services = append(services, svc)
	}
	return services
}
