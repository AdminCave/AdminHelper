// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"os"
	"reflect"
	"slices"
	"strings"
	"testing"
)

// rcScriptPath is the rc.d script the FreeBSD package installs as /usr/local/etc/rc.d/adminhelper_frpc.
const rcScriptPath = "../../freebsd/adminhelper_frpc"

// rcScriptFrpcConfig is config.FrpConfigFile() on FreeBSD (paths_freebsd.go); the test of
// platform_freebsd.go compares the two there.
const rcScriptFrpcConfig = "/usr/local/etc/adminhelper/frp/frpc.toml"

func readRCScript(t *testing.T) []string {
	t.Helper()
	data, err := os.ReadFile(rcScriptPath)
	if err != nil {
		t.Fatal(err)
	}
	// A Windows checkout may turn the line ends into CRLF.
	return strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
}

// rcorderBlock reads the lines as rcorder(8) does (crunch_file): it skips the lines before the
// first "# PROVIDE:", "# REQUIRE:", "# BEFORE:" or "# KEYWORD:" line and stops at the first
// other line after it, so a keyword below that line is lost.
func rcorderBlock(lines []string) map[string][]string {
	block := map[string][]string{}
	parsing := false
	for _, line := range lines {
		matched := false
		for _, kw := range []string{"PROVIDE", "REQUIRE", "BEFORE", "KEYWORD"} {
			if rest, ok := strings.CutPrefix(line, "# "+kw+":"); ok {
				block[kw] = append(block[kw], strings.Fields(rest)...)
				matched = true
			}
		}
		if !matched && parsing {
			break
		}
		parsing = parsing || matched
	}
	return block
}

// rcAssignments returns the script's top-level name="value" lines.
func rcAssignments(lines []string) map[string]string {
	vars := map[string]string{}
	for _, line := range lines {
		name, value, ok := strings.Cut(line, "=")
		if !ok || name == "" || strings.ContainsAny(name, " \t:${#") {
			continue
		}
		vars[name] = strings.Trim(value, `"`)
	}
	return vars
}

// daemonCommandLine splits daemon(8)'s arguments as its getopt_long does with FreeBSD 14.3's
// shortopts (15.0 only adds C:): options up to the first other word, which is the program; the
// rest are the program's arguments.
func daemonCommandLine(t *testing.T, args []string) (opts map[string]string, program string, programArgs []string) {
	t.Helper()
	const withArgument, without = "pPuosltmRT", "cfHSrh"
	opts = map[string]string{}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if !strings.HasPrefix(a, "-") || a == "-" {
			return opts, a, args[i+1:]
		}
		if len(a) != 2 {
			t.Fatalf("daemon option %q: the test reads single options only", a)
		}
		switch o := a[1:]; {
		case strings.Contains(without, o):
			opts[o] = ""
		case strings.Contains(withArgument, o) && i+1 < len(args):
			opts[o] = args[i+1]
			i++
		default:
			t.Fatalf("daemon has no option %q or it lacks its argument", a)
		}
	}
	t.Fatal("daemon's arguments name no program")
	return nil, "", nil
}

func TestRCScriptOrdersAsAService(t *testing.T) {
	block := rcorderBlock(readRCScript(t))
	if !reflect.DeepEqual(block["PROVIDE"], []string{rcName}) {
		t.Errorf("PROVIDE = %q, want %q", block["PROVIDE"], rcName)
	}
	// frpc needs the network and logs to syslog; LOGIN comes after both.
	if !slices.Contains(block["REQUIRE"], "LOGIN") {
		t.Errorf("REQUIRE = %q, want LOGIN", block["REQUIRE"])
	}
	// shutdown: rc.shutdown stops the service, so frpc ends before the network does.
	if !slices.Contains(block["KEYWORD"], "shutdown") {
		t.Errorf("KEYWORD = %q, want shutdown", block["KEYWORD"])
	}
}

func TestRCScriptRunsFrpcUnderDaemon(t *testing.T) {
	lines := readRCScript(t)
	vars := rcAssignments(lines)
	for name, want := range map[string]string{
		"name":           rcName,
		"rcvar":          rcName + "_enable",
		"command":        "/usr/sbin/daemon",
		"required_files": rcScriptFrpcConfig,
	} {
		if vars[name] != want {
			t.Errorf("%s = %q, want %q", name, vars[name], want)
		}
	}
	// rc.subr matches the pidfile's process against procname, which defaults to command: daemon,
	// which the pidfile holds. procname=frpc would never match it.
	if _, ok := vars["procname"]; ok {
		t.Error("the script sets procname; status would never find the daemon")
	}

	opts, program, programArgs := daemonCommandLine(t, strings.Fields(vars["command_args"]))
	for opt, want := range map[string]string{
		"f": "",                 // daemon lets go of the caller's stdout and stderr
		"r": "",                 // restarts frpc when it exits
		"R": "5",                // five seconds later
		"P": vars["pidfile"],    // the pid rc.subr stops and checks: the daemon's
		"p": rcChildPidFile,     // frpc's pid, empty while daemon waits to restart it (frpcDown)
		"S": "",                 // frpc's output to syslog
		"T": "adminhelper-frpc", // under this tag
	} {
		got, ok := opts[opt]
		if !ok || got != want {
			t.Errorf("daemon -%s: got %q (set %v), want %q", opt, got, ok, want)
		}
	}
	if vars["pidfile"] == "" {
		t.Error("the script sets no pidfile; stop and status would not find the daemon")
	}
	if extra := len(opts) - 7; extra != 0 {
		t.Errorf("daemon has %d options beyond the tested ones: %q", extra, opts)
	}
	if program != rcFrpcBinary {
		t.Errorf("daemon runs %q, want %q", program, rcFrpcBinary)
	}
	if want := []string{"-c", rcScriptFrpcConfig}; !reflect.DeepEqual(programArgs, want) {
		t.Errorf("frpc arguments = %q, want %q", programArgs, want)
	}
}

func TestRCScriptLoadsItsConfigAndRunsTheCommand(t *testing.T) {
	lines := readRCScript(t)
	// In this order: rc.subr, then rc.conf (load_rc_config), then the default for an unset rcvar,
	// then the command; the service is off until the agent enables it.
	want := []string{
		". /etc/rc.subr",
		"load_rc_config $name",
		`: ${` + rcName + `_enable:="NO"}`,
		`run_rc_command "$1"`,
	}
	var got []string
	for _, line := range lines {
		if slices.Contains(want, line) {
			got = append(got, line)
		}
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("the script has %q, want each of %q once and in this order", got, want)
	}
	last := len(lines) - 1
	for last > 0 && strings.TrimSpace(lines[last]) == "" {
		last--
	}
	if lines[last] != want[len(want)-1] {
		t.Errorf("last line = %q, want %q", lines[last], want[len(want)-1])
	}
	if lines[0] != "#!/bin/sh" {
		t.Errorf("first line = %q, want #!/bin/sh", lines[0])
	}
}
