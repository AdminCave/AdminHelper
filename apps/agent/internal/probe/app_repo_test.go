// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestRepoHelperExit is no test: run as a child (repoExit), it ends with the exit code it is given.
func TestRepoHelperExit(t *testing.T) {
	code := os.Getenv("AH_REPO_HELPER_EXIT")
	if code == "" {
		return
	}
	n, _ := strconv.Atoi(code)
	os.Exit(n)
}

// repoExit is the error of a command that ended with code and wrote stderr, as os/exec returns it.
func repoExit(t *testing.T, code int, stderr string) error {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestRepoHelperExit$")
	cmd.Env = append(os.Environ(), "AH_REPO_HELPER_EXIT="+strconv.Itoa(code))
	err := cmd.Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != code {
		t.Fatalf("helper exit %d = %v", code, err)
	}
	exitErr.Stderr = []byte(stderr)
	return exitErr
}

// envCall is one command a stub of runToolEnv got.
type envCall struct {
	env  []string
	args []string
}

// stubToolsEnv stands in for runToolEnv: it records each call with its environment, checks it against
// the allowlist and answers in turn.
func stubToolsEnv(t *testing.T, answers ...answer) *[]envCall {
	t.Helper()
	var calls []envCall
	old := runToolEnv
	runToolEnv = func(_ context.Context, _ time.Duration, env []string, name string, args ...string) ([]byte, error) {
		calls = append(calls, envCall{env: env, args: append([]string{name}, args...)})
		checkAllowed(t, name, args)
		if len(calls) > len(answers) {
			t.Errorf("call %q past the %d answers", calls[len(calls)-1].args, len(answers))
			return nil, errors.New("no answer")
		}
		a := answers[len(calls)-1]
		return []byte(a.out), a.err
	}
	t.Cleanup(func() { runToolEnv = old })
	return &calls
}

// unitShow is systemctl's answer for a unit with the environment env and the EnvironmentFiles files.
func unitShow(env string, files ...string) answer {
	out := "LoadState=loaded\nEnvironment=" + env + "\n"
	if len(files) == 0 {
		out += "EnvironmentFiles=\n"
	}
	for _, f := range files {
		out += "EnvironmentFiles=" + f + " (ignore_errors=no)\n"
	}
	return answer{out: out}
}

// envFileAt writes an EnvironmentFile with text and returns its path.
func envFileAt(t *testing.T, text string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "backup.env")
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

var repoPassword = appCredential{use: usePassword, secret: "Ge h31m"}

func TestUnitEnvironmentOfAUnitThatIsNotThere(t *testing.T) {
	stubTools(t, answer{out: "LoadState=not-found\nEnvironment=\nEnvironmentFiles=\n"})
	if _, err := unitEnvironment(context.Background(), "weg.service", "BORG_REPO"); err == nil || errors.Is(err, ErrUnsupported) {
		t.Errorf("a unit that does not exist = %v, want an error", err)
	}
	stubTools(t, answer{out: "something else\n"})
	if _, err := unitEnvironment(context.Background(), "x.service", "BORG_REPO"); err == nil {
		t.Error("an answer without LoadState was taken")
	}
	stubTools(t, answer{err: exec.ErrNotFound})
	if _, err := unitEnvironment(context.Background(), "x.service", "BORG_REPO"); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no systemctl = %v, want unsupported", err)
	}
}

func TestResticLatestReadsTheNewestSnapshot(t *testing.T) {
	stubNow(t, backupNow)
	stubTools(t, unitShow(`"RESTIC_REPOSITORY=/srv/restic/buchhaltung" RESTIC_PASSWORD=ausdemunit`))
	newest := backupNow.Add(-3 * time.Hour).UTC()
	calls := stubToolsEnv(t, answer{out: `[
		{"time":"` + backupNow.Add(-50*time.Hour).UTC().Format(time.RFC3339Nano) + `","hostname":"chef","paths":["/home"],"id":"aa"},
		{"time":"` + newest.Format(time.RFC3339Nano) + `","hostname":"lager","paths":["/etc"],"id":"bb"}]`})

	got, err := resticLatest(context.Background(), Target{Kind: kindUnit, Name: "restic-backup.service"}, repoPassword)
	if want := map[string]any{"has_snapshot": true, "snapshot_age_s": int64(3 * 3600)}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("restic_latest = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, "buchhaltung", "chef", "lager", "Ge h31m")
	want := []envCall{{env: []string{"RESTIC_REPOSITORY=/srv/restic/buchhaltung", "RESTIC_PASSWORD=Ge h31m"},
		args: []string{"restic", "snapshots", "--json", "--latest", "1", "--no-lock", "--no-cache"}}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls %q, want %q (the repository and the stored password in the environment)", *calls, want)
	}

	stubTools(t, unitShow(`RESTIC_REPOSITORY=sftp:backup@nas:/restic`))
	stubToolsEnv(t, answer{out: `[]`})
	got, err = resticLatest(context.Background(), Target{Kind: kindUnit, Name: "restic-backup.service"}, repoPassword)
	if want := map[string]any{"has_snapshot": false}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("an empty sftp repository = %v, %v; want %v", got, err, want)
	}
}

func TestResticLatestReadsOnlyALocalRepositoryWithItsPassword(t *testing.T) {
	unit := Target{Kind: kindUnit, Name: "restic-backup.service"}
	for name, env := range map[string]string{
		"no repository":    `RESTIC_PASSWORD_FILE=/etc/restic.pw`,
		"s3":               `RESTIC_REPOSITORY=s3:s3.amazonaws.com/bucket`,
		"rest server":      `RESTIC_REPOSITORY=rest:https://backup.example/`,
		"b2":               `RESTIC_REPOSITORY=b2:bucket:/pfad`,
		"rclone":           `RESTIC_REPOSITORY=rclone:remote:pfad`,
		"a relative path":  `RESTIC_REPOSITORY=repo`,
		"a path with dots": `RESTIC_REPOSITORY=/../etc`,
	} {
		stubTools(t, unitShow(env))
		calls := stubToolsEnv(t)
		if _, err := resticLatest(context.Background(), unit, repoPassword); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s = %v, want unsupported", name, err)
		}
		if len(*calls) != 0 {
			t.Errorf("%s: restic ran: %q", name, *calls)
		}
	}

	stubTools(t)
	calls := stubToolsEnv(t)
	if _, err := resticLatest(context.Background(), unit, appCredential{}); !errors.Is(err, ErrInvalid) {
		t.Errorf("no credential = %v, want invalid", err)
	}
	if _, err := resticLatest(context.Background(), unit, appCredential{use: usePassword}); !errors.Is(err, ErrInvalid) {
		t.Errorf("an empty password = %v, want invalid", err)
	}
	if len(*calls) != 0 {
		t.Errorf("restic ran without a password: %q", *calls)
	}
}

func TestResticLatestFailures(t *testing.T) {
	stubNow(t, backupNow)
	unit := Target{Kind: kindUnit, Name: "restic-backup.service"}
	cases := map[string]struct {
		a    answer
		want error
	}{
		"wrong password": {answer{err: repoExit(t, 12, `{"message_type":"exit_error","code":12,"message":"Fatal: wrong password"}`)}, ErrDenied},
		"no repository":  {answer{err: repoExit(t, 10, "Fatal: repository does not exist: /srv/restic/buchhaltung")}, nil},
		"not installed":  {answer{err: exec.ErrNotFound}, ErrUnsupported},
		"another form":   {answer{out: `{"snapshots":[]}`}, nil},
		"no time":        {answer{out: `[{"id":"aa"}]`}, nil},
	}
	for name, c := range cases {
		stubTools(t, unitShow(`RESTIC_REPOSITORY=/srv/restic/buchhaltung`))
		stubToolsEnv(t, c.a)
		_, err := resticLatest(context.Background(), unit, repoPassword)
		switch {
		case err == nil:
			t.Errorf("%s: no error", name)
		case c.want != nil && !errors.Is(err, c.want):
			t.Errorf("%s = %v, want %v", name, err, c.want)
		case strings.Contains(err.Error(), "buchhaltung") || strings.Contains(err.Error(), "Ge h31m"):
			t.Errorf("%s: the error quotes the repository or the password: %v", name, err)
		}
	}
}

func TestBorgLocal(t *testing.T) {
	for repo, want := range map[string]bool{
		"/srv/borg":                    true,
		"file:///srv/borg":             true,
		"ssh://backup@nas:2222/./borg": true,
		"backup@nas:borg":              true,
		"nas:/srv/borg":                true,
		"borg":                         false,
		"/../borg":                     false,
		"https://nas/borg":             false,
		"rclone://remote/borg":         false,
		"./borg:x":                     false,
		":borg":                        false,
	} {
		if got := borgLocal(repo); got != want {
			t.Errorf("borgLocal(%q) = %v, want %v", repo, got, want)
		}
	}
}

func TestBorgLatestFailures(t *testing.T) {
	unit := Target{Kind: kindUnit, Name: "borgbackup.service"}
	cases := map[string]struct {
		env  string
		a    []answer
		want error
	}{
		"no repository":       {`BORG_PASSCOMMAND=cat`, nil, ErrUnsupported},
		"a remote url":        {`BORG_REPO=https://nas/borg`, nil, ErrUnsupported},
		"wrong password":      {`BORG_REPO=/srv/borg`, []answer{{err: repoExit(t, 52, "passphrase supplied in BORG_PASSPHRASE is incorrect")}}, ErrDenied},
		"no repository there": {`BORG_REPO=/srv/borg`, []answer{{err: repoExit(t, 13, "Repository /srv/borg does not exist.")}}, nil},
		"not installed":       {`BORG_REPO=/srv/borg`, []answer{{err: exec.ErrNotFound}}, ErrUnsupported},
		"another form":        {`BORG_REPO=/srv/borg`, []answer{{out: `{"repository":{}}`}}, nil},
		"a time with a zone":  {`BORG_REPO=/srv/borg`, []answer{{out: `{"archives":[{"start":"2026-11-14T10:00:00+01:00"}]}`}}, nil},
	}
	for name, c := range cases {
		stubTools(t, unitShow(c.env))
		calls := stubToolsEnv(t, c.a...)
		_, err := borgLatest(context.Background(), unit, repoPassword)
		switch {
		case err == nil:
			t.Errorf("%s: no error", name)
		case c.want != nil && !errors.Is(err, c.want):
			t.Errorf("%s = %v, want %v", name, err, c.want)
		case strings.Contains(err.Error(), "/srv/borg"):
			t.Errorf("%s: the error quotes the repository: %v", name, err)
		}
		if len(*calls) != len(c.a) {
			t.Errorf("%s: %d calls of borg, want %d", name, len(*calls), len(c.a))
		}
	}
}

func TestDuplicatiHealth(t *testing.T) {
	unit := Target{Kind: kindUnit, Name: "duplicati.service"}
	for name, c := range map[string]struct {
		a    answer
		want map[string]any
	}{
		"healthy":   {answer{out: "Server is healthy\n"}, map[string]any{"healthy": true}},
		"unhealthy": {answer{out: "Server is unhealthy\n", err: repoExit(t, 1, "")}, map[string]any{"healthy": false}},
	} {
		calls := stubTools(t, c.a)
		got, err := duplicatiHealth(context.Background(), unit)
		if err != nil || !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s = %v, %v; want %v", name, got, err, c.want)
		}
		if want := [][]string{{"duplicati-server-util", "health"}}; !reflect.DeepEqual(*calls, want) {
			t.Errorf("%s: calls %q, want %q", name, *calls, want)
		}
	}
	for name, c := range map[string]struct {
		a    answer
		want error
	}{
		"no server":      {answer{err: repoExit(t, 100, "Failed to connect to http://localhost:8200")}, nil},
		"exit 1 unclear": {answer{out: "Error\n", err: repoExit(t, 1, "")}, nil},
		"another form":   {answer{out: "ok\n"}, nil},
		"not installed":  {answer{err: exec.ErrNotFound}, ErrUnsupported},
	} {
		stubTools(t, c.a)
		_, err := duplicatiHealth(context.Background(), unit)
		if err == nil || (c.want != nil && !errors.Is(err, c.want)) || strings.Contains(errText(err), "localhost") {
			t.Errorf("%s = %v, want an error (%v) without the server's address", name, err, c.want)
		}
	}
}

// errText is the text of err, "" for nil.
func errText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func TestTheRepositoryViewsTakeOnlyAPassword(t *testing.T) {
	for _, view := range []string{"restic_latest", "borg_latest", "kopia_latest"} {
		p := appProbe(view, unitTarget("backup.service"))
		for _, use := range []string{useBasic, useBearer, "header:X-Key"} {
			p.Credential = &Credential{Ref: "repo", Use: use}
			if _, err := appSensor(context.Background(), p, "x"); !errors.Is(err, ErrInvalid) {
				t.Errorf("%s with %s = %v, want invalid", view, use, err)
			}
		}
		p.Target = &Target{Kind: kindContainer, Name: "restic"}
		p.Credential = &Credential{Ref: "repo", Use: usePassword}
		if _, err := appSensor(context.Background(), p, "x"); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s on a container = %v, want invalid", view, err)
		}
	}
	p := appProbe("duplicati_health", unitTarget("duplicati.service"))
	p.Credential = &Credential{Ref: "repo", Use: usePassword}
	if _, err := appSensor(context.Background(), p, "x"); !errors.Is(err, ErrInvalid) {
		t.Errorf("duplicati_health with a password = %v, want invalid", err)
	}
}
