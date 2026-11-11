// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestOnlyAllowlistStartsCommands parses every non-test file of the packages that start tools, this
// one, probe and discovery, whatever its build tag, and fails on a start of a command outside the
// allowlist: exec.Command, exec.CommandContext, os.StartProcess, execx.Run, execx.RunEnv, or a call of
// execTimed, which skips the allowlist check. Only this package's allowlist.go may: execTimed is there.
// The least number of files per package is its counter-check: a glob that found few would pass.
func TestOnlyAllowlistStartsCommands(t *testing.T) {
	for _, pkg := range []struct {
		dir   string
		least int
	}{{".", 10}, {"../probe", 15}, {"../discovery", 3}} {
		files, err := filepath.Glob(filepath.Join(pkg.dir, "*.go"))
		if err != nil || len(files) == 0 {
			t.Fatalf("no Go files found in %s: %v", pkg.dir, err)
		}
		checked := 0
		for _, file := range files {
			if strings.HasSuffix(file, "_test.go") || file == "allowlist.go" {
				continue
			}
			checked++
			for _, call := range commandStarts(t, file) {
				t.Errorf("%s starts a command outside the allowlist: %s", file, call)
			}
		}
		if checked < pkg.least {
			t.Fatalf("checked %d files in %s, want the whole package", checked, pkg.dir)
		}
	}
}

// commandStarts lists the command starts in file (see TestOnlyAllowlistStartsCommands) as
// "line: call".
func commandStarts(t *testing.T, file string) []string {
	t.Helper()
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, file, nil, parser.SkipObjectResolution)
	if err != nil {
		t.Fatalf("parse %s: %v", file, err)
	}
	names := map[string]string{} // local import name -> import path
	for _, imp := range f.Imports {
		path, _ := strconv.Unquote(imp.Path.Value)
		name := filepath.Base(path)
		if imp.Name != nil {
			name = imp.Name.Name
		}
		names[name] = path
	}
	forbidden := map[string]bool{
		"os/exec.Command": true, "os/exec.CommandContext": true, "os.StartProcess": true,
		"adminhelper-agent/internal/execx.Run": true, "adminhelper-agent/internal/execx.RunEnv": true,
	}
	var found []string
	ast.Inspect(f, func(n ast.Node) bool {
		switch e := n.(type) {
		case *ast.SelectorExpr:
			if pkg, ok := e.X.(*ast.Ident); ok && forbidden[names[pkg.Name]+"."+e.Sel.Name] {
				found = append(found, fmt.Sprintf("%d: %s.%s", fset.Position(e.Pos()).Line, pkg.Name, e.Sel.Name))
			}
		case *ast.Ident:
			if e.Name == "execTimed" {
				found = append(found, fmt.Sprintf("%d: execTimed", fset.Position(e.Pos()).Line))
			}
		}
		return true
	})
	return found
}

// TestCommandStartsSeesAStart is the counter-check of the AST test: a file that starts a command,
// under an alias, through execx and through execTimed, is found.
func TestCommandStartsSeesAStart(t *testing.T) {
	file := filepath.Join(t.TempDir(), "start.go")
	src := "package monitor\n\nimport (\n\tx \"os/exec\"\n\t\"os\"\n\t\"adminhelper-agent/internal/execx\"\n)\n\n" +
		"func a() { _ = x.Command(\"true\") }\n" +
		"func b() { _, _ = os.StartProcess(\"true\", nil, nil) }\n" +
		"func c() { _, _ = execTimed(nil, 0, nil, \"true\") }\n" +
		"func d() { _, _ = execx.Run(nil, 0, \"true\") }\n" +
		"func e() { _, _ = execx.RunEnv(nil, 0, nil, \"true\") }\n"
	if err := os.WriteFile(file, []byte(src), 0o600); err != nil {
		t.Fatal(err)
	}
	got := commandStarts(t, file)
	want := []string{"9: x.Command", "10: os.StartProcess", "11: execTimed", "12: execx.Run", "13: execx.RunEnv"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Errorf("found %q, want %q", got, want)
	}
}

// TestAllowlistTakesEveryCollectorCall runs every call the collectors make today through the list,
// with the variable parts in the forms they come in.
func TestAllowlistTakesEveryCollectorCall(t *testing.T) {
	// smartctl runs by the absolute path exec.LookPath found: an absolute path of this platform.
	smartctl := filepath.Join(t.TempDir(), "smartctl")
	calls := [][]string{
		{smartctl, "--scan", "--json=c"},
		{smartctl, "--all", "--json=c", "-d", "nvme", "/dev/nvme0"},
		{"docker", "info"},
		{"docker", "ps", "-a", "--format", "{{json .}}"},
		{"docker", "inspect", "--type", "container", "0123456789ab"},
		{"docker", "inspect", "--type", "container", "0123456789ab", strings.Repeat("f", 64)},
		{"pvesh", "get", "/nodes/pve1/status", "--output-format", "json"},
		{"pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"},
		{"pvesh", "get", "/cluster/resources", "--type", "storage", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve-01/storage/local/content", "--content", "backup", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/storage/pbs_back.up-2/content", "--content", "backup", "--output-format", "json"},
		{"zpool", "list", "-H", "-o", "name,size,alloc,free,cap,health"},
		{"zpool", "status", "-x"},
		{"smartctl", "--scan", "--json=c"},
		{"smartctl", "--all", "--json=c", "/dev/sda"},
		{"smartctl", "--all", "--json=c", "-d", "nvme", "/dev/nvme0"},
		{"smartctl", "--all", "--json=c", "-d", "megaraid,0", "/dev/bus/0"},
		{"smartctl", "--all", "--json=c", "-d", "sat,12", "/dev/bsg/sssraid0"},
		{"smartctl", "--all", "--json=c", "-d", "sat+megaraid,1", "/dev/disk/by-id/ata-X_1.0"},
		{"smartctl", "--scan", "--json=c"},
		{"systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"},
		{"systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"},
		{"systemctl", "list-units", "--state=failed", "--no-legend", "--plain"},
		{"systemctl", "show", "-p", "Id,Names", "--", "nginx.service", "getty@tty1.service"},
		{"systemctl", "show", "-p", "Id,Names,ActiveState,MainPID", "--", "nginx"},
		{"systemctl", "show", "-p", "Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic",
			"--", `systemd-fsck@dev-disk-by\x2duuid-1a2b.service`, "user-runtime-dir@1000.service"},
		{"sc", "query", "state=", "all"},
		{"sc", "query", "MSSQL$SQLEXPRESS"},
		{"sc", "queryex", "wuauserv"},
		{"needs-restarting", "-r"},
		{"timedatectl", "show"},
		{"apt-get", "-s", "dist-upgrade"},
		{"dnf", "-C", "-q", "updateinfo", "list", "--security"},
	}
	for _, call := range calls {
		if !commandAllowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
}

// TestCommandKeyDropsTheWindowsExtension: on Windows exec.LookPath returns smartctl with ".exe" (in
// the case of PATHEXT); elsewhere the extension is part of the name.
func TestCommandKeyDropsTheWindowsExtension(t *testing.T) {
	dir := t.TempDir()
	cases := []struct {
		name    string
		windows bool
		want    string
	}{
		{filepath.Join(dir, "smartctl.exe"), true, "smartctl"},
		{filepath.Join(dir, "smartctl.EXE"), true, "smartctl"},
		{"sc.exe", true, "sc"},
		{filepath.Join(dir, "smartctl"), true, "smartctl"},
		{filepath.Join(dir, "smartctl.exe"), false, "smartctl.exe"},
		{filepath.Join(dir, "smartctl"), false, "smartctl"},
		{"smartctl.exe.bak", true, "smartctl.exe.bak"},
	}
	for _, c := range cases {
		if got := commandKey(c.name, c.windows); got != c.want {
			t.Errorf("commandKey(%q, %v) = %q, want %q", c.name, c.windows, got, c.want)
		}
	}
	if runtime.GOOS == "windows" && !commandAllowed(filepath.Join(dir, "smartctl.exe"), []string{"--scan", "--json=c"}) {
		t.Error("smartctl.exe refused on Windows")
	}
}

// TestAllowlistRefusesTheTraps is the negative test: the calls Konzept §3.6 keeps out (they write,
// repair, activate storages or run code in a container) and calls that bend an allowed one.
func TestAllowlistRefusesTheTraps(t *testing.T) {
	calls := [][]string{
		{"postfix", "check"},
		{"apt-get", "check"},
		{"apt-get", "update"},
		{"apt-get", "-s", "dist-upgrade", "-o", "Debug::NoLocking=1"},
		{"zpool", "scrub", "tank"},
		{"zpool", "list"},
		{"zpool", "status", "-x", "-v"},
		{"pvesh", "get", "/nodes/pve1/storage", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/storage", "--content", "backup", "--output-format", "json"},
		{"pvesh", "get", "/nodes/../status", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/storage/-x/content", "--content", "backup", "--output-format", "json"},
		{"pvesh", "set", "/nodes/pve1/status", "--output-format", "json"},
		{"pvesh", "get", "/cluster/resources", "--output-format", "json"},
		{"docker", "exec", "0123456789ab", "sh"},
		{"docker", "inspect", "--type", "container"},
		{"docker", "inspect", "--type", "container", "-f", "{{.Config}}"},
		{"docker", "ps", "-a"},
		{"smartctl", "-t", "short", "/dev/sda"},
		{"smartctl", "--all", "--json=c", "/dev/../etc/shadow"},
		{"smartctl", "--all", "--json=c", "/etc/passwd"},
		{"smartctl", "--all", "--json=c", "-d", "-x", "/dev/sda"},
		{"smartctl", "--all", "--json=c"},
		{"./smartctl", "--scan", "--json=c"},
		{"systemctl", "restart", "nginx"},
		{"systemctl", "show", "-p", "Id,Names", "--"},
		{"systemctl", "show", "-p", "Id,Names", "--", "--help"},
		{"systemctl", "show", "-p", "Id,Names", "--", "a b"},
		{"systemctl", "show", "-p", "Id,Names,ExecStart", "--", "nginx"},
		{"sc", "stop", "wuauserv"},
		{"sc", "query", "-x"},
		{"sc", "query", "two words"},
		{"needs-restarting"},
		{"timedatectl", "set-time", "2026-01-01"},
		{"dnf", "-q", "updateinfo", "list", "--security"},
		{"sh", "-c", "true"},
	}
	for _, call := range calls {
		if commandAllowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestRunTimedRefusesCallsOffTheList: a refused call does not start (the hanging helper would hold it
// for a minute) and its error names the allowlist, also through commandFailure.
func TestRunTimedRefusesCallsOffTheList(t *testing.T) {
	t.Setenv(dockerHelperEnv, "hang")
	start := time.Now()
	out, err := runTimed(context.Background(), time.Minute, os.Args[0], "-test.run=^TestHelperDockerProcess$")
	if elapsed := time.Since(start); elapsed > 10*time.Second {
		t.Errorf("runTimed returned after %s, the refused call started", elapsed)
	}
	if out != nil || !errors.Is(err, errCommandNotAllowed) {
		t.Fatalf("runTimed = %q, %v; want no output and errCommandNotAllowed", out, err)
	}
	if got, want := commandFailure("zpool", pluginTimeout, err), "zpool call not on the command allowlist"; got != want {
		t.Errorf("commandFailure = %q, want %q", got, want)
	}
	if _, err := runTimedEnv(context.Background(), time.Minute, []string{"LC_ALL=C"}, "apt-get", "check"); !errors.Is(err, errCommandNotAllowed) {
		t.Errorf("runTimedEnv(apt-get check) = %v, want errCommandNotAllowed", err)
	}
}
