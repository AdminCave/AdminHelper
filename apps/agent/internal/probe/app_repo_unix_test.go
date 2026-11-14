// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestUnitEnvironmentTakesTheUnitsWordsAndItsFile(t *testing.T) {
	file := envFileAt(t, "# a comment\n; another\nRESTIC_REPOSITORY = \"/srv/aus der Datei\"\nRESTIC_PASSWORD=nie\nOTHER=x\n")
	// systemd 257's form: a word with a space or a quote is quoted whole, \" inside.
	stubTools(t, unitShow(`"RESTIC_REPOSITORY=/srv/aus dem Unit" OTHER=y "Q=x\"y"`, file))
	env, err := unitEnvironment(context.Background(), "restic-backup.service", "RESTIC_REPOSITORY", "Q")
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]string{"RESTIC_REPOSITORY": "/srv/aus der Datei", "Q": `x"y`}; !reflect.DeepEqual(env, want) {
		t.Errorf("environment %q, want %q (the file overrides, only the keys asked for)", env, want)
	}

	stubTools(t, unitShow(`"RESTIC_REPOSITORY=/srv/aus dem Unit"`, "/gibt/es/nicht.env", "relativ.env"))
	env, err = unitEnvironment(context.Background(), "restic-backup.service", "RESTIC_REPOSITORY")
	if err != nil || env["RESTIC_REPOSITORY"] != "/srv/aus dem Unit" {
		t.Errorf("an unreadable file = %q, %v; want the unit's word", env, err)
	}
}

func TestBorgLatestReadsTheNewestArchive(t *testing.T) {
	stubNow(t, backupNow)
	file := envFileAt(t, "BORG_REPO=ssh://backup@nas/./lager\nBORG_PASSPHRASE=ausderdatei\n")
	stubTools(t, unitShow(``, file))
	start := backupNow.Add(-26 * time.Hour).Format(borgTime)
	calls := stubToolsEnv(t, answer{out: `{"archives":[{"archive":"lager-2026","name":"lager-2026","start":"` + start +
		`","time":"` + start + `"}],"encryption":{"mode":"repokey"},"repository":{"location":"ssh://backup@nas/./lager"}}`})

	got, err := borgLatest(context.Background(), Target{Kind: kindUnit, Name: "borgbackup.service"}, repoPassword)
	if want := map[string]any{"has_snapshot": true, "snapshot_age_s": int64(26 * 3600)}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("borg_latest = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, "lager", "nas", "Ge h31m")
	want := []envCall{{env: []string{"BORG_REPO=ssh://backup@nas/./lager", "BORG_EXIT_CODES=modern",
		"BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=no", "BORG_RELOCATED_REPO_ACCESS_IS_OK=no", "BORG_PASSPHRASE=Ge h31m"},
		args: []string{"borg", "list", "--last", "1", "--json", "--bypass-lock"}}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls %q, want %q", *calls, want)
	}

	stubTools(t, unitShow(`BORG_REPO=/srv/borg`))
	stubToolsEnv(t, answer{out: `{"archives":[],"repository":{}}`})
	got, err = borgLatest(context.Background(), Target{Kind: kindUnit, Name: "borgbackup.service"}, repoPassword)
	if want := map[string]any{"has_snapshot": false}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("an empty repository = %v, %v; want %v", got, err, want)
	}
}

// kopiaConfigAt writes a repository.config of storage type kind and returns its path.
func kopiaConfigAt(t *testing.T, kind string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "repository.config")
	conf := `{"storage":{"type":"` + kind + `","config":{"path":"/srv/kopia/chef"}},"hostname":"chef","username":"root"}`
	if err := os.WriteFile(path, []byte(conf), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestKopiaLatestReadsTheNewestSnapshot(t *testing.T) {
	stubNow(t, backupNow)
	conf := kopiaConfigAt(t, "filesystem")
	stubTools(t, unitShow(`KOPIA_CONFIG_PATH=`+conf))
	calls := stubToolsEnv(t, answer{out: `[
		{"id":"k1","source":{"host":"chef","userName":"root","path":"/home"},"startTime":"` +
		backupNow.Add(-2*time.Hour).UTC().Format(time.RFC3339Nano) + `","endTime":"` + backupNow.Add(-time.Hour).UTC().Format(time.RFC3339Nano) + `"},
		{"id":"k2","source":{"host":"chef","userName":"root","path":"/etc"},"startTime":"` +
		backupNow.Add(-30*time.Hour).UTC().Format(time.RFC3339Nano) + `","endTime":"` + backupNow.Add(-29*time.Hour).UTC().Format(time.RFC3339Nano) + `"}]`})

	got, err := kopiaLatest(context.Background(), Target{Kind: kindUnit, Name: "kopia.service"}, repoPassword)
	if want := map[string]any{"has_snapshot": true, "snapshot_age_s": int64(3600)}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("kopia_latest = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, "chef", "/home", "Ge h31m")
	want := []envCall{{env: []string{"KOPIA_CONFIG_PATH=" + conf, "KOPIA_PASSWORD=Ge h31m"},
		args: []string{"kopia", "snapshot", "list", "--json", "-n", "1"}}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls %q, want %q", *calls, want)
	}
}

func TestKopiaLatestFailures(t *testing.T) {
	unit := Target{Kind: kindUnit, Name: "kopia.service"}
	fs, s3 := kopiaConfigAt(t, "filesystem"), kopiaConfigAt(t, "s3")
	cases := map[string]struct {
		env  string
		a    []answer
		want error
	}{
		"s3":              {`KOPIA_CONFIG_PATH=` + s3, nil, ErrUnsupported},
		"no config":       {`KOPIA_CONFIG_PATH=` + filepath.Join(t.TempDir(), "fehlt.config"), nil, ErrUnsupported},
		"a relative path": {`KOPIA_CONFIG_PATH=repository.config`, nil, ErrInvalid},
		"wrong password":  {`KOPIA_CONFIG_PATH=` + fs, []answer{{err: repoExit(t, 1, "ERROR error connecting to repository: invalid repository password")}}, ErrDenied},
		"another error":   {`KOPIA_CONFIG_PATH=` + fs, []answer{{err: repoExit(t, 1, "ERROR unable to open /srv/kopia/chef")}}, nil},
		"killed":          {`KOPIA_CONFIG_PATH=` + fs, []answer{{err: &exec.ExitError{}}}, nil},
		"not installed":   {`KOPIA_CONFIG_PATH=` + fs, []answer{{err: exec.ErrNotFound}}, ErrUnsupported},
		"no time":         {`KOPIA_CONFIG_PATH=` + fs, []answer{{out: `[{"id":"k1"}]`}}, nil},
	}
	for name, c := range cases {
		stubTools(t, unitShow(c.env))
		calls := stubToolsEnv(t, c.a...)
		_, err := kopiaLatest(context.Background(), unit, repoPassword)
		switch {
		case err == nil:
			t.Errorf("%s: no error", name)
		case c.want != nil && !errors.Is(err, c.want):
			t.Errorf("%s = %v, want %v", name, err, c.want)
		case c.want == nil && errors.Is(err, ErrDenied):
			t.Errorf("%s = %v, taken for a refused password", name, err)
		case strings.Contains(err.Error(), "/srv/kopia"):
			t.Errorf("%s: the error quotes the repository: %v", name, err)
		}
		if len(*calls) != len(c.a) {
			t.Errorf("%s: %d calls of kopia, want %d", name, len(*calls), len(c.a))
		}
	}
}
