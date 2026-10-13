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

var (
	wordRE = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)
	// assignRE is a VAR=value in front of a command, as in `sudo LOG_LEVEL=debug …`.
	assignRE = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*=`)
	// mentionRE is the name as a word of its own: not ./usr/bin/adminhelper-agent, not
	// adminhelper-agent-*.rpm.
	mentionRE = regexp.MustCompile(`(^|[\s"'(;|&{!])adminhelper-agent($|[\s"');|&}])`)
)

// wrapper is a token that runs the next one: what stands before it decides.
func wrapper(tok string) bool {
	switch tok {
	case "sudo", "$SUDO", "${SUDO}", "\"$SUDO\"", "-E", "exec", "time", "!", "{":
		return true
	}
	return assignRE.MatchString(tok)
}

// commandStart reports whether a command starts after this token: the start of the
// line, an operator, or a keyword that runs what follows.
func commandStart(prev string) bool {
	switch prev {
	case "", "&&", "||", ";", "|", "then", "do", "else", "if", "while", "until", "(":
		return true
	}
	return false
}

// nonCall reports the mentions that name the unit or the binary, not a call of the
// CLI: `command -v adminhelper-agent`, `journalctl -u adminhelper-agent`, systemctl.
func nonCall(prev string) bool {
	switch prev {
	case "-v", "-u", "--unit", "restart", "start", "stop", "status", "enable", "disable", "is-active":
		return true
	}
	return false
}

// shellOperator ends the arguments of a call: what follows is no longer the CLI's.
// An operator glued to a word (sync)", --once>/dev/null) is cut off in parseCalls.
func shellOperator(tok string) bool {
	for _, p := range []string{"&&", "||", "|", ";", "\\", ">", "2>", "&", ")"} {
		if strings.HasPrefix(tok, p) {
			return true
		}
	}
	return false
}

// logicalLines joins a line that ends in a backslash with the next, keeping the
// number of the first: a call's subcommands or flags may sit on the next line.
func logicalLines(lines []string) (joined []string, numbers []int) {
	for i := 0; i < len(lines); i++ {
		n, l := i+1, lines[i]
		// bash does not continue a comment: its backslash joins nothing.
		for !strings.HasPrefix(strings.TrimSpace(l), "#") &&
			strings.HasSuffix(strings.TrimRight(l, " \t\r"), "\\") && i+1 < len(lines) {
			l = strings.TrimSuffix(strings.TrimRight(l, " \t\r"), "\\") + " " + lines[i+1]
			i++
		}
		joined, numbers = append(joined, l), append(numbers, n)
	}
	return joined, numbers
}

// parseCalls finds the calls in the lines of one script. Subcommands are the words
// before the first flag; a flag is its name without a value; values are skipped.
// A mention of the name that is neither a call nor a known non-call is reported in
// unknown: a form the parser does not know must not pass as checked.
func parseCalls(name string, lines []string) (calls []agentCall, unknown []string) {
	joined, numbers := logicalLines(lines)
	for i, line := range joined {
		if strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		where := fmt.Sprintf("%s:%d", name, numbers[i])
		toks := strings.Fields(line)
		mentions, found := len(mentionRE.FindAllStringIndex(line, -1)), 0
		for j, tok := range toks {
			// "$(adminhelper-agent or (adminhelper-agent: the name starts a command.
			inParen := false
			if k := strings.LastIndexByte(tok, '('); k >= 0 {
				tok, inParen = tok[k+1:], true
			}
			if tok != "adminhelper-agent" {
				continue
			}
			// Walk back over wrappers to what decides. A token with ( in it ends the walk
			// before it could pass as a VAR=… prefix: out="$(sudo starts a command.
			prev := ""
			for k := j - 1; !inParen && k >= 0; k-- {
				tk := toks[k]
				if m := strings.LastIndexByte(tk, '('); m >= 0 {
					if rest := tk[m+1:]; rest == "" || wrapper(rest) {
						prev = "("
					} else {
						prev = rest
					}
					break
				}
				if !wrapper(tk) {
					prev = tk
					break
				}
			}
			if nonCall(prev) {
				found++
				continue
			}
			if !inParen && !commandStart(prev) {
				continue
			}
			found++
			c := agentCall{where: where}
			for _, a := range toks[j+1:] {
				if shellOperator(a) {
					break
				}
				// An operator glued to a word ends the call there: sync)", --once>/dev/null.
				cut := strings.IndexAny(a, "<>;|&)")
				if cut >= 0 {
					a = a[:cut]
				}
				switch {
				case strings.HasPrefix(a, "-"):
					if e := strings.IndexByte(a, '='); e >= 0 {
						a = a[:e]
					}
					c.flags = append(c.flags, a)
				case len(c.flags) == 0 && wordRE.MatchString(a):
					c.words = append(c.words, a)
				}
				if cut >= 0 {
					break
				}
			}
			if len(c.words) > 0 {
				calls = append(calls, c)
			} else {
				unknown = append(unknown, where+": a call of adminhelper-agent without a subcommand")
			}
		}
		if found < mentions {
			unknown = append(unknown, where+": adminhelper-agent in a form the check does not know: "+strings.TrimSpace(line))
		}
	}
	return calls, unknown
}

// checkCall runs `adminhelper-agent <words> --help` in a helper process: it must exit 0,
// and every flag of the call must be in that help.
func checkCall(c agentCall) error {
	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), helperEnv+"="+strings.Join(append(append([]string{}, c.words...), "--help"), " "))
	out, err := cmd.CombinedOutput()
	path := "adminhelper-agent " + strings.Join(c.words, " ")
	if err != nil {
		return fmt.Errorf("%s --help: %v\n%s", path, err, out)
	}
	// cobra checks the subcommand only at the root: `frpc snyc --help` prints the help
	// of frpc and exits 0. The help's usage line must name the whole path.
	if !regexp.MustCompile(`(?m)^\s+` + regexp.QuoteMeta(path) + `( |$)`).Match(out) {
		return fmt.Errorf("%s: the help is not the one of this command (no usage line %q)", path, path)
	}
	// In the table of flags, not anywhere in the text of the help.
	for _, f := range c.flags {
		if !regexp.MustCompile(`(?m)^\s+(-\w, )?` + regexp.QuoteMeta(f) + `([\s=]|$)`).Match(out) {
			return fmt.Errorf("%s has no flag %s", path, f)
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
		calls, unknown := parseCalls(base, strings.Split(string(data), "\n"))
		for _, u := range unknown {
			t.Error(u)
		}
		for _, c := range calls {
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
		calls, _ := parseCalls("fixture", []string{c.line})
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
		if calls, _ := parseCalls("fixture", []string{line}); len(calls) != 0 {
			t.Errorf("%q is no call, parsed %v", line, calls)
		}
	}
}

// The forms the first round of review found: a typo below the root, continued lines,
// $( without sudo, wrappers, and mentions the parser does not know, which must fail
// loud instead of passing unchecked.
func TestBoxCLICheckSeesEveryForm(t *testing.T) {
	for _, c := range []struct {
		lines []string
		ok    bool
	}{
		{[]string{"sudo adminhelper-agent frpc snyc"}, false},
		{[]string{"adminhelper-agent provision --insecure \\", "  --ca-fpp x && echo ok"}, false},
		{[]string{`-u x="$(sudo adminhelper-agent frpc snyc)"`}, false},
		{[]string{"# a note \\", "sudo adminhelper-agent frpc snyc"}, false},
		{[]string{`ver="$(adminhelper-agent version)"`}, true},
		{[]string{"sudo adminhelper-agent \\", "  frpc sync"}, true},
		{[]string{"sudo LOG_LEVEL=debug adminhelper-agent run --once>/dev/null"}, true},
		{[]string{`sudo adminhelper-agent provision --url "https://$SRV_IP" --insecure \`, `  --token "$T"`}, true},
		{[]string{`local out="$(sudo adminhelper-agent frpc sync 2>&1)"`}, true},
	} {
		calls, unknown := parseCalls("fixture", c.lines)
		if len(calls) != 1 || len(unknown) != 0 {
			t.Fatalf("%q: %d calls, unknown %v; want 1 call", c.lines, len(calls), unknown)
		}
		if err := checkCall(calls[0]); (err == nil) != c.ok {
			t.Errorf("%q: check ok=%v, want ok=%v (%v)", c.lines, err == nil, c.ok, err)
		}
	}
	for _, line := range []string{
		"$SUDO journalctl -u adminhelper-agent --no-pager -n 300",
		`RPM="$(ls -1 ./adminhelper-agent-*.rpm 2>/dev/null | head -1)"`,
	} {
		if calls, unknown := parseCalls("fixture", []string{line}); len(calls) != 0 || len(unknown) != 0 {
			t.Errorf("%q is no call: parsed %v, unknown %v", line, calls, unknown)
		}
	}
	if _, unknown := parseCalls("fixture", []string{"timeout 60 adminhelper-agent run --once"}); len(unknown) == 0 {
		t.Error("an unknown form of a call passed silently")
	}
}
