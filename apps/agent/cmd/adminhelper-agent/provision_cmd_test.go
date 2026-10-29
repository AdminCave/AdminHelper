// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"bytes"
	"io"
	"regexp"
	"strings"
	"testing"
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
