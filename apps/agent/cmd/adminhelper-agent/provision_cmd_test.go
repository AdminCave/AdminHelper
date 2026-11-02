// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"bytes"
	"io"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"

	"golang.org/x/term"
)

// provisionCall is what the provision command handed to provision.Run.
type provisionCall struct {
	url, token, serverID, cacert, caFP string
	insecure                           bool
}

// runProvisionCmd runs a fresh provision command with args and stdin against a
// recording runProvision; calls holds every call that reached it, out what the
// command wrote to stdout and stderr.
func runProvisionCmd(t *testing.T, stdin io.Reader, args ...string) (calls []provisionCall, out string, err error) {
	t.Helper()
	orig := runProvision
	t.Cleanup(func() { runProvision = orig })
	runProvision = func(url, token, serverID, cacert string, insecure bool, caFP string) error {
		calls = append(calls, provisionCall{url: url, token: token, serverID: serverID, cacert: cacert, caFP: caFP, insecure: insecure})
		return nil
	}
	var buf bytes.Buffer
	cmd := provisionCmd()
	cmd.SetArgs(args)
	cmd.SetIn(stdin)
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	err = cmd.Execute()
	return calls, buf.String(), err
}

// untouchedStdin is a stdin the command must not read.
type untouchedStdin struct{ read bool }

func (u *untouchedStdin) Read([]byte) (int, error) {
	u.read = true
	return 0, io.EOF
}

// endlessStdin never ends and never has a newline.
type endlessStdin struct{}

func (endlessStdin) Read(p []byte) (int, error) {
	for i := range p {
		p[i] = 'a'
	}
	return len(p), nil
}

var baseProvisionArgs = []string{"--url", "https://srm.example.com", "--server-id", "sid-1"}

func provisionArgs(extra ...string) []string {
	return append(append([]string{}, baseProvisionArgs...), extra...)
}

func TestProvisionCmdTokenFromStdin(t *testing.T) {
	for _, c := range []struct{ stdin, want string }{
		{"adminhelper_prov_test9\r\n", "adminhelper_prov_test9"},
		// Only the first line counts; what follows it stays unread.
		{" adminhelper_prov_test9\t\nzz9second-line\n", "adminhelper_prov_test9"},
		{"adminhelper_prov_test9", "adminhelper_prov_test9"},
	} {
		calls, _, err := runProvisionCmd(t, strings.NewReader(c.stdin), provisionArgs("--token-stdin")...)
		if err != nil {
			t.Fatalf("stdin %q: %v", c.stdin, err)
		}
		want := provisionCall{url: "https://srm.example.com", token: c.want, serverID: "sid-1"}
		if len(calls) != 1 || calls[0] != want {
			t.Errorf("stdin %q: calls %+v, want one %+v", c.stdin, calls, want)
		}
	}
}

func TestProvisionCmdTokenFlag(t *testing.T) {
	stdin := &untouchedStdin{}
	calls, _, err := runProvisionCmd(t, stdin, provisionArgs("--token", "tok-1")...)
	if err != nil {
		t.Fatal(err)
	}
	want := provisionCall{url: "https://srm.example.com", token: "tok-1", serverID: "sid-1"}
	if len(calls) != 1 || calls[0] != want {
		t.Errorf("calls %+v, want one %+v", calls, want)
	}
	if stdin.read {
		t.Error("--token read stdin")
	}
}

func TestProvisionCmdTokenFlagsExclusive(t *testing.T) {
	calls, _, err := runProvisionCmd(t, strings.NewReader("adminhelper_prov_test9\n"),
		provisionArgs("--token", "tok-1", "--token-stdin")...)
	if err == nil || !strings.Contains(err.Error(), "token-stdin") {
		t.Errorf("--token with --token-stdin: err %v, want the flag group error", err)
	}
	if len(calls) != 0 {
		t.Errorf("provision ran: %+v", calls)
	}
}

func TestProvisionCmdTokenRequired(t *testing.T) {
	calls, _, err := runProvisionCmd(t, strings.NewReader("adminhelper_prov_test9\n"), provisionArgs()...)
	if err == nil || !strings.Contains(err.Error(), "token-stdin") {
		t.Errorf("neither --token nor --token-stdin: err %v, want the flag group error", err)
	}
	if len(calls) != 0 {
		t.Errorf("provision ran: %+v", calls)
	}
}

func TestProvisionCmdEmptyStdin(t *testing.T) {
	for _, stdin := range []string{"", "\n", " \t\r\n", "\nzz9tok-late\n"} {
		calls, out, err := runProvisionCmd(t, strings.NewReader(stdin), provisionArgs("--token-stdin")...)
		if err == nil || err.Error() != "no provision token on stdin" {
			t.Errorf("stdin %q: err %v, want exactly %q", stdin, err, "no provision token on stdin")
		}
		if strings.Contains(out, "zz9") {
			t.Errorf("stdin %q: the output quotes stdin:\n%s", stdin, out)
		}
		if len(calls) != 0 {
			t.Errorf("stdin %q: provision ran: %+v", stdin, calls)
		}
	}
}

// A stdin that never sends a newline must not hold the command or grow its memory.
func TestProvisionCmdStdinBounded(t *testing.T) {
	calls, _, err := runProvisionCmd(t, endlessStdin{}, provisionArgs("--token-stdin")...)
	if err != nil {
		t.Fatal(err)
	}
	if len(calls) != 1 {
		t.Fatalf("%d call(s), want one", len(calls))
	}
	if n := len(calls[0].token); n != 4096 {
		t.Errorf("token of %d bytes, want the first 4096", n)
	}
}

func TestProvisionCmdHelpNamesTokenStdin(t *testing.T) {
	calls, out, err := runProvisionCmd(t, &untouchedStdin{}, "--help")
	if err != nil {
		t.Fatal(err)
	}
	if !regexp.MustCompile(`(?m)^\s+--token-stdin\s`).MatchString(out) {
		t.Errorf("the help has no flag --token-stdin:\n%s", out)
	}
	if len(calls) != 0 {
		t.Errorf("provision ran: %+v", calls)
	}
}

// fakeTerminal makes stdin a terminal that answers the no-echo read with answer.
func fakeTerminal(t *testing.T, answer []byte, err error) (reads *int) {
	t.Helper()
	origTerm, origRead := stdinTerminal, readTerminal
	t.Cleanup(func() { stdinTerminal, readTerminal = origTerm, origRead })
	reads = new(int)
	stdinTerminal = func(io.Reader) (int, bool) { return 7, true }
	readTerminal = func(fd int) ([]byte, error) {
		*reads++
		if fd != 7 {
			t.Errorf("read fd %d, want the terminal's 7", fd)
		}
		return answer, err
	}
	return reads
}

func TestReadStdinTokenTerminalReadsWithoutEcho(t *testing.T) {
	reads := fakeTerminal(t, []byte(" adminhelper_prov_test9 "), nil)
	stdin := &untouchedStdin{}
	calls, out, err := runProvisionCmd(t, stdin, provisionArgs("--token-stdin")...)
	if err != nil {
		t.Fatal(err)
	}
	if *reads != 1 || stdin.read {
		t.Errorf("%d no-echo read(s), stdin read %v; want one no-echo read and stdin untouched", *reads, stdin.read)
	}
	if len(calls) != 1 || calls[0].token != "adminhelper_prov_test9" {
		t.Errorf("calls %+v, want one with the trimmed token", calls)
	}
	if !strings.Contains(out, "Provision token: ") || strings.Contains(out, "zz9") {
		t.Errorf("output %q, want the prompt", out)
	}
}

func TestReadStdinTokenTerminalErrors(t *testing.T) {
	for name, c := range map[string]struct {
		answer []byte
		err    error
		want   string
	}{
		"empty":  {[]byte("  "), nil, "no provision token on stdin"},
		"failed": {nil, io.ErrUnexpectedEOF, "read the provision token from the terminal: unexpected EOF"},
	} {
		fakeTerminal(t, c.answer, c.err)
		calls, _, err := runProvisionCmd(t, &untouchedStdin{}, provisionArgs("--token-stdin")...)
		if err == nil || err.Error() != c.want {
			t.Errorf("%s: err %v, want %q", name, err, c.want)
		}
		if len(calls) != 0 {
			t.Errorf("%s: provision ran: %+v", name, calls)
		}
	}
}

func TestReadStdinTokenTerminalBounded(t *testing.T) {
	fakeTerminal(t, bytes.Repeat([]byte("a"), 3*maxStdinToken), nil)
	calls, _, err := runProvisionCmd(t, &untouchedStdin{}, provisionArgs("--token-stdin")...)
	if err != nil {
		t.Fatal(err)
	}
	if len(calls) != 1 || len(calls[0].token) != maxStdinToken {
		t.Errorf("calls %d, want one with a token of %d bytes", len(calls), maxStdinToken)
	}
}

// interruptHooks swaps the terminal-state and signal hooks of the no-echo read;
// sig is the channel the read registered for interrupts, restored the states
// handed to termRestore, exits the codes handed to exitProcess.
type interruptHooks struct {
	state    *term.State
	sig      chan<- os.Signal
	stopped  bool
	restored []*term.State
	exits    chan int
}

func fakeInterruptHooks(t *testing.T) *interruptHooks {
	t.Helper()
	origState, origRestore, origNotify, origStop, origExit := termState, termRestore, notifyInterrupt, stopInterrupt, exitProcess
	t.Cleanup(func() {
		termState, termRestore, notifyInterrupt, stopInterrupt, exitProcess = origState, origRestore, origNotify, origStop, origExit
	})
	h := &interruptHooks{state: &term.State{}, exits: make(chan int, 1)}
	termState = func(fd int) (*term.State, error) {
		if fd != 7 {
			t.Errorf("state of fd %d, want the terminal's 7", fd)
		}
		return h.state, nil
	}
	termRestore = func(fd int, s *term.State) error {
		h.restored = append(h.restored, s)
		return nil
	}
	notifyInterrupt = func(c chan<- os.Signal) { h.sig = c }
	stopInterrupt = func(c chan<- os.Signal) {
		if c != h.sig {
			t.Error("stopped another channel than the one registered")
		}
		h.stopped = true
	}
	exitProcess = func(code int) { h.exits <- code }
	return h
}

// Ctrl-C ends the process inside the no-echo read, before x/term puts the echo
// back: the read must restore the terminal itself and leave with 130.
func TestReadStdinTokenTerminalInterruptRestores(t *testing.T) {
	h := fakeInterruptHooks(t)
	reads := fakeTerminal(t, nil, nil)
	readTerminal = func(fd int) ([]byte, error) {
		*reads++
		if h.sig == nil {
			t.Error("no interrupt registered during the read")
			return nil, io.ErrUnexpectedEOF
		}
		h.sig <- os.Interrupt
		select {
		case code := <-h.exits:
			if code != 130 {
				t.Errorf("exit %d, want 130", code)
			}
		case <-time.After(10 * time.Second):
			t.Error("no exit after the interrupt")
		}
		return nil, io.ErrUnexpectedEOF
	}
	_, _, err := runProvisionCmd(t, &untouchedStdin{}, provisionArgs("--token-stdin")...)
	if err == nil {
		t.Error("the interrupted read returned no error")
	}
	if len(h.restored) != 1 || h.restored[0] != h.state {
		t.Errorf("restored %v, want the saved state once", h.restored)
	}
	if !h.stopped {
		t.Error("the interrupt stays caught after the read")
	}
}

func TestReadStdinTokenTerminalNoInterruptNoRestore(t *testing.T) {
	h := fakeInterruptHooks(t)
	fakeTerminal(t, []byte("adminhelper_prov_test9"), nil)
	calls, _, err := runProvisionCmd(t, &untouchedStdin{}, provisionArgs("--token-stdin")...)
	if err != nil || len(calls) != 1 {
		t.Fatalf("err %v, calls %+v; want one provision", err, calls)
	}
	if h.sig == nil || !h.stopped {
		t.Errorf("interrupt registered %v, stopped %v; want both", h.sig != nil, h.stopped)
	}
	if len(h.restored) != 0 || len(h.exits) != 0 {
		t.Errorf("restored %v, exits %d; want neither without an interrupt", h.restored, len(h.exits))
	}
}

// A pipe is no terminal: the real check must send it the line-reading way.
func TestReadStdinTokenPipeIsNoTerminal(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	if _, err := w.WriteString("adminhelper_prov_test9\n"); err != nil {
		t.Fatal(err)
	}
	w.Close()
	if _, ok := stdinTerminal(r); ok {
		t.Fatal("a pipe counts as a terminal")
	}
	calls, _, err := runProvisionCmd(t, r, provisionArgs("--token-stdin")...)
	if err != nil || len(calls) != 1 || calls[0].token != "adminhelper_prov_test9" {
		t.Errorf("err %v, calls %+v; want the token from the pipe", err, calls)
	}
}
