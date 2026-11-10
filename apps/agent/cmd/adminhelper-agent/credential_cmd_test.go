// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"bytes"
	"io"
	"os"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/credentials"
)

// runCredential runs `monitor credential <args>` with stdin and returns stdout, stderr and the error.
func runCredential(t *testing.T, stdin string, args ...string) (string, string, error) {
	t.Helper()
	cmd := monitorCmd()
	var out, errOut bytes.Buffer
	cmd.SetArgs(append([]string{"credential"}, args...))
	cmd.SetIn(strings.NewReader(stdin))
	cmd.SetOut(&out)
	cmd.SetErr(&errOut)
	err := cmd.Execute()
	return out.String(), errOut.String(), err
}

func TestMonitorCredentialSetStoresTheSecretFromStdin(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())

	out, errOut, err := runCredential(t, "s3cret-pw\n", "set", "db/main")
	if err != nil {
		t.Fatalf("credential set: %v", err)
	}
	if strings.TrimSpace(out) != "credential db/main stored" {
		t.Errorf("stdout = %q", out)
	}
	if strings.Contains(out+errOut, "s3cret-pw") {
		t.Errorf("the secret was printed: %q %q", out, errOut)
	}
	creds, err := credentials.Load(config.MonitorCredentialsFile())
	if err != nil || creds["db/main"].Secret != "s3cret-pw" {
		t.Fatalf("stored = %v, %v; want db/main", credentials.Refs(creds), err)
	}
}

func TestMonitorCredentialSetRefusesWhatItCannotStore(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())

	for _, c := range []struct {
		name, stdin string
		args        []string
		want        string
	}{
		{"no ref", "pw\n", []string{"set"}, "accepts 1 arg"},
		{"a ref the monitoring cannot name", "pw\n", []string{"set", "../etc"}, "invalid ref"},
		{"no secret", "\n", []string{"set", "db"}, "no credential on stdin"},
		{"a secret with a control character", "a\tb\n", []string{"set", "db"}, "control character"},
	} {
		t.Run(c.name, func(t *testing.T) {
			out, errOut, err := runCredential(t, c.stdin, c.args...)
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("credential %v: %v, want %q", c.args, err, c.want)
			}
			if strings.Contains(out+errOut+err.Error(), "a\tb") {
				t.Errorf("the secret was printed: %q %q %v", out, errOut, err)
			}
		})
	}
	if _, err := os.Stat(config.MonitorCredentialsFile()); !os.IsNotExist(err) {
		t.Errorf("a refused set wrote %s: %v", config.MonitorCredentialsFile(), err)
	}
}

// readWatch fails the test when the command reads it.
type readWatch struct{ t *testing.T }

func (r readWatch) Read([]byte) (int, error) {
	r.t.Error("the secret was read before the ref was checked")
	return 0, io.EOF
}

func TestMonitorCredentialSetChecksTheRefBeforeTheSecret(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	cmd := monitorCmd()
	cmd.SetArgs([]string{"credential", "set", "no ref!"})
	cmd.SetIn(readWatch{t})
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)

	if err := cmd.Execute(); err == nil || !strings.Contains(err.Error(), "invalid ref") {
		t.Fatalf("credential set with a bad ref: %v, want invalid ref", err)
	}
}

func TestMonitorCredentialListAndDelete(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	for _, ref := range []string{"web", "db"} {
		if _, _, err := runCredential(t, "pw-"+ref+"\n", "set", ref); err != nil {
			t.Fatal(err)
		}
	}

	out, _, err := runCredential(t, "", "list")
	if err != nil || out != "db\nweb\n" {
		t.Fatalf("credential list = %q, %v; want the refs sorted", out, err)
	}
	if strings.Contains(out, "pw-") {
		t.Errorf("list printed a secret: %q", out)
	}

	out, _, err = runCredential(t, "", "delete", "db")
	if err != nil || strings.TrimSpace(out) != "credential db deleted" {
		t.Fatalf("credential delete = %q, %v", out, err)
	}
	if _, _, err := runCredential(t, "", "delete", "db"); err == nil || !strings.Contains(err.Error(), "no credential stored") {
		t.Errorf("deleting it again: %v, want no credential stored", err)
	}
	if out, _, err := runCredential(t, "", "list"); err != nil || out != "web\n" {
		t.Errorf("credential list after the delete = %q, %v; want web alone", out, err)
	}
}
