// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// The box scripts of the multibox run (scripts/tests/box_*.sh) call this CLI on a VM
// only, and multibox_test.sh replaces every box by a fake: no local test sees those
// calls. These tests read them and run each against the real command tree, the way
// the box would (R-0333): `adminhelper-agent sync` went through every local check once.

// helperEnv makes the test binary run main() with these arguments instead of the
// tests: a subcommand that does not exist ends main() with os.Exit(1), which must end
// a helper process, not this one.
const helperEnv = "AH_BOX_CLI_HELPER_ARGS"

func TestMain(m *testing.M) {
	if args, ok := os.LookupEnv(helperEnv); ok {
		os.Args = append([]string{"adminhelper-agent"}, strings.Fields(args)...)
		main()
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// agentCall is one `adminhelper-agent …` call of a box script.
type agentCall struct {
	where string   // file:line
	words []string // the subcommands, e.g. frpc sync
	flags []string // the flag names, e.g. --once
}

var wordRE = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)

// commandPosition reports whether the token before adminhelper-agent leaves it in the
// place of a command: the start of the line, after sudo, $( or ( (with sudo), or an
// operator. `command -v adminhelper-agent` or `journalctl -u adminhelper-agent` is no call.
func commandPosition(prev string) bool {
	if i := strings.LastIndexByte(prev, '('); i >= 0 {
		prev = prev[i+1:]
	}
	switch prev {
	case "", "sudo", "&&", "||", ";", "|", "then", "do", "else":
		return true
	}
	return false
}

// shellOperator ends the arguments of a call: what follows is no longer the CLI's.
func shellOperator(tok string) bool {
	for _, p := range []string{"&&", "||", "|", ";", "\\", ">", "2>", "&", ")"} {
		if strings.HasPrefix(tok, p) {
			return true
		}
	}
	return strings.Contains(tok, ")")
}

// parseCalls finds the calls in the lines of one script. Subcommands are the words
// before the first flag; a flag is its name without a value; values are skipped.
func parseCalls(name string, lines []string) []agentCall {
	var calls []agentCall
	for i, line := range lines {
		if strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		toks := strings.Fields(line)
		for j, tok := range toks {
			if tok != "adminhelper-agent" {
				continue
			}
			prev := ""
			if j > 0 {
				prev = toks[j-1]
			}
			if !commandPosition(prev) {
				continue
			}
			c := agentCall{where: fmt.Sprintf("%s:%d", name, i+1)}
			for _, a := range toks[j+1:] {
				if shellOperator(a) {
					break
				}
				switch {
				case strings.HasPrefix(a, "-"):
					if k := strings.IndexByte(a, '='); k >= 0 {
						a = a[:k]
					}
					c.flags = append(c.flags, a)
				case len(c.flags) == 0 && wordRE.MatchString(a):
					c.words = append(c.words, a)
				}
			}
			if len(c.words) > 0 {
				calls = append(calls, c)
			}
		}
	}
	return calls
}

// checkCall runs `adminhelper-agent <words> --help` in a helper process: it must exit 0,
// and every flag of the call must be in that help.
func checkCall(c agentCall) error {
	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), helperEnv+"="+strings.Join(append(append([]string{}, c.words...), "--help"), " "))
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("adminhelper-agent %s --help: %v\n%s", strings.Join(c.words, " "), err, out)
	}
	for _, f := range c.flags {
		if !regexp.MustCompile(`(?m)(^|\s)` + regexp.QuoteMeta(f) + `(\s|=|,|$)`).Match(out) {
			return fmt.Errorf("adminhelper-agent %s has no flag %s", strings.Join(c.words, " "), f)
		}
	}
	return nil
}

func TestBoxScriptsCallTheAgentCLIAsItIs(t *testing.T) {
	dir := filepath.Join("..", "..", "..", "..", "scripts", "tests")
	files, err := filepath.Glob(filepath.Join(dir, "box_*.sh"))
	if err != nil || len(files) == 0 {
		t.Fatalf("no box scripts under %s (%v)", dir, err)
	}
	perFile := map[string]int{}
	for _, f := range files {
		data, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		base := filepath.Base(f)
		for _, c := range parseCalls(base, strings.Split(string(data), "\n")) {
			perFile[base]++
			if err := checkCall(c); err != nil {
				t.Errorf("%s: %v", c.where, err)
			}
		}
	}
	// The scripts that call the CLI. None found in one of them means the parser lost
	// them, or the script changed; then this list changes with it.
	for _, want := range []string{"box_agentbox.sh", "box_agentbox_rpm.sh", "box_tunnelbox.sh", "box_visitorbox.sh"} {
		if perFile[want] == 0 {
			t.Errorf("%s: no adminhelper-agent call found", want)
		}
	}
}

func TestBoxCLICheckCanFail(t *testing.T) {
	for _, c := range []struct {
		line string
		ok   bool
	}{
		{"sudo adminhelper-agent sync", false},
		{"adminhelper-agent run --onse && echo x", false},
		{`if out="$(sudo adminhelper-agent frpc sync 2>&1)"; then`, true},
		{`sudo adminhelper-agent provision --url "https://$SRV_IP" --insecure \`, true},
	} {
		calls := parseCalls("fixture", []string{c.line})
		if len(calls) != 1 {
			t.Fatalf("%q: %d calls parsed, want 1", c.line, len(calls))
		}
		if err := checkCall(calls[0]); (err == nil) != c.ok {
			t.Errorf("%q: check ok=%v, want ok=%v (%v)", c.line, err == nil, c.ok, err)
		}
	}
	for _, line := range []string{
		"command -v adminhelper-agent >/dev/null || exit 1",
		"journalctl -u adminhelper-agent --no-pager -n 300",
		"#   2. binary glibc linkage: extract + RUN adminhelper-agent provision",
		"tar -xO ./usr/bin/adminhelper-agent > /tmp/ah",
	} {
		if calls := parseCalls("fixture", []string{line}); len(calls) != 0 {
			t.Errorf("%q is no call, parsed %v", line, calls)
		}
	}
}
