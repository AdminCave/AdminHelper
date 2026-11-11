// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package allowlist

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"
)

const cursor = "s=0123456789abcdef0123456789abcdef;i=1a2b;b=fedcba9876543210fedcba9876543210;m=3c4d;t=5e6f;x=7a8b"

// TestAllowlistTakesEveryProbeAndDiscoveryCall runs the calls of the sensors (probe) and of discovery
// through the list, with the variable parts in the forms they come in; the collectors' calls are
// monitor's test, and the stubs of probe and discovery check every call their tests make.
func TestAllowlistTakesEveryProbeAndDiscoveryCall(t *testing.T) {
	head := []string{"journalctl", "--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor"}
	journal := func(rest ...string) []string { return append(append([]string{}, head...), rest...) }
	calls := [][]string{
		journal("--priority=3", "--since=-60s"),
		journal("--priority=0", "--after-cursor="+cursor),
		journal("--priority=7", "--unit=nginx.service", "--since=-300s"),
		journal("--priority=3", "--unit=getty@tty1.service", "--after-cursor="+cursor, "--", "_COMM=sshd"),
		journal("--priority=4", "--since=-60s", "--", "SYSLOG_IDENTIFIER=postfix/smtpd"),
		journal("--priority=4", "--unit=-.slice", "--since=-60s", "--", "CONTAINER_NAME=web-1"),
		{"systemctl", "show", "-p", "LoadState,ActiveState,SubState,NRestarts,ActiveEnterTimestampMonotonic", "--", "nginx.service"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "-.slice"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", `systemd-fsck@dev-disk-by\x2duuid-1a2b.service`},
		{"docker", "inspect", "--type", "container", "--", "web_1.prod"},
		{"docker", "inspect", "--type", "container", "--", "0123456789ab"},
		{"systemctl", "list-units", "--type=service", "--all", "--full", "--no-legend", "--plain", "--no-pager"},
		{"docker", "ps", "--all", "--quiet", "--no-trunc"},
		{"docker", "inspect", "--type", "container", strings.Repeat("a", 64), strings.Repeat("0", 64)},
		{"dpkg-query", "--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--", "nginx", "libc6", "g++-12"},
		{"rpm", "--query", `--queryformat=%{NAME}\n`, "nginx", "postgresql16-server"},
	}
	for _, args := range mariadbCalls {
		calls = append(calls, append([]string{"mariadb"}, args...), append([]string{"mysql"}, args...))
	}
	for _, args := range postgresCalls {
		calls = append(calls, append([]string{"runuser"}, args...))
	}
	for _, call := range calls {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	if len(journalCalls) != 8 || len(mariadbCalls) != 4 || len(postgresCalls) != 4 {
		t.Errorf("%d journalctl, %d MariaDB, %d PostgreSQL calls; want 8, 4, 4",
			len(journalCalls), len(mariadbCalls), len(postgresCalls))
	}
}

// TestAllowlistRefusesTheProbeAndDiscoveryTraps is the negative test: calls that bend an allowed one
// of the sensors or of discovery into another output, another user, another query or an option.
func TestAllowlistRefusesTheProbeAndDiscoveryTraps(t *testing.T) {
	head := []string{"journalctl", "--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor"}
	journal := func(rest ...string) []string { return append(append([]string{}, head...), rest...) }
	sql := mariadbCalls[0]
	pg := postgresCalls[0]
	calls := [][]string{
		{"journalctl", "--no-pager", "--quiet", "--output=json", "--show-cursor", "--priority=3", "--since=-60s"},
		journal("--priority=3"),
		journal("--priority=8", "--since=-60s"),
		journal("--priority=3", "--since=-60s", "--", "MESSAGE=password"),
		journal("--priority=3", "--since=-60s", "--", "--help"),
		journal("--priority=3", "--since=-60s", "_COMM=sshd"),
		journal("--priority=3", "--after-cursor=x y"),
		journal("--priority=3", "--unit=*", "--since=-60s"),
		journal("--priority=3", "--since=-60s", "--file=/etc/shadow"),
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "--help"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "nginx"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "a", "b"},
		{"systemctl", "show", "-p", "LoadState,ExecStart", "--", "nginx"},
		{"docker", "inspect", "--type", "container", "--", "-f"},
		{"docker", "inspect", "--type", "container", "--", "../x"},
		{"docker", "inspect", "--type", "container", "web"},
		{"docker", "ps", "--all", "--quiet"},
		{"dpkg-query", "--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--"},
		{"dpkg-query", "--show", `--showformat=${Conffiles}\n`, "--", "nginx"},
		{"dpkg-query", "--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--", "-x"},
		{"rpm", "--query", `--queryformat=%{NAME}\n`, "-e"},
		{"rpm", "--query", `--queryformat=%{NAME}\n`, "--", "nginx"},
		{"rpm", "--erase", "nginx"},
		append([]string{"mariadb"}, append(append([]string{}, sql[:len(sql)-1]...), "--execute=SELECT * FROM mysql.user")...),
		append([]string{"mysql"}, append(append([]string{}, sql...), "--user=root")...),
		append([]string{"runuser"}, append(append([]string{}, pg[:len(pg)-1]...), "--command=SELECT * FROM pg_authid")...),
		append([]string{"runuser", "-u", "root"}, pg[2:]...),
		{"psql", "--command=SELECT 1"},
		{"sh", "-c", "true"},
	}
	for _, call := range calls {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestNoClassTakesAnOption: no class matches an argument that begins with '-', but unitarg, which takes
// "-" only for the root units and stands right after "--" or behind a literal option.
func TestNoClassTakesAnOption(t *testing.T) {
	for name, class := range Classes() {
		re := regexp.MustCompile("^(?:" + class + ")$")
		for _, arg := range []string{"-", "-x", "--help", "-1", "-.", "-.slice/x", "-x.slice"} {
			if re.MatchString(arg) {
				t.Errorf("class %s takes %q", name, arg)
			}
		}
	}
	unitarg := regexp.MustCompile("^(?:" + classes["unitarg"] + ")$")
	for _, arg := range []string{"-.slice", "-.mount"} {
		if !unitarg.MatchString(arg) {
			t.Errorf("unitarg refuses the root unit %q", arg)
		}
	}
	for _, entries := range commands {
		for _, args := range entries {
			for i, arg := range args {
				if strings.HasPrefix(arg, "<unitarg>") && (arg != "<unitarg>" || i == 0 || args[i-1] != "--") {
					t.Errorf("entry %q has <unitarg> neither right after \"--\" nor behind an option", args)
				}
			}
		}
	}
}

// TestRunRefusesACallOffTheList: a refused call does not start, and its error is ErrNotAllowed.
func TestRunRefusesACallOffTheList(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("starts a shell script")
	}
	marker := filepath.Join(t.TempDir(), "started")
	out, err := Run(context.Background(), time.Minute, "sh", "-c", "touch "+marker)
	if out != nil || !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("Run = %q, %v; want no output and ErrNotAllowed", out, err)
	}
	if _, err := os.Stat(marker); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("the refused call started: %v", err)
	}
}

// TestRunStartsAnAllowedCall is the counter-check: an allowed call does start. The command is a script
// named timedatectl, by its absolute path, which counts by its base name.
func TestRunStartsAnAllowedCall(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("starts a shell script")
	}
	tool := filepath.Join(t.TempDir(), "timedatectl")
	if err := os.WriteFile(tool, []byte("#!/bin/sh\necho \"ran $1\"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	out, err := Run(context.Background(), time.Minute, tool, "show")
	if err != nil || string(out) != "ran show\n" {
		t.Errorf("Run = %q, %v; want the script's output", out, err)
	}
}

// TestClassesIsACopy: what a caller does to the map Classes returns does not change the list.
func TestClassesIsACopy(t *testing.T) {
	c := Classes()
	c["unit"] = ".*"
	if Classes()["unit"] == ".*" {
		t.Error("Classes returned the list's own map")
	}
}
