// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"

	"adminhelper-agent/internal/execx"
)

// errCommandNotAllowed is the error of a call runTimedEnv refused: the command or its arguments are not
// on commandAllowlist, so it never started.
var errCommandNotAllowed = errors.New("not on the command allowlist")

// argClasses are the variable parts a call may carry, each a whole argument or a part of one
// (`<node>` in a pvesh path). None may begin with '-', so none can pass for an option.
var argClasses = map[string]string{
	// A Proxmox node name: a hostname label (the short name collectProxmox cuts from the hostname).
	"node": `[A-Za-z0-9][A-Za-z0-9-]*`,
	// A Proxmox storage ID (pve-storage: a letter, then letters, digits, '-', '_', '.').
	"storage": `[A-Za-z][A-Za-z0-9._-]*`,
	// A device path from smartctl --scan, below /dev; no segment begins with '.', so no "..".
	"device": `/dev(/[A-Za-z0-9_,-][A-Za-z0-9_.,-]*)+`,
	// A smartctl device type from the scan (sat, nvme, megaraid,N, sat,12 …).
	"devtype": `[a-z0-9][a-z0-9_,+]*`,
	// A systemd unit name (systemd.unit(5): letters, digits, ":-_.\", '@' for instances).
	"unit": `[A-Za-z0-9:_.@\\][A-Za-z0-9:_.@\\-]*`,
	// A container ID as docker ps prints it: 12 hex digits, 64 untruncated.
	"container": `[0-9a-f]{12,64}`,
	// A Windows service name, the class collectWatchedServices lets through (reWinServiceName).
	"winservice": `[A-Za-z0-9._$][A-Za-z0-9._$-]*`,
}

// commandAllowlist is every call the collectors may start: per command its argument lists, a literal
// argument as written, `<class>` for a variable part from argClasses, and `<class>...` as the last
// argument for one or more of them. Collectors only read; a new call needs its entry here, and
// allowlist_test.go checks every current call against it. Kept out on purpose (Konzept §3.6): calls
// that write, repair or touch the network, such as `apt-get check`, `zpool scrub`, `postfix check`,
// `docker exec` and the storage list `pvesh get /nodes/<n>/storage`, which activates every storage.
var commandAllowlist = map[string][][]string{
	"docker": {
		{"info"},
		{"ps", "-a", "--format", "{{json .}}"},
		{"inspect", "--type", "container", "<container>..."},
	},
	"pvesh": {
		{"get", "/nodes/<node>/status", "--output-format", "json"},
		{"get", "/cluster/resources", "--type", "vm", "--output-format", "json"},
		{"get", "/cluster/resources", "--type", "storage", "--output-format", "json"},
		{"get", "/nodes/<node>/storage/<storage>/content", "--content", "backup", "--output-format", "json"},
	},
	"zpool": {
		{"list", "-H", "-o", "name,size,alloc,free,cap,health"},
		{"status", "-x"},
	},
	"smartctl": {
		{"--scan", "--json=c"},
		{"--all", "--json=c", "<device>"},
		{"--all", "--json=c", "-d", "<devtype>", "<device>"},
	},
	"systemctl": {
		{"list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"},
		{"list-unit-files", "--type=service", "--no-legend", "--no-pager"},
		{"list-units", "--state=failed", "--no-legend", "--plain"},
		{"show", "-p", "Id,Names", "--", "<unit>..."},
		{"show", "-p", "Id,Names,ActiveState,MainPID", "--", "<unit>..."},
		{"show", "-p", "Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic", "--", "<unit>..."},
	},
	"sc": {
		{"query", "state=", "all"},
		{"query", "<winservice>"},
		{"queryex", "<winservice>"},
	},
	"needs-restarting": {{"-r"}},
	"timedatectl":      {{"show"}},
	"apt-get":          {{"-s", "dist-upgrade"}},
	"dnf":              {{"-C", "-q", "updateinfo", "list", "--security"}},
}

// allowedCall is one argument list of commandAllowlist, compiled: one pattern per argument, the last
// one repeated when variadic.
type allowedCall struct {
	args     []*regexp.Regexp
	variadic bool
}

var (
	allowedCalls = compileAllowlist(commandAllowlist)
	reArgClass   = regexp.MustCompile(`<([a-z]+)>`)
)

// compileAllowlist turns the table into anchored patterns; an unknown class is a programming error.
func compileAllowlist(list map[string][][]string) map[string][]allowedCall {
	compiled := make(map[string][]allowedCall, len(list))
	for name, calls := range list {
		for _, call := range calls {
			var c allowedCall
			for i, arg := range call {
				if i == len(call)-1 && strings.HasSuffix(arg, "...") {
					arg, c.variadic = strings.TrimSuffix(arg, "..."), true
				}
				c.args = append(c.args, regexp.MustCompile("^"+argPattern(arg)+"$"))
			}
			compiled[name] = append(compiled[name], c)
		}
	}
	return compiled
}

// argPattern quotes the literal parts of one argument and replaces each `<class>` by its pattern.
func argPattern(arg string) string {
	var b strings.Builder
	last := 0
	for _, m := range reArgClass.FindAllStringSubmatchIndex(arg, -1) {
		class, ok := argClasses[arg[m[2]:m[3]]]
		if !ok {
			panic("monitor: unknown argument class in commandAllowlist: " + arg)
		}
		b.WriteString(regexp.QuoteMeta(arg[last:m[0]]) + "(?:" + class + ")")
		last = m[1]
	}
	b.WriteString(regexp.QuoteMeta(arg[last:]))
	return b.String()
}

// commandAllowed reports whether name with args is on commandAllowlist, by commandKey(name).
func commandAllowed(name string, args []string) bool {
	for _, call := range allowedCalls[commandKey(name, runtime.GOOS == "windows")] {
		if call.matches(args) {
			return true
		}
	}
	return false
}

// commandKey is the allowlist key of name. An absolute name counts by its base name: smartctl runs by
// the path exec.LookPath found, which on Windows ends in ".exe" (PATHEXT), so there the extension goes
// too, in any case.
func commandKey(name string, windows bool) string {
	if filepath.IsAbs(name) {
		name = filepath.Base(name)
	}
	if windows && strings.EqualFold(filepath.Ext(name), ".exe") {
		name = name[:len(name)-len(".exe")]
	}
	return name
}

func (c allowedCall) matches(args []string) bool {
	if len(args) < len(c.args) || (!c.variadic && len(args) != len(c.args)) {
		return false
	}
	for i, arg := range args {
		pattern := c.args[min(i, len(c.args)-1)]
		if !pattern.MatchString(arg) {
			return false
		}
	}
	return true
}

// commandWaitDelay bounds how long runTimed waits for a command's pipes (execx.WaitDelay).
const commandWaitDelay = execx.WaitDelay

// runTimed runs a command under timeout and ctx, whichever ends first; see runTimedEnv.
func runTimed(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
	return runTimedEnv(ctx, timeout, nil, name, args...)
}

// runTimedEnv is the one place the collectors start a command. A call off commandAllowlist does not
// start and returns errCommandNotAllowed. env is added to the agent's environment; a later entry of
// the same key wins (os/exec), so the agent's own LC_ALL is overridden.
func runTimedEnv(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	if !commandAllowed(name, args) {
		logger.Warnf("monitor: %s call refused, %s", filepath.Base(name), errCommandNotAllowed)
		return nil, fmt.Errorf("%s: %w", filepath.Base(name), errCommandNotAllowed)
	}
	return execTimed(ctx, timeout, env, name, args...)
}

// execTimed runs a command without the allowlist check, through execx.RunEnv (its errors there; a
// call its own timeout ended counts for the self-throttle); only runTimedEnv and the tests of the
// timeout handling call it.
func execTimed(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	return execx.RunEnv(ctx, timeout, env, name, args...)
}
